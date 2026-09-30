import json
import uuid
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.models import (
    AdminPlan,
    Customer,
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentProfile,
    PaymentStatus,
    Plan,
    User,
    Wallet,
    WalletTxnType,
)
from app.services.customer_wallet import (
    CustomerInsufficientFundsError,
    apply_customer_wallet_transaction,
)
from app.services.gateways import GatewayRequestError, build_gateway
from app.services.orders import provision_paid_order
from app.services.wallet import apply_wallet_transaction

settings = get_settings()
GIB = Decimal(1024**3)


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


async def get_or_create_customer(
    db: AsyncSession,
    *,
    admin_id: uuid.UUID,
    telegram_user_id: int | None = None,
    username: str | None = None,
    display_name: str | None = None,
) -> Customer:
    customer = None
    if telegram_user_id is not None:
        customer = await db.scalar(
            select(Customer).where(
                Customer.admin_id == admin_id,
                Customer.telegram_user_id == telegram_user_id,
            )
        )
    if customer is None:
        customer = Customer(
            admin_id=admin_id,
            telegram_user_id=telegram_user_id,
            username=username,
            display_name=display_name,
        )
        db.add(customer)
        await db.flush()
    else:
        if username is not None:
            customer.username = username
        if display_name is not None:
            customer.display_name = display_name
    return customer


async def create_order(
    db: AsyncSession,
    *,
    admin_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    plan_id: uuid.UUID,
    quota_gib: Decimal,
    duration_days: int | None,
    payment_method: PaymentMethod,
) -> Order:
    if quota_gib <= 0:
        raise ValueError("quota must be positive")

    plan = await db.scalar(select(Plan).where(Plan.id == plan_id, Plan.enabled.is_(True)))
    if not plan:
        raise ValueError("plan not found or disabled")

    admin_plan = await db.scalar(
        select(AdminPlan).where(
            AdminPlan.admin_id == admin_id,
            AdminPlan.plan_id == plan.id,
            AdminPlan.enabled.is_(True),
        )
    )
    if not admin_plan:
        raise PermissionError("plan is not assigned to this admin")

    if plan.min_quota_gib is not None and quota_gib < Decimal(plan.min_quota_gib):
        raise ValueError("quota below plan minimum")
    if plan.max_quota_gib is not None and quota_gib > Decimal(plan.max_quota_gib):
        raise ValueError("quota above plan maximum")
    if plan.max_duration_days is not None and duration_days and duration_days > plan.max_duration_days:
        raise ValueError("duration above plan maximum")

    retail = money(Decimal(admin_plan.retail_price_per_gib_toman) * Decimal(quota_gib))
    order = Order(
        admin_id=admin_id,
        customer_id=customer_id,
        plan_id=plan.id,
        quota_bytes=int(Decimal(quota_gib) * GIB),
        duration_days=duration_days,
        retail_amount_toman=retail,
        payment_method=payment_method,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    await db.flush()
    return order


async def pay_order_from_customer_wallet(db: AsyncSession, order: Order):
    if not order.customer_id:
        raise ValueError("customer is required for customer-wallet payment")
    txn = await apply_customer_wallet_transaction(
        db,
        customer_id=order.customer_id,
        amount_toman=-Decimal(order.retail_amount_toman),
        txn_type="order_payment",
        idempotency_key=f"order-wallet:{order.id}",
        reference_type="order",
        reference_id=str(order.id),
        description="PRIMEVPN order paid from customer wallet",
    )
    payment = Payment(
        admin_id=order.admin_id,
        customer_id=order.customer_id,
        order_id=order.id,
        method=PaymentMethod.CUSTOMER_WALLET,
        status=PaymentStatus.PAID,
        amount_toman=order.retail_amount_toman,
        provider="customer_wallet",
        provider_reference=str(txn.id),
        meta={"purpose": "order_wallet"},
    )
    db.add(payment)
    order.status = OrderStatus.PAID
    await db.flush()
    client = await provision_paid_order(db, order.id)
    return payment, client


async def create_card_order_payment(db: AsyncSession, order: Order) -> Payment:
    profile = await db.scalar(
        select(PaymentProfile).where(PaymentProfile.owner_user_id == order.admin_id)
    )
    if not profile or not profile.card_to_card_enabled or not profile.card_number:
        raise ValueError("admin card-to-card payment is not configured")

    payment = Payment(
        admin_id=order.admin_id,
        customer_id=order.customer_id,
        order_id=order.id,
        method=PaymentMethod.CARD_TO_CARD,
        status=PaymentStatus.AWAITING_REVIEW,
        amount_toman=order.retail_amount_toman,
        provider="card_to_card",
        meta={"purpose": "order_card"},
    )
    db.add(payment)
    await db.flush()
    return payment


async def create_gateway_payment(
    db: AsyncSession,
    *,
    payment: Payment,
    profile_owner_user_id: uuid.UUID,
    description: str,
):
    profile = await db.scalar(
        select(PaymentProfile).where(PaymentProfile.owner_user_id == profile_owner_user_id)
    )
    if (
        not profile
        or not profile.gateway_enabled
        or not profile.gateway_provider
        or not profile.encrypted_gateway_credentials
    ):
        raise ValueError("payment gateway is not configured")

    credentials = json.loads(decrypt_secret(profile.encrypted_gateway_credentials))
    gateway = build_gateway(profile.gateway_provider, credentials)
    callback_url = (
        settings.public_web_url.rstrip("/")
        + f"/api/backend/api/v1/gateway/callback/{payment.id}"
    )
    result = await gateway.create_payment(
        amount_toman=Decimal(payment.amount_toman),
        callback_url=callback_url,
        description=description,
        metadata={"payment_id": str(payment.id)},
    )
    payment.provider = profile.gateway_provider
    payment.provider_reference = result.authority
    payment.meta = {
        **(payment.meta or {}),
        "gateway_authority": result.authority,
        "redirect_url": result.redirect_url,
    }
    await db.flush()
    return result


async def create_gateway_order_payment(db: AsyncSession, order: Order):
    payment = Payment(
        admin_id=order.admin_id,
        customer_id=order.customer_id,
        order_id=order.id,
        method=PaymentMethod.GATEWAY,
        status=PaymentStatus.PENDING,
        amount_toman=order.retail_amount_toman,
        meta={"purpose": "order_gateway"},
    )
    db.add(payment)
    await db.flush()
    result = await create_gateway_payment(
        db,
        payment=payment,
        profile_owner_user_id=order.admin_id,
        description=f"PRIMEVPN order {order.id}",
    )
    return payment, result


async def create_admin_gateway_topup(
    db: AsyncSession,
    *,
    admin: User,
    amount_toman: Decimal,
):
    owner = await db.scalar(select(User).where(User.role == "owner"))
    if not owner:
        raise ValueError("owner not found")
    payment = Payment(
        admin_id=admin.id,
        customer_id=None,
        order_id=None,
        method=PaymentMethod.GATEWAY,
        status=PaymentStatus.PENDING,
        amount_toman=money(amount_toman),
        meta={
            "purpose": "admin_wallet_topup_gateway",
            "destination_owner_id": str(owner.id),
        },
    )
    db.add(payment)
    await db.flush()
    result = await create_gateway_payment(
        db,
        payment=payment,
        profile_owner_user_id=owner.id,
        description=f"PRIMEVPN wallet top-up for {admin.username}",
    )
    return payment, result


async def verify_gateway_payment(
    db: AsyncSession,
    *,
    payment_id: uuid.UUID,
    authority: str,
    callback_status: str | None,
):
    payment = await db.scalar(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    )
    if not payment:
        raise ValueError("payment not found")
    if payment.status == PaymentStatus.PAID:
        return payment, None
    if payment.method != PaymentMethod.GATEWAY:
        raise ValueError("payment is not a gateway payment")
    if callback_status and callback_status.upper() != "OK":
        payment.status = PaymentStatus.FAILED
        await db.flush()
        return payment, None
    if payment.provider_reference != authority:
        raise ValueError("gateway authority mismatch")

    purpose = (payment.meta or {}).get("purpose")
    if purpose == "order_gateway":
        profile_owner_id = payment.admin_id
    elif purpose == "admin_wallet_topup_gateway":
        profile_owner_id = uuid.UUID((payment.meta or {})["destination_owner_id"])
    elif purpose == "customer_wallet_topup_gateway":
        profile_owner_id = payment.admin_id
    else:
        raise ValueError("unsupported gateway payment purpose")

    profile = await db.scalar(
        select(PaymentProfile).where(PaymentProfile.owner_user_id == profile_owner_id)
    )
    if not profile or not profile.encrypted_gateway_credentials or not profile.gateway_provider:
        raise ValueError("gateway profile unavailable")
    credentials = json.loads(decrypt_secret(profile.encrypted_gateway_credentials))
    gateway = build_gateway(profile.gateway_provider, credentials)
    result = await gateway.verify_payment(
        authority=authority,
        amount_toman=Decimal(payment.amount_toman),
    )
    if not result.paid:
        payment.status = PaymentStatus.FAILED
        payment.meta = {**(payment.meta or {}), "verify": result.raw or {}}
        await db.flush()
        return payment, None

    payment.status = PaymentStatus.PAID
    payment.provider_reference = result.reference or authority
    payment.meta = {**(payment.meta or {}), "verify": result.raw or {}}

    client = None
    if purpose == "order_gateway":
        if not payment.order_id:
            raise ValueError("gateway order payment has no order")
        order = await db.scalar(select(Order).where(Order.id == payment.order_id).with_for_update())
        if not order:
            raise ValueError("order not found")
        order.status = OrderStatus.PAID
        client = await provision_paid_order(db, order.id)

    elif purpose == "admin_wallet_topup_gateway":
        wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == payment.admin_id))
        if not wallet:
            raise ValueError("admin wallet not found")
        await apply_wallet_transaction(
            db,
            wallet_id=wallet.id,
            txn_type=WalletTxnType.GATEWAY_TOPUP,
            amount_toman=Decimal(payment.amount_toman),
            idempotency_key=f"gateway-payment:{payment.id}",
            reference_type="payment",
            reference_id=str(payment.id),
            description="Gateway wallet top-up",
        )

    elif purpose == "customer_wallet_topup_gateway":
        if not payment.customer_id:
            raise ValueError("customer wallet payment has no customer")
        await apply_customer_wallet_transaction(
            db,
            customer_id=payment.customer_id,
            amount_toman=Decimal(payment.amount_toman),
            txn_type="gateway_topup",
            idempotency_key=f"gateway-payment:{payment.id}",
            reference_type="payment",
            reference_id=str(payment.id),
            description="Customer gateway wallet top-up",
        )

    await db.flush()
    return payment, client
