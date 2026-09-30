import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Wallet, WalletTransaction, WalletTxnType


class InsufficientFundsError(RuntimeError):
    pass


def normalize_wallet_delta(
    txn_type: WalletTxnType,
    amount_toman: Decimal,
) -> Decimal:
    amount = Decimal(amount_toman)
    if txn_type == WalletTxnType.USAGE_CHARGE and amount > 0:
        raise ValueError("usage_charge must debit the wallet")
    return amount


async def apply_wallet_transaction(
    db: AsyncSession,
    *,
    wallet_id: uuid.UUID,
    txn_type: WalletTxnType,
    amount_toman: Decimal,
    idempotency_key: str,
    actor_user_id: uuid.UUID | None = None,
    reference_type: str | None = None,
    reference_id: str | None = None,
    description: str | None = None,
    meta: dict | None = None,
) -> WalletTransaction:
    existing = await db.scalar(
        select(WalletTransaction).where(
            WalletTransaction.idempotency_key == idempotency_key
        )
    )
    if existing:
        return existing

    wallet = await db.scalar(
        select(Wallet).where(Wallet.id == wallet_id).with_for_update()
    )
    if not wallet:
        raise ValueError("wallet not found")

    amount = normalize_wallet_delta(txn_type, amount_toman)
    new_balance = Decimal(wallet.balance_toman) + amount
    if new_balance < -Decimal(wallet.debt_limit_toman):
        raise InsufficientFundsError("wallet debt limit exceeded")

    wallet.balance_toman = new_balance
    txn = WalletTransaction(
        wallet_id=wallet.id,
        txn_type=txn_type,
        amount_toman=amount,
        balance_after_toman=new_balance,
        idempotency_key=idempotency_key,
        actor_user_id=actor_user_id,
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
        meta=meta or {},
    )
    db.add(txn)
    await db.flush()
    return txn
