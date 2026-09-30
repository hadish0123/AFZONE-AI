import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Role(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"


class AccountStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class PaymentMethod(str, enum.Enum):
    CUSTOMER_WALLET = "customer_wallet"
    GATEWAY = "gateway"
    CARD_TO_CARD = "card_to_card"
    OWNER_MANUAL = "owner_manual"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    AWAITING_REVIEW = "awaiting_review"
    PAID = "paid"
    REJECTED = "rejected"
    FAILED = "failed"
    REFUNDED = "refunded"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    PROVISIONED = "provisioned"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ClientStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


class WalletTxnType(str, enum.Enum):
    OWNER_TOPUP = "owner_topup"
    GATEWAY_TOPUP = "gateway_topup"
    CARD_TOPUP = "card_topup"
    USAGE_CHARGE = "usage_charge"
    REFUND = "refund"
    BONUS = "bonus"
    ADJUSTMENT = "adjustment"
    CUSTOMER_PAYMENT = "customer_payment"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"), index=True)
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, name="account_status"), default=AccountStatus.ACTIVE, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(160))
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    balance_toman: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"))
    debt_limit_toman: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"))
    low_balance_threshold_toman: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("50000")
    )
    block_new_clients_when_low: Mapped[bool] = mapped_column(Boolean, default=True)
    block_renewals_when_low: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id: Mapped[uuid.UUID] = uuid_pk()
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="CASCADE"), index=True
    )
    txn_type: Mapped[WalletTxnType] = mapped_column(Enum(WalletTxnType, name="wallet_txn_type"))
    amount_toman: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    balance_after_toman: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    reference_type: Mapped[str | None] = mapped_column(String(80))
    reference_id: Mapped[str | None] = mapped_column(String(160), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    description: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasarGuardConnection(Base):
    __tablename__ = "pasarguard_connections"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[str] = mapped_column(String(500), unique=True)
    encrypted_api_token: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasarGuardGroup(Base):
    __tablename__ = "pasarguard_groups"
    __table_args__ = (
        UniqueConstraint("connection_id", "remote_group_id", name="uq_pg_connection_group"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pasarguard_connections.id", ondelete="CASCADE"), index=True
    )
    remote_group_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    enabled_remote: Mapped[bool] = mapped_column(Boolean, default=True)
    inbound_tags: Mapped[list] = mapped_column(JSONB, default=list)
    remote_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(160), index=True)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pasarguard_groups.id"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    base_price_per_gib_toman: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    min_quota_gib: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    max_quota_gib: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    max_duration_days: Mapped[int | None] = mapped_column(Integer)
    default_hwid_limit: Mapped[int | None] = mapped_column(Integer)
    allow_custom_quota: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_custom_duration: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdminPlan(Base):
    __tablename__ = "admin_plans"
    __table_args__ = (UniqueConstraint("admin_id", "plan_id", name="uq_admin_plan"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    retail_price_per_gib_toman: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    bot_visible: Mapped[bool] = mapped_column(Boolean, default=True)


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("connection_id", "remote_user_id", name="uq_connection_remote_user"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pasarguard_connections.id"), index=True
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id"))
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pasarguard_groups.id"))
    remote_user_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(160), index=True)
    quota_bytes: Mapped[int | None] = mapped_column(BigInteger)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hwid_limit: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[ClientStatus] = mapped_column(
        Enum(ClientStatus, name="client_status"), default=ClientStatus.ACTIVE
    )
    subscription_url: Mapped[str | None] = mapped_column(Text)
    last_lifetime_usage_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    remote_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageCheckpoint(Base):
    __tablename__ = "usage_checkpoints"

    id: Mapped[uuid.UUID] = uuid_pk()
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), unique=True
    )
    last_lifetime_usage_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    last_billed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    billing_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    anomaly_reason: Mapped[str | None] = mapped_column(Text)


class BillingEvent(Base):
    __tablename__ = "billing_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), index=True)
    admin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    delta_bytes: Mapped[int] = mapped_column(BigInteger)
    price_per_gib_toman: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    amount_toman: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    lifetime_before_bytes: Mapped[int] = mapped_column(BigInteger)
    lifetime_after_bytes: Mapped[int] = mapped_column(BigInteger)
    wallet_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallet_transactions.id")
    )
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramBot(Base):
    __tablename__ = "telegram_bots"

    id: Mapped[uuid.UUID] = uuid_pk()
    admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    encrypted_token: Mapped[str] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    card_number: Mapped[str | None] = mapped_column(String(40))
    card_holder_name: Mapped[str | None] = mapped_column(String(160))
    gateway_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    customer_wallet_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    card_to_card_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("admin_id", "telegram_user_id", name="uq_admin_tg_customer"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    admin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(160))
    display_name: Mapped[str | None] = mapped_column(String(200))
    wallet_balance_toman: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = uuid_pk()
    admin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"))
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id"))
    quota_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    retail_amount_toman: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    payment_method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod, name="payment_method"))
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"), default=OrderStatus.PENDING
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = uuid_pk()
    admin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"))
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"))
    method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod, name="payment_method_2"))
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), default=PaymentStatus.PENDING
    )
    amount_toman: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    provider: Mapped[str | None] = mapped_column(String(80))
    provider_reference: Mapped[str | None] = mapped_column(String(200), index=True)
    receipt_file_key: Mapped[str | None] = mapped_column(Text)
    receipt_note: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(160), index=True)
    entity_type: Mapped[str] = mapped_column(String(120), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(160), index=True)
    before_data: Mapped[dict | None] = mapped_column(JSONB)
    after_data: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(80))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
