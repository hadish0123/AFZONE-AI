import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    encrypt_secret,
    hash_password,
    verify_password,
)
from app.db import SessionLocal, engine, get_db
from app.models import (
    AccountStatus,
    AdminPlan,
    Base,
    PasarGuardConnection,
    PasarGuardGroup,
    Plan,
    Role,
    User,
    Wallet,
    WalletTxnType,
)
from app.services.pasarguard import PasarGuardClient, PasarGuardError
from app.services.wallet import apply_wallet_transaction

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/login")


class LoginIn(BaseModel):
    username: str
    password: str


class AdminCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(default=None, max_length=160)
    initial_balance_toman: Decimal = Field(default=Decimal("0"), ge=0)


class ConnectionCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    base_url: HttpUrl
    api_token: str = Field(min_length=8)


class PlanCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    group_id: uuid.UUID
    base_price_per_gib_toman: Decimal = Field(gt=0)
    min_quota_gib: Decimal | None = Field(default=None, ge=0)
    max_quota_gib: Decimal | None = Field(default=None, gt=0)
    max_duration_days: int | None = Field(default=None, ge=1)
    default_hwid_limit: int | None = Field(default=None, ge=1)


class AssignPlanIn(BaseModel):
    retail_price_per_gib_toman: Decimal = Field(gt=0)
    bot_visible: bool = True


class WalletTopupIn(BaseModel):
    amount_toman: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=500)


async def ensure_owner() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        owner = await db.scalar(select(User).where(User.role == Role.OWNER))
        if owner is None:
            owner = User(
                username=settings.owner_username,
                password_hash=hash_password(settings.owner_password),
                role=Role.OWNER,
                status=AccountStatus.ACTIVE,
                display_name="PRIMEVPN Owner",
            )
            db.add(owner)
            await db.flush()
            db.add(Wallet(owner_user_id=owner.id))
            await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_owner()
    yield


app = FastAPI(
    title="PRIMEVPN API",
    version="0.1.0",
    lifespan=lifespan,
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


async def current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc

    user = await db.scalar(select(User).where(User.id == user_id))
    if not user or user.status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="account unavailable")
    return user


def require_owner(user: User = Depends(current_user)) -> User:
    if user.role != Role.OWNER:
        raise HTTPException(status_code=403, detail="owner access required")
    return user


@app.get("/health")
async def health():
    return {"ok": True, "service": "primevpn-api", "version": "0.1.0"}


@app.post(f"{settings.api_prefix}/auth/login")
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    if user.status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="account disabled")
    return {
        "access_token": create_access_token(user.id, user.role.value),
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role.value,
        },
    }


@app.get(f"{settings.api_prefix}/me")
async def me(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == user.id))
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.value,
        "wallet_balance_toman": str(wallet.balance_toman if wallet else 0),
    }


@app.get(f"{settings.api_prefix}/admins")
async def list_admins(
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(User).where(User.role == Role.ADMIN).order_by(User.created_at.desc()))).scalars()
    result = []
    for admin in rows:
        wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == admin.id))
        result.append({
            "id": str(admin.id),
            "username": admin.username,
            "display_name": admin.display_name,
            "status": admin.status.value,
            "wallet_balance_toman": str(wallet.balance_toman if wallet else 0),
        })
    return result


@app.post(f"{settings.api_prefix}/admins", status_code=201)
async def create_admin(
    payload: AdminCreateIn,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    if await db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status_code=409, detail="username already exists")

    admin = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=Role.ADMIN,
        display_name=payload.display_name,
    )
    db.add(admin)
    await db.flush()
    wallet = Wallet(owner_user_id=admin.id)
    db.add(wallet)
    await db.flush()

    if payload.initial_balance_toman > 0:
        await apply_wallet_transaction(
            db,
            wallet_id=wallet.id,
            txn_type=WalletTxnType.OWNER_TOPUP,
            amount_toman=payload.initial_balance_toman,
            idempotency_key=f"initial:{admin.id}",
            actor_user_id=owner.id,
            reference_type="admin",
            reference_id=str(admin.id),
            description="Initial wallet credit",
        )
    await db.commit()
    return {"id": str(admin.id), "username": admin.username}


@app.post(f"{settings.api_prefix}/admins/{{admin_id}}/wallet/topup")
async def topup_admin_wallet(
    admin_id: uuid.UUID,
    payload: WalletTopupIn,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    admin = await db.scalar(select(User).where(User.id == admin_id, User.role == Role.ADMIN))
    if not admin:
        raise HTTPException(status_code=404, detail="admin not found")
    wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == admin.id))
    txn = await apply_wallet_transaction(
        db,
        wallet_id=wallet.id,
        txn_type=WalletTxnType.OWNER_TOPUP,
        amount_toman=payload.amount_toman,
        idempotency_key=f"manual:{uuid.uuid4()}",
        actor_user_id=owner.id,
        reference_type="admin",
        reference_id=str(admin.id),
        description=payload.note or "Owner manual top-up",
    )
    await db.commit()
    return {"balance_toman": str(txn.balance_after_toman), "transaction_id": str(txn.id)}


@app.get(f"{settings.api_prefix}/connections")
async def list_connections(
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(PasarGuardConnection).order_by(PasarGuardConnection.created_at.desc()))).scalars()
    return [{
        "id": str(item.id),
        "name": item.name,
        "base_url": item.base_url,
        "enabled": item.enabled,
        "last_sync_at": item.last_sync_at,
        "last_error": item.last_error,
    } for item in rows]


@app.post(f"{settings.api_prefix}/connections", status_code=201)
async def create_connection(
    payload: ConnectionCreateIn,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    connection = PasarGuardConnection(
        name=payload.name,
        base_url=str(payload.base_url).rstrip("/"),
        encrypted_api_token=encrypt_secret(payload.api_token),
        created_by=owner.id,
    )
    pg = PasarGuardClient(connection.base_url, connection.encrypted_api_token)
    try:
        await pg.health()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="PasarGuard authentication/connection failed") from exc

    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    return {"id": str(connection.id), "name": connection.name, "connected": True}


@app.post(f"{settings.api_prefix}/connections/{{connection_id}}/sync-groups")
async def sync_groups(
    connection_id: uuid.UUID,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    connection = await db.scalar(select(PasarGuardConnection).where(PasarGuardConnection.id == connection_id))
    if not connection:
        raise HTTPException(status_code=404, detail="connection not found")

    pg = PasarGuardClient(connection.base_url, connection.encrypted_api_token)
    try:
        payload = await pg.list_groups()
    except PasarGuardError as exc:
        connection.last_error = str(exc)
        await db.commit()
        raise HTTPException(status_code=502, detail="PasarGuard group sync failed") from exc

    groups = payload.get("groups", payload if isinstance(payload, list) else [])
    synced = 0
    for remote in groups:
        remote_id = int(remote["id"])
        local = await db.scalar(
            select(PasarGuardGroup).where(
                PasarGuardGroup.connection_id == connection.id,
                PasarGuardGroup.remote_group_id == remote_id,
            )
        )
        if local is None:
            local = PasarGuardGroup(
                connection_id=connection.id,
                remote_group_id=remote_id,
                name=remote.get("name", f"Group {remote_id}"),
            )
            db.add(local)
        local.name = remote.get("name", local.name)
        local.enabled_remote = not bool(remote.get("is_disabled", False))
        local.inbound_tags = remote.get("inbound_tags", [])
        local.remote_payload = remote
        synced += 1

    from datetime import datetime, timezone
    connection.last_sync_at = datetime.now(timezone.utc)
    connection.last_error = None
    await db.commit()
    return {"synced": synced}


@app.get(f"{settings.api_prefix}/groups")
async def list_groups(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PasarGuardGroup).order_by(PasarGuardGroup.name)
    groups = (await db.execute(stmt)).scalars()
    return [{
        "id": str(group.id),
        "connection_id": str(group.connection_id),
        "remote_group_id": group.remote_group_id,
        "name": group.name,
        "enabled": group.enabled_remote,
        "inbound_tags": group.inbound_tags,
    } for group in groups]


@app.get(f"{settings.api_prefix}/plans")
async def list_plans(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role == Role.OWNER:
        rows = (await db.execute(select(Plan).order_by(Plan.created_at.desc()))).scalars()
        return [{
            "id": str(plan.id),
            "name": plan.name,
            "group_id": str(plan.group_id),
            "base_price_per_gib_toman": str(plan.base_price_per_gib_toman),
            "enabled": plan.enabled,
        } for plan in rows]

    rows = (await db.execute(
        select(AdminPlan, Plan)
        .join(Plan, Plan.id == AdminPlan.plan_id)
        .where(AdminPlan.admin_id == user.id, AdminPlan.enabled.is_(True), Plan.enabled.is_(True))
    )).all()
    return [{
        "id": str(plan.id),
        "name": plan.name,
        "group_id": str(plan.group_id),
        "cost_per_gib_toman": str(plan.base_price_per_gib_toman),
        "retail_price_per_gib_toman": str(admin_plan.retail_price_per_gib_toman),
        "bot_visible": admin_plan.bot_visible,
    } for admin_plan, plan in rows]


@app.post(f"{settings.api_prefix}/plans", status_code=201)
async def create_plan(
    payload: PlanCreateIn,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    group = await db.scalar(select(PasarGuardGroup).where(PasarGuardGroup.id == payload.group_id))
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    plan = Plan(**payload.model_dump())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return {"id": str(plan.id), "name": plan.name}


@app.put(f"{settings.api_prefix}/admins/{{admin_id}}/plans/{{plan_id}}")
async def assign_plan(
    admin_id: uuid.UUID,
    plan_id: uuid.UUID,
    payload: AssignPlanIn,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    admin = await db.scalar(select(User).where(User.id == admin_id, User.role == Role.ADMIN))
    plan = await db.scalar(select(Plan).where(Plan.id == plan_id))
    if not admin or not plan:
        raise HTTPException(status_code=404, detail="admin or plan not found")
    if payload.retail_price_per_gib_toman < plan.base_price_per_gib_toman:
        raise HTTPException(status_code=400, detail="retail price cannot be below owner cost")

    item = await db.scalar(
        select(AdminPlan).where(AdminPlan.admin_id == admin.id, AdminPlan.plan_id == plan.id)
    )
    if not item:
        item = AdminPlan(admin_id=admin.id, plan_id=plan.id, retail_price_per_gib_toman=payload.retail_price_per_gib_toman)
        db.add(item)
    item.retail_price_per_gib_toman = payload.retail_price_per_gib_toman
    item.bot_visible = payload.bot_visible
    item.enabled = True
    await db.commit()
    return {"ok": True}
