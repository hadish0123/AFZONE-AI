import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    BillingEvent,
    Client,
    Plan,
    UsageCheckpoint,
    Wallet,
    WalletTxnType,
)
from app.services.wallet import apply_wallet_transaction

settings = get_settings()


class BillingAnomaly(RuntimeError):
    pass


def calculate_usage_cost_toman(
    delta_bytes: int,
    price_per_gib_toman: Decimal,
) -> Decimal:
    if delta_bytes < 0:
        raise ValueError("usage delta cannot be negative")
    price = Decimal(price_per_gib_toman)
    if price <= 0:
        raise ValueError("usage price must be positive")
    return (Decimal(delta_bytes) / Decimal(settings.billing_gib_bytes)) * price


async def bill_lifetime_usage(
    db: AsyncSession,
    *,
    client_id: uuid.UUID,
    current_lifetime_usage_bytes: int,
) -> BillingEvent | None:
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if not client:
        raise ValueError("client not found")

    checkpoint = await db.scalar(
        select(UsageCheckpoint)
        .where(UsageCheckpoint.client_id == client.id)
        .with_for_update()
    )
    if checkpoint is None:
        checkpoint = UsageCheckpoint(
            client_id=client.id,
            last_lifetime_usage_bytes=current_lifetime_usage_bytes,
        )
        db.add(checkpoint)
        client.last_lifetime_usage_bytes = current_lifetime_usage_bytes
        await db.flush()
        return None

    previous = checkpoint.last_lifetime_usage_bytes
    if current_lifetime_usage_bytes < previous:
        checkpoint.billing_suspended = True
        checkpoint.anomaly_reason = (
            f"lifetime usage regressed from {previous} to {current_lifetime_usage_bytes}"
        )
        raise BillingAnomaly(checkpoint.anomaly_reason)

    delta = current_lifetime_usage_bytes - previous
    if delta == 0:
        return None

    plan = await db.scalar(select(Plan).where(Plan.id == client.plan_id))
    if not plan:
        raise ValueError("client has no billable plan")

    wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == client.admin_id))
    if not wallet:
        raise ValueError("admin wallet not found")

    price = Decimal(plan.base_price_per_gib_toman)
    amount = calculate_usage_cost_toman(delta, price)
    wallet_debit = -amount
    idempotency_key = f"usage:{client.id}:{previous}:{current_lifetime_usage_bytes}"

    txn = await apply_wallet_transaction(
        db,
        wallet_id=wallet.id,
        txn_type=WalletTxnType.USAGE_CHARGE,
        amount_toman=wallet_debit,
        idempotency_key=idempotency_key,
        reference_type="client",
        reference_id=str(client.id),
        description=f"Usage charge for {delta} bytes",
        meta={
            "delta_bytes": delta,
            "price_per_gib_toman": str(price),
            "lifetime_before": previous,
            "lifetime_after": current_lifetime_usage_bytes,
        },
    )

    event = BillingEvent(
        client_id=client.id,
        admin_id=client.admin_id,
        delta_bytes=delta,
        price_per_gib_toman=price,
        amount_toman=amount,
        lifetime_before_bytes=previous,
        lifetime_after_bytes=current_lifetime_usage_bytes,
        wallet_transaction_id=txn.id,
        idempotency_key=idempotency_key,
    )
    db.add(event)

    from datetime import datetime, timezone
    checkpoint.last_lifetime_usage_bytes = current_lifetime_usage_bytes
    checkpoint.last_billed_at = datetime.now(timezone.utc)
    checkpoint.billing_suspended = False
    checkpoint.anomaly_reason = None
    client.last_lifetime_usage_bytes = current_lifetime_usage_bytes
    await db.flush()
    return event
