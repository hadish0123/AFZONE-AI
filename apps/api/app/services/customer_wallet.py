import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, CustomerWalletTransaction


class CustomerInsufficientFundsError(RuntimeError):
    pass


async def apply_customer_wallet_transaction(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID,
    amount_toman: Decimal,
    txn_type: str,
    idempotency_key: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
    description: str | None = None,
    meta: dict | None = None,
) -> CustomerWalletTransaction:
    existing = await db.scalar(
        select(CustomerWalletTransaction).where(
            CustomerWalletTransaction.idempotency_key == idempotency_key
        )
    )
    if existing:
        return existing

    customer = await db.scalar(
        select(Customer).where(Customer.id == customer_id).with_for_update()
    )
    if not customer:
        raise ValueError("customer not found")

    new_balance = Decimal(customer.wallet_balance_toman) + Decimal(amount_toman)
    if new_balance < 0:
        raise CustomerInsufficientFundsError("customer wallet balance is insufficient")

    customer.wallet_balance_toman = new_balance
    txn = CustomerWalletTransaction(
        customer_id=customer.id,
        amount_toman=amount_toman,
        balance_after_toman=new_balance,
        txn_type=txn_type,
        idempotency_key=idempotency_key,
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
        meta=meta or {},
    )
    db.add(txn)
    await db.flush()
    return txn
