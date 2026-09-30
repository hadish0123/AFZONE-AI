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
    decrypt_secret,
    encrypt_secret,
    generate_recovery_codes,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    new_totp_secret,
    recovery_code_hash,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.db import SessionLocal, engine, get_db
from app.models import (
    AccountStatus,
    AdminPlan,
    Base,
    PasarGuardConnection,
    PasarGuardGroup,
    Plan,
    Order,
    OrderStatus,
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
    otp: str | None = Field(default=None, max_length=32)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20)


class TwoFactorCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class AdminCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(default=None, max_length=160)
    telegram_id: int | None = None
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
        else:
            # Railway OWNER_USERNAME / OWNER_PASSWORD are the bootstrap recovery
            # source for the single Owner account. This lets the human owner
            # rotate the bootstrap credential without ever sharing it in chat.
            if owner.username != settings.owner_username:
                owner.username = settings.owner_username
            if not verify_password(owner.password_hash, settings.owner_password):
                owner.password_hash = hash_password(settings.owner_password)
            owner.status = AccountStatus.ACTIVE
            wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == owner.id))
            if wallet is None:
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
async def login(payload: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timedelta, timezone
    from redis.asyncio import Redis
    from app.models import AuthSession, UserSecurity

    # Soft dependency: Redis protects login from brute force; a Redis outage
    # must not permanently lock the Owner out of the control plane.
    rate_key = f"primevpn:login:{request.client.host if request.client else 'unknown'}:{payload.username.lower()}"
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        attempts = await redis.incr(rate_key)
        if attempts == 1:
            await redis.expire(rate_key, 300)
        if attempts > 10:
            raise HTTPException(status_code=429, detail="too many login attempts; try again shortly")
    except HTTPException:
        raise
    except Exception:
        pass
    finally:
        try:
            await redis.aclose()
        except Exception:
            pass

    user = await db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    if user.status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="account disabled")

    security = await db.scalar(select(UserSecurity).where(UserSecurity.user_id == user.id))
    if security and security.totp_enabled:
        if not payload.otp:
            raise HTTPException(status_code=428, detail="otp_required")

        accepted = False
        if security.encrypted_totp_secret:
            accepted = verify_totp(decrypt_secret(security.encrypted_totp_secret), payload.otp)

        if not accepted:
            candidate = recovery_code_hash(payload.otp)
            if candidate in (security.recovery_code_hashes or []):
                security.recovery_code_hashes = [
                    item for item in security.recovery_code_hashes if item != candidate
                ]
                accepted = True

        if not accepted:
            raise HTTPException(status_code=401, detail="invalid_otp")

    refresh_raw, refresh_hash = new_refresh_token()
    session = AuthSession(
        user_id=user.id,
        refresh_token_hash=refresh_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(session)
    await db.commit()

    return {
        "access_token": create_access_token(user.id, user.role.value),
        "refresh_token": refresh_raw,
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
        "user": {
            "id": str(user.id),
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role.value,
            "two_factor_enabled": bool(security and security.totp_enabled),
        },
    }


@app.post(f"{settings.api_prefix}/auth/refresh")
async def refresh_access_token(payload: RefreshIn, request: Request, db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timezone
    from app.models import AuthSession

    session = await db.scalar(
        select(AuthSession).where(
            AuthSession.refresh_token_hash == hash_refresh_token(payload.refresh_token)
        ).with_for_update()
    )
    now = datetime.now(timezone.utc)
    if not session or session.revoked_at is not None or session.expires_at <= now:
        raise HTTPException(status_code=401, detail="refresh session expired")

    user = await db.scalar(select(User).where(User.id == session.user_id))
    if not user or user.status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="account unavailable")

    # Rotate refresh tokens on every use.
    raw, hashed = new_refresh_token()
    session.refresh_token_hash = hashed
    session.ip_address = request.client.host if request.client else session.ip_address
    session.user_agent = request.headers.get("user-agent") or session.user_agent
    await db.commit()
    return {
        "access_token": create_access_token(user.id, user.role.value),
        "refresh_token": raw,
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
    }


@app.post(f"{settings.api_prefix}/auth/logout", status_code=204)
async def logout_session(payload: RefreshIn, db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timezone
    from app.models import AuthSession

    session = await db.scalar(
        select(AuthSession).where(
            AuthSession.refresh_token_hash == hash_refresh_token(payload.refresh_token)
        )
    )
    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        await db.commit()
    return None


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
            "telegram_id": admin.telegram_id,
            "status": admin.status.value,
            "wallet_balance_toman": str(wallet.balance_toman if wallet else 0),
            "low_balance_threshold_toman": str(wallet.low_balance_threshold_toman if wallet else 0),
            "debt_limit_toman": str(wallet.debt_limit_toman if wallet else 0),
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
        telegram_id=payload.telegram_id,
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
    if user.role == Role.OWNER:
        stmt = select(PasarGuardGroup).order_by(PasarGuardGroup.name)
    else:
        stmt = (
            select(PasarGuardGroup)
            .join(Plan, Plan.group_id == PasarGuardGroup.id)
            .join(AdminPlan, AdminPlan.plan_id == Plan.id)
            .where(
                AdminPlan.admin_id == user.id,
                AdminPlan.enabled.is_(True),
                Plan.enabled.is_(True),
            )
            .distinct()
            .order_by(PasarGuardGroup.name)
        )
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
            "min_quota_gib": str(plan.min_quota_gib) if plan.min_quota_gib is not None else None,
            "max_quota_gib": str(plan.max_quota_gib) if plan.max_quota_gib is not None else None,
            "max_duration_days": plan.max_duration_days,
            "default_hwid_limit": plan.default_hwid_limit,
            "allow_custom_quota": plan.allow_custom_quota,
            "allow_custom_duration": plan.allow_custom_duration,
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


@app.get(f"{settings.api_prefix}/admins/{{admin_id}}/plans")
async def list_admin_assignments(
    admin_id: uuid.UUID,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    admin = await db.scalar(select(User).where(User.id == admin_id, User.role == Role.ADMIN))
    if not admin:
        raise HTTPException(status_code=404, detail="admin not found")
    rows = (
        await db.execute(
            select(AdminPlan, Plan)
            .join(Plan, Plan.id == AdminPlan.plan_id)
            .where(AdminPlan.admin_id == admin_id)
            .order_by(Plan.name)
        )
    ).all()
    return [{
        "assignment_id": str(item.id),
        "plan_id": str(plan.id),
        "name": plan.name,
        "enabled": item.enabled,
        "bot_visible": item.bot_visible,
        "base_price_per_gib_toman": str(plan.base_price_per_gib_toman),
        "retail_price_per_gib_toman": str(item.retail_price_per_gib_toman),
    } for item, plan in rows]


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


# ---- Client provisioning ----------------------------------------------------

from datetime import datetime, timedelta, timezone

from app.models import Client, ClientStatus, UsageCheckpoint


class ClientCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    plan_id: uuid.UUID
    quota_gib: Decimal = Field(gt=0)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    hwid_limit: int | None = Field(default=None, ge=1, le=100)
    note: str | None = Field(default=None, max_length=500)
    admin_id: uuid.UUID | None = None


class ClientUpdateIn(BaseModel):
    quota_gib: Decimal | None = Field(default=None, gt=0)
    duration_days_from_now: int | None = Field(default=None, ge=1, le=3650)
    hwid_limit: int | None = Field(default=None, ge=1, le=100)
    disabled: bool | None = None
    note: str | None = Field(default=None, max_length=500)


async def _resolve_client_admin(
    user: User,
    requested_admin_id: uuid.UUID | None,
    db: AsyncSession,
) -> User:
    if user.role == Role.ADMIN:
        if requested_admin_id and requested_admin_id != user.id:
            raise HTTPException(status_code=403, detail="cannot create clients for another admin")
        return user
    if not requested_admin_id:
        raise HTTPException(status_code=400, detail="admin_id is required for owner-created clients")
    admin = await db.scalar(
        select(User).where(User.id == requested_admin_id, User.role == Role.ADMIN)
    )
    if not admin:
        raise HTTPException(status_code=404, detail="admin not found")
    return admin


@app.get(f"{settings.api_prefix}/clients")
async def list_clients(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Client).order_by(Client.created_at.desc())
    if user.role == Role.ADMIN:
        stmt = stmt.where(Client.admin_id == user.id)
    rows = (await db.execute(stmt)).scalars()
    return [{
        "id": str(item.id),
        "admin_id": str(item.admin_id),
        "username": item.username,
        "status": item.status.value,
        "quota_bytes": item.quota_bytes,
        "expires_at": item.expires_at,
        "hwid_limit": item.hwid_limit,
        "lifetime_usage_bytes": item.last_lifetime_usage_bytes,
        "subscription_url": item.subscription_url,
        "plan_id": str(item.plan_id) if item.plan_id else None,
        "group_id": str(item.group_id),
    } for item in rows]


@app.post(f"{settings.api_prefix}/clients", status_code=201)
async def create_client(
    payload: ClientCreateIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    admin = await _resolve_client_admin(user, payload.admin_id, db)
    plan = await db.scalar(select(Plan).where(Plan.id == payload.plan_id, Plan.enabled.is_(True)))
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found")

    allowed = await db.scalar(
        select(AdminPlan).where(
            AdminPlan.admin_id == admin.id,
            AdminPlan.plan_id == plan.id,
            AdminPlan.enabled.is_(True),
        )
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="plan is not assigned to this admin")

    if plan.min_quota_gib is not None and payload.quota_gib < plan.min_quota_gib:
        raise HTTPException(status_code=400, detail="quota below plan minimum")
    if plan.max_quota_gib is not None and payload.quota_gib > plan.max_quota_gib:
        raise HTTPException(status_code=400, detail="quota above plan maximum")
    if plan.max_duration_days is not None and payload.duration_days and payload.duration_days > plan.max_duration_days:
        raise HTTPException(status_code=400, detail="duration above plan maximum")

    wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == admin.id))
    if not wallet:
        raise HTTPException(status_code=409, detail="admin wallet missing")
    if wallet.block_new_clients_when_low and wallet.balance_toman <= wallet.low_balance_threshold_toman:
        raise HTTPException(status_code=402, detail="admin wallet is below the client-creation threshold")

    group = await db.scalar(select(PasarGuardGroup).where(PasarGuardGroup.id == plan.group_id))
    if not group or not group.enabled_remote:
        raise HTTPException(status_code=409, detail="PasarGuard group unavailable")
    connection = await db.scalar(
        select(PasarGuardConnection).where(
            PasarGuardConnection.id == group.connection_id,
            PasarGuardConnection.enabled.is_(True),
        )
    )
    if not connection:
        raise HTTPException(status_code=409, detail="PasarGuard connection unavailable")

    if await db.scalar(
        select(Client).where(
            Client.connection_id == connection.id,
            Client.username == payload.username,
        )
    ):
        raise HTTPException(status_code=409, detail="client username already exists locally")

    quota_bytes = int(payload.quota_gib * Decimal(1024**3))
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=payload.duration_days)
        if payload.duration_days
        else None
    )
    remote_payload = {
        "username": payload.username,
        "status": "active",
        "expire": expires_at.isoformat() if expires_at else 0,
        "data_limit": quota_bytes,
        "data_limit_reset_strategy": "no_reset",
        "group_ids": [group.remote_group_id],
        "note": payload.note,
        "hwid_limit": payload.hwid_limit or plan.default_hwid_limit,
    }
    remote_payload = {k: v for k, v in remote_payload.items() if v is not None}

    pg = PasarGuardClient(connection.base_url, connection.encrypted_api_token)
    try:
        remote = await pg.create_user(remote_payload)
    except PasarGuardError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    client = Client(
        admin_id=admin.id,
        connection_id=connection.id,
        plan_id=plan.id,
        group_id=group.id,
        remote_user_id=int(remote["id"]),
        username=remote["username"],
        quota_bytes=remote.get("data_limit", quota_bytes),
        expires_at=expires_at,
        hwid_limit=remote.get("hwid_limit", remote_payload.get("hwid_limit")),
        status=ClientStatus.ACTIVE,
        subscription_url=remote.get("subscription_url"),
        last_lifetime_usage_bytes=int(remote.get("lifetime_used_traffic") or 0),
        remote_payload=remote,
    )
    db.add(client)
    await db.flush()
    db.add(
        UsageCheckpoint(
            client_id=client.id,
            last_lifetime_usage_bytes=client.last_lifetime_usage_bytes,
        )
    )
    await db.commit()
    await db.refresh(client)
    return {
        "id": str(client.id),
        "username": client.username,
        "subscription_url": client.subscription_url,
        "quota_bytes": client.quota_bytes,
        "expires_at": client.expires_at,
    }


@app.patch(f"{settings.api_prefix}/clients/{{client_id}}")
async def update_client(
    client_id: uuid.UUID,
    payload: ClientUpdateIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if not client:
        raise HTTPException(status_code=404, detail="client not found")
    if user.role == Role.ADMIN and client.admin_id != user.id:
        raise HTTPException(status_code=403, detail="client belongs to another admin")

    connection = await db.scalar(
        select(PasarGuardConnection).where(PasarGuardConnection.id == client.connection_id)
    )
    if not connection or not connection.enabled:
        raise HTTPException(status_code=409, detail="PasarGuard connection unavailable")

    plan = await db.scalar(select(Plan).where(Plan.id == client.plan_id)) if client.plan_id else None
    if user.role == Role.ADMIN:
        if not plan:
            raise HTTPException(status_code=409, detail="client is not attached to a managed plan")
        assignment = await db.scalar(
            select(AdminPlan).where(
                AdminPlan.admin_id == user.id,
                AdminPlan.plan_id == plan.id,
                AdminPlan.enabled.is_(True),
            )
        )
        if not assignment:
            raise HTTPException(status_code=403, detail="plan is no longer assigned to this admin")
        if payload.quota_gib is not None or payload.duration_days_from_now is not None:
            wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == user.id))
            if wallet and wallet.block_renewals_when_low and wallet.balance_toman <= wallet.low_balance_threshold_toman:
                raise HTTPException(status_code=402, detail="admin wallet is below the renewal threshold")

    pg = PasarGuardClient(connection.base_url, connection.encrypted_api_token)

    remote_update = {}
    if payload.quota_gib is not None:
        if plan:
            if plan.min_quota_gib is not None and payload.quota_gib < plan.min_quota_gib:
                raise HTTPException(status_code=400, detail="quota below plan minimum")
            if plan.max_quota_gib is not None and payload.quota_gib > plan.max_quota_gib:
                raise HTTPException(status_code=400, detail="quota above plan maximum")
        client.quota_bytes = int(payload.quota_gib * Decimal(1024**3))
        remote_update["data_limit"] = client.quota_bytes
    if payload.duration_days_from_now is not None:
        if plan and plan.max_duration_days is not None and payload.duration_days_from_now > plan.max_duration_days:
            raise HTTPException(status_code=400, detail="duration above plan maximum")
        client.expires_at = datetime.now(timezone.utc) + timedelta(days=payload.duration_days_from_now)
        remote_update["expire"] = client.expires_at.isoformat()
    if payload.hwid_limit is not None:
        client.hwid_limit = payload.hwid_limit
        remote_update["hwid_limit"] = payload.hwid_limit
    if payload.note is not None:
        remote_update["note"] = payload.note

    try:
        if remote_update:
            remote = await pg.update_user(client.username, remote_update)
            client.remote_payload = remote or client.remote_payload
        if payload.disabled is not None:
            remote = await pg.set_user_disabled(client.username, payload.disabled)
            client.status = ClientStatus.DISABLED if payload.disabled else ClientStatus.ACTIVE
            client.remote_payload = remote or client.remote_payload
    except PasarGuardError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await db.commit()
    return {"ok": True}


@app.post(f"{settings.api_prefix}/clients/{{client_id}}/reset-usage")
async def reset_client_usage(
    client_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if not client:
        raise HTTPException(status_code=404, detail="client not found")
    if user.role == Role.ADMIN and client.admin_id != user.id:
        raise HTTPException(status_code=403, detail="client belongs to another admin")
    connection = await db.scalar(select(PasarGuardConnection).where(PasarGuardConnection.id == client.connection_id))
    pg = PasarGuardClient(connection.base_url, connection.encrypted_api_token)
    try:
        remote = await pg.reset_user_usage(client.username)
    except PasarGuardError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    client.remote_payload = remote or client.remote_payload
    client.last_lifetime_usage_bytes = int((remote or {}).get("lifetime_used_traffic") or client.last_lifetime_usage_bytes)
    await db.commit()
    return {"ok": True, "lifetime_usage_bytes": client.last_lifetime_usage_bytes}


@app.post(f"{settings.api_prefix}/clients/{{client_id}}/revoke-subscription")
async def revoke_client_subscription(
    client_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if not client:
        raise HTTPException(status_code=404, detail="client not found")
    if user.role == Role.ADMIN and client.admin_id != user.id:
        raise HTTPException(status_code=403, detail="client belongs to another admin")
    connection = await db.scalar(select(PasarGuardConnection).where(PasarGuardConnection.id == client.connection_id))
    pg = PasarGuardClient(connection.base_url, connection.encrypted_api_token)
    try:
        remote = await pg.revoke_subscription(client.username)
    except PasarGuardError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    client.subscription_url = (remote or {}).get("subscription_url", client.subscription_url)
    client.remote_payload = remote or client.remote_payload
    await db.commit()
    return {"ok": True, "subscription_url": client.subscription_url}


@app.delete(f"{settings.api_prefix}/clients/{{client_id}}", status_code=204)
async def delete_client(
    client_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if not client:
        raise HTTPException(status_code=404, detail="client not found")
    if user.role == Role.ADMIN and client.admin_id != user.id:
        raise HTTPException(status_code=403, detail="client belongs to another admin")
    connection = await db.scalar(select(PasarGuardConnection).where(PasarGuardConnection.id == client.connection_id))
    pg = PasarGuardClient(connection.base_url, connection.encrypted_api_token)
    try:
        await pg.delete_user(client.username)
    except PasarGuardError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Keep PRIMEVPN billing/audit history. The remote user is gone, so mark the
    # local mirror disabled rather than deleting financial history.
    client.status = ClientStatus.DISABLED
    client.remote_payload = {**(client.remote_payload or {}), "deleted_remote": True}
    await db.commit()
    return None


# ---- Payments, cards and wallet top-ups ------------------------------------

import base64
import hashlib
import json

from fastapi import File, Form, Response, UploadFile

from app.core.security import decrypt_secret
from app.models import (
    Customer,
    Payment,
    PaymentMethod,
    PaymentProfile,
    PaymentReceipt,
    PaymentStatus,
)
from app.services.audit import write_audit
from app.services.customer_wallet import apply_customer_wallet_transaction


class PaymentProfileIn(BaseModel):
    card_number: str | None = Field(default=None, max_length=40)
    card_holder_name: str | None = Field(default=None, max_length=160)
    card_instructions: str | None = Field(default=None, max_length=1000)
    card_to_card_enabled: bool = True
    gateway_provider: str | None = Field(default=None, max_length=80)
    gateway_credentials: dict | None = None
    gateway_enabled: bool = False


class PaymentReviewIn(BaseModel):
    approved: bool
    note: str | None = Field(default=None, max_length=500)


async def _get_or_create_payment_profile(db: AsyncSession, user_id: uuid.UUID) -> PaymentProfile:
    profile = await db.scalar(
        select(PaymentProfile).where(PaymentProfile.owner_user_id == user_id)
    )
    if profile is None:
        profile = PaymentProfile(owner_user_id=user_id)
        db.add(profile)
        await db.flush()
    return profile


def _payment_profile_public(profile: PaymentProfile) -> dict:
    return {
        "card_number": profile.card_number,
        "card_holder_name": profile.card_holder_name,
        "card_instructions": profile.card_instructions,
        "card_to_card_enabled": profile.card_to_card_enabled,
        "gateway_provider": profile.gateway_provider,
        "gateway_enabled": profile.gateway_enabled,
        "gateway_configured": bool(profile.encrypted_gateway_credentials),
    }


@app.get(f"{settings.api_prefix}/payment-profile")
async def get_payment_profile(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_or_create_payment_profile(db, user.id)
    await db.commit()
    return _payment_profile_public(profile)


@app.put(f"{settings.api_prefix}/payment-profile")
async def update_payment_profile(
    payload: PaymentProfileIn,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_or_create_payment_profile(db, user.id)
    before = _payment_profile_public(profile)

    profile.card_number = payload.card_number
    profile.card_holder_name = payload.card_holder_name
    profile.card_instructions = payload.card_instructions
    profile.card_to_card_enabled = payload.card_to_card_enabled
    profile.gateway_provider = payload.gateway_provider
    profile.gateway_enabled = payload.gateway_enabled

    if payload.gateway_credentials is not None:
        profile.encrypted_gateway_credentials = encrypt_secret(
            json.dumps(payload.gateway_credentials, separators=(",", ":"))
        )

    if profile.gateway_enabled and (
        not profile.gateway_provider or not profile.encrypted_gateway_credentials
    ):
        raise HTTPException(
            status_code=400,
            detail="gateway provider and credentials are required before enabling gateway",
        )

    await write_audit(
        db,
        actor_user_id=user.id,
        action="payment_profile.update",
        entity_type="payment_profile",
        entity_id=str(profile.id),
        before_data=before,
        after_data=_payment_profile_public(profile),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return _payment_profile_public(profile)


@app.get(f"{settings.api_prefix}/wallet/topup-options")
async def admin_wallet_topup_options(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="admin access required")

    owner = await db.scalar(select(User).where(User.role == Role.OWNER))
    if owner is None:
        raise HTTPException(status_code=503, detail="owner account unavailable")

    profile = await _get_or_create_payment_profile(db, owner.id)
    from app.services.commerce import default_bank_card
    card = await default_bank_card(db, owner.id)
    await db.commit()
    return {
        "card_to_card": {
            "enabled": bool(card),
            "card_id": str(card.id) if card else None,
            "card_number": card.card_number if card else None,
            "card_holder_name": card.card_holder_name if card else None,
            "instructions": card.instructions if card else None,
        },
        "gateway": {
            "enabled": profile.gateway_enabled and bool(profile.gateway_provider),
            "provider": profile.gateway_provider if profile.gateway_enabled else None,
        },
    }


@app.post(f"{settings.api_prefix}/wallet/topups/card", status_code=201)
async def create_admin_card_topup(
    request: Request,
    amount_toman: Decimal = Form(..., gt=0),
    receipt: UploadFile = File(...),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="admin access required")

    owner = await db.scalar(select(User).where(User.role == Role.OWNER))
    if owner is None:
        raise HTTPException(status_code=503, detail="owner account unavailable")
    from app.services.commerce import default_bank_card
    card = await default_bank_card(db, owner.id)
    if not card:
        raise HTTPException(status_code=409, detail="owner card-to-card payment is disabled")

    allowed_types = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
    if receipt.content_type not in allowed_types:
        raise HTTPException(status_code=415, detail="receipt must be JPG, PNG, WEBP or PDF")

    raw = await receipt.read(5 * 1024 * 1024 + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="receipt file is empty")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="receipt file exceeds 5 MB")

    payment = Payment(
        admin_id=user.id,
        customer_id=None,
        order_id=None,
        method=PaymentMethod.CARD_TO_CARD,
        status=PaymentStatus.AWAITING_REVIEW,
        amount_toman=amount_toman,
        provider="card_to_card",
        meta={
            "purpose": "admin_wallet_topup",
            "destination_owner_id": str(owner.id),
        },
    )
    db.add(payment)
    await db.flush()

    db.add(
        PaymentReceipt(
            payment_id=payment.id,
            original_name=(receipt.filename or "")[:255] or None,
            mime_type=receipt.content_type or "application/octet-stream",
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            encrypted_data=encrypt_secret(base64.b64encode(raw).decode()),
        )
    )

    await write_audit(
        db,
        actor_user_id=user.id,
        action="wallet.card_topup.request",
        entity_type="payment",
        entity_id=str(payment.id),
        after_data={"amount_toman": str(amount_toman), "status": payment.status.value},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {
        "payment_id": str(payment.id),
        "status": payment.status.value,
        "amount_toman": str(payment.amount_toman),
        "message": "receipt submitted for owner review",
    }


@app.get(f"{settings.api_prefix}/payments")
async def list_payments(
    status_filter: PaymentStatus | None = None,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Payment).order_by(Payment.created_at.desc())
    if user.role == Role.ADMIN:
        stmt = stmt.where(Payment.admin_id == user.id)
    if status_filter is not None:
        stmt = stmt.where(Payment.status == status_filter)

    rows = (await db.execute(stmt)).scalars()
    return [{
        "id": str(item.id),
        "admin_id": str(item.admin_id),
        "customer_id": str(item.customer_id) if item.customer_id else None,
        "order_id": str(item.order_id) if item.order_id else None,
        "method": item.method.value,
        "status": item.status.value,
        "amount_toman": str(item.amount_toman),
        "provider": item.provider,
        "provider_reference": item.provider_reference,
        "purpose": (item.meta or {}).get("purpose"),
        "created_at": item.created_at,
        "reviewed_at": item.reviewed_at,
    } for item in rows]


@app.get(f"{settings.api_prefix}/payments/{{payment_id}}/receipt")
async def get_payment_receipt(
    payment_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    payment = await db.scalar(select(Payment).where(Payment.id == payment_id))
    if not payment:
        raise HTTPException(status_code=404, detail="payment not found")
    if user.role == Role.ADMIN and payment.admin_id != user.id:
        raise HTTPException(status_code=403, detail="payment belongs to another admin")

    receipt = await db.scalar(
        select(PaymentReceipt).where(PaymentReceipt.payment_id == payment.id)
    )
    if not receipt:
        raise HTTPException(status_code=404, detail="receipt not found")

    raw = base64.b64decode(decrypt_secret(receipt.encrypted_data))
    return Response(
        content=raw,
        media_type=receipt.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{receipt.original_name or "receipt"}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post(f"{settings.api_prefix}/payments/{{payment_id}}/review")
async def review_payment(
    payment_id: uuid.UUID,
    payload: PaymentReviewIn,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone

    payment = await db.scalar(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="payment not found")
    if payment.status != PaymentStatus.AWAITING_REVIEW:
        raise HTTPException(status_code=409, detail="payment is not awaiting review")

    purpose = (payment.meta or {}).get("purpose")

    if purpose == "admin_wallet_topup":
        if user.role != Role.OWNER:
            raise HTTPException(status_code=403, detail="owner review required")
        if payload.approved:
            wallet = await db.scalar(
                select(Wallet).where(Wallet.owner_user_id == payment.admin_id)
            )
            if not wallet:
                raise HTTPException(status_code=409, detail="admin wallet not found")
            txn = await apply_wallet_transaction(
                db,
                wallet_id=wallet.id,
                txn_type=WalletTxnType.CARD_TOPUP,
                amount_toman=payment.amount_toman,
                idempotency_key=f"payment:{payment.id}",
                actor_user_id=user.id,
                reference_type="payment",
                reference_id=str(payment.id),
                description=payload.note or "Approved card-to-card wallet top-up",
            )
            payment.status = PaymentStatus.PAID
            payment.provider_reference = str(txn.id)
        else:
            payment.status = PaymentStatus.REJECTED

    elif purpose == "customer_wallet_topup":
        if user.role == Role.ADMIN and payment.admin_id != user.id:
            raise HTTPException(status_code=403, detail="customer belongs to another admin")
        if user.role not in {Role.ADMIN, Role.OWNER}:
            raise HTTPException(status_code=403, detail="review access denied")
        if not payment.customer_id:
            raise HTTPException(status_code=409, detail="customer payment has no customer")
        if payload.approved:
            txn = await apply_customer_wallet_transaction(
                db,
                customer_id=payment.customer_id,
                amount_toman=payment.amount_toman,
                txn_type="card_topup",
                idempotency_key=f"payment:{payment.id}",
                reference_type="payment",
                reference_id=str(payment.id),
                description=payload.note or "Approved customer card-to-card top-up",
            )
            payment.status = PaymentStatus.PAID
            payment.provider_reference = str(txn.id)
        else:
            payment.status = PaymentStatus.REJECTED

    elif purpose == "order_card":
        from app.models import Order, OrderStatus
        from app.services.orders import provision_paid_order

        if user.role == Role.ADMIN and payment.admin_id != user.id:
            raise HTTPException(status_code=403, detail="order belongs to another admin")
        if user.role not in {Role.ADMIN, Role.OWNER}:
            raise HTTPException(status_code=403, detail="review access denied")
        if not payment.order_id:
            raise HTTPException(status_code=409, detail="payment has no order")

        order = await db.scalar(
            select(Order).where(Order.id == payment.order_id).with_for_update()
        )
        if not order:
            raise HTTPException(status_code=404, detail="order not found")

        if payload.approved:
            payment.status = PaymentStatus.PAID
            order.status = OrderStatus.PAID
            client = await provision_paid_order(db, order.id)
            payment.provider_reference = str(client.id)
        else:
            payment.status = PaymentStatus.REJECTED
            order.status = OrderStatus.CANCELLED

    else:
        raise HTTPException(status_code=400, detail="payment purpose cannot be manually reviewed")

    payment.reviewed_at = datetime.now(timezone.utc)
    payment.reviewed_by = user.id

    await write_audit(
        db,
        actor_user_id=user.id,
        action="payment.review",
        entity_type="payment",
        entity_id=str(payment.id),
        before_data={"status": PaymentStatus.AWAITING_REVIEW.value},
        after_data={
            "status": payment.status.value,
            "approved": payload.approved,
            "purpose": purpose,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {"id": str(payment.id), "status": payment.status.value}


# ---- Telegram bot management -----------------------------------------------

from aiogram import Bot as AiogramBot

from app.models import TelegramBot, TelegramBotPlan


class TelegramBotCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    token: str = Field(min_length=20, max_length=300)
    admin_id: uuid.UUID | None = None
    customer_wallet_enabled: bool = True
    card_to_card_enabled: bool = True
    gateway_enabled: bool = False


class TelegramBotUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    token: str | None = Field(default=None, min_length=20, max_length=300)
    enabled: bool | None = None
    customer_wallet_enabled: bool | None = None
    card_to_card_enabled: bool | None = None
    gateway_enabled: bool | None = None


async def _validate_telegram_token(token: str) -> dict:
    bot = AiogramBot(token=token)
    try:
        info = await bot.get_me()
        return {
            "id": info.id,
            "username": info.username,
            "first_name": info.first_name,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Telegram bot token is invalid or unreachable") from exc
    finally:
        await bot.session.close()


async def _resolve_bot_admin(
    user: User,
    requested_admin_id: uuid.UUID | None,
    db: AsyncSession,
) -> User:
    if user.role == Role.ADMIN:
        if requested_admin_id and requested_admin_id != user.id:
            raise HTTPException(status_code=403, detail="cannot create a bot for another admin")
        return user
    if not requested_admin_id:
        raise HTTPException(status_code=400, detail="admin_id is required")
    admin = await db.scalar(
        select(User).where(User.id == requested_admin_id, User.role == Role.ADMIN)
    )
    if not admin:
        raise HTTPException(status_code=404, detail="admin not found")
    return admin


@app.get(f"{settings.api_prefix}/bots")
async def list_telegram_bots(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TelegramBot).order_by(TelegramBot.created_at.desc())
    if user.role == Role.ADMIN:
        stmt = stmt.where(TelegramBot.admin_id == user.id)
    rows = (await db.execute(stmt)).scalars()
    return [{
        "id": str(item.id),
        "admin_id": str(item.admin_id),
        "name": item.name,
        "username": item.username,
        "enabled": item.enabled,
        "customer_wallet_enabled": item.customer_wallet_enabled,
        "card_to_card_enabled": item.card_to_card_enabled,
        "gateway_enabled": item.gateway_enabled,
        "created_at": item.created_at,
    } for item in rows]


@app.post(f"{settings.api_prefix}/bots", status_code=201)
async def create_telegram_bot(
    payload: TelegramBotCreateIn,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    admin = await _resolve_bot_admin(user, payload.admin_id, db)
    bot_info = await _validate_telegram_token(payload.token)

    existing = await db.scalar(
        select(TelegramBot).where(
            TelegramBot.admin_id == admin.id,
            TelegramBot.username == bot_info.get("username"),
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="this Telegram bot is already registered")

    row = TelegramBot(
        admin_id=admin.id,
        name=payload.name,
        encrypted_token=encrypt_secret(payload.token),
        username=bot_info.get("username"),
        enabled=True,
        customer_wallet_enabled=payload.customer_wallet_enabled,
        card_to_card_enabled=payload.card_to_card_enabled,
        gateway_enabled=payload.gateway_enabled,
    )
    db.add(row)
    await db.flush()

    assigned_plans = (
        await db.execute(
            select(AdminPlan).where(
                AdminPlan.admin_id == admin.id,
                AdminPlan.enabled.is_(True),
                AdminPlan.bot_visible.is_(True),
            )
        )
    ).scalars().all()
    for index, assignment in enumerate(assigned_plans):
        db.add(
            TelegramBotPlan(
                bot_id=row.id,
                plan_id=assignment.plan_id,
                enabled=True,
                sort_order=index,
            )
        )

    await write_audit(
        db,
        actor_user_id=user.id,
        action="telegram_bot.create",
        entity_type="telegram_bot",
        entity_id=str(row.id),
        after_data={
            "admin_id": str(admin.id),
            "name": row.name,
            "username": row.username,
            "enabled": row.enabled,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    await db.refresh(row)
    return {
        "id": str(row.id),
        "name": row.name,
        "username": row.username,
        "enabled": row.enabled,
    }


@app.patch(f"{settings.api_prefix}/bots/{{bot_id}}")
async def update_telegram_bot(
    bot_id: uuid.UUID,
    payload: TelegramBotUpdateIn,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(select(TelegramBot).where(TelegramBot.id == bot_id))
    if not row:
        raise HTTPException(status_code=404, detail="bot not found")
    if user.role == Role.ADMIN and row.admin_id != user.id:
        raise HTTPException(status_code=403, detail="bot belongs to another admin")

    before = {
        "name": row.name,
        "username": row.username,
        "enabled": row.enabled,
        "customer_wallet_enabled": row.customer_wallet_enabled,
        "card_to_card_enabled": row.card_to_card_enabled,
        "gateway_enabled": row.gateway_enabled,
    }

    if payload.token is not None:
        bot_info = await _validate_telegram_token(payload.token)
        row.encrypted_token = encrypt_secret(payload.token)
        row.username = bot_info.get("username")
    if payload.name is not None:
        row.name = payload.name
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.customer_wallet_enabled is not None:
        row.customer_wallet_enabled = payload.customer_wallet_enabled
    if payload.card_to_card_enabled is not None:
        row.card_to_card_enabled = payload.card_to_card_enabled
    if payload.gateway_enabled is not None:
        row.gateway_enabled = payload.gateway_enabled

    await write_audit(
        db,
        actor_user_id=user.id,
        action="telegram_bot.update",
        entity_type="telegram_bot",
        entity_id=str(row.id),
        before_data=before,
        after_data={
            "name": row.name,
            "username": row.username,
            "enabled": row.enabled,
            "customer_wallet_enabled": row.customer_wallet_enabled,
            "card_to_card_enabled": row.card_to_card_enabled,
            "gateway_enabled": row.gateway_enabled,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {"ok": True}


@app.delete(f"{settings.api_prefix}/bots/{{bot_id}}", status_code=204)
async def disable_telegram_bot(
    bot_id: uuid.UUID,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(select(TelegramBot).where(TelegramBot.id == bot_id))
    if not row:
        raise HTTPException(status_code=404, detail="bot not found")
    if user.role == Role.ADMIN and row.admin_id != user.id:
        raise HTTPException(status_code=403, detail="bot belongs to another admin")
    row.enabled = False
    await write_audit(
        db,
        actor_user_id=user.id,
        action="telegram_bot.disable",
        entity_type="telegram_bot",
        entity_id=str(row.id),
        after_data={"enabled": False},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return None


# ---- Production management completion --------------------------------------

from sqlalchemy import func

from app.models import (
    AuditLog,
    AuthSession,
    BillingEvent,
    Notification,
    UserSecurity,
    WalletTransaction,
)


class AdminUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    telegram_id: int | None = None
    status: AccountStatus | None = None
    password: str | None = Field(default=None, min_length=10, max_length=200)
    low_balance_threshold_toman: Decimal | None = Field(default=None, ge=0)
    debt_limit_toman: Decimal | None = Field(default=None, ge=0)
    block_new_clients_when_low: bool | None = None
    block_renewals_when_low: bool | None = None


class WalletAdjustmentIn(BaseModel):
    amount_toman: Decimal
    note: str = Field(min_length=3, max_length=500)


class ConnectionUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    base_url: HttpUrl | None = None
    api_token: str | None = Field(default=None, min_length=8)
    enabled: bool | None = None


class PlanUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    enabled: bool | None = None
    base_price_per_gib_toman: Decimal | None = Field(default=None, gt=0)
    min_quota_gib: Decimal | None = Field(default=None, ge=0)
    max_quota_gib: Decimal | None = Field(default=None, gt=0)
    max_duration_days: int | None = Field(default=None, ge=1, le=3650)
    default_hwid_limit: int | None = Field(default=None, ge=1, le=100)
    allow_custom_quota: bool | None = None
    allow_custom_duration: bool | None = None


class RetailPriceIn(BaseModel):
    retail_price_per_gib_toman: Decimal = Field(gt=0)


@app.get(f"{settings.api_prefix}/security/2fa/status")
async def two_factor_status(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    security = await db.scalar(select(UserSecurity).where(UserSecurity.user_id == user.id))
    return {
        "enabled": bool(security and security.totp_enabled),
        "recovery_codes_remaining": len(security.recovery_code_hashes or []) if security else 0,
    }


@app.post(f"{settings.api_prefix}/security/2fa/setup")
async def setup_two_factor(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    # V1 exposes TOTP only to Owner; Admin authentication remains password +
    # rotating refresh sessions unless Owner later chooses otherwise.
    if user.role != Role.OWNER:
        raise HTTPException(status_code=403, detail="2FA setup is owner-only")

    security = await db.scalar(select(UserSecurity).where(UserSecurity.user_id == user.id))
    if security is None:
        security = UserSecurity(user_id=user.id)
        db.add(security)
        await db.flush()

    secret = new_totp_secret()
    recovery_codes, recovery_hashes = generate_recovery_codes()
    security.encrypted_totp_secret = encrypt_secret(secret)
    security.totp_enabled = False
    security.recovery_code_hashes = recovery_hashes
    await db.commit()

    return {
        "secret": secret,
        "otpauth_uri": totp_uri(secret, username=user.username),
        "recovery_codes": recovery_codes,
        "message": "Scan the TOTP secret, then call /security/2fa/enable with a current code.",
    }


@app.post(f"{settings.api_prefix}/security/2fa/enable")
async def enable_two_factor(
    payload: TwoFactorCodeIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    security = await db.scalar(select(UserSecurity).where(UserSecurity.user_id == user.id))
    if not security or not security.encrypted_totp_secret:
        raise HTTPException(status_code=409, detail="run 2FA setup first")
    if not verify_totp(decrypt_secret(security.encrypted_totp_secret), payload.code):
        raise HTTPException(status_code=400, detail="invalid TOTP code")
    security.totp_enabled = True
    await db.commit()
    return {"enabled": True}


@app.post(f"{settings.api_prefix}/security/2fa/disable")
async def disable_two_factor(
    payload: TwoFactorCodeIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    security = await db.scalar(select(UserSecurity).where(UserSecurity.user_id == user.id))
    if not security or not security.totp_enabled or not security.encrypted_totp_secret:
        return {"enabled": False}
    secret = decrypt_secret(security.encrypted_totp_secret)
    if not verify_totp(secret, payload.code):
        raise HTTPException(status_code=400, detail="invalid TOTP code")
    security.totp_enabled = False
    security.encrypted_totp_secret = None
    security.recovery_code_hashes = []
    await db.commit()
    return {"enabled": False}


@app.patch(f"{settings.api_prefix}/admins/{{admin_id}}")
async def update_admin(
    admin_id: uuid.UUID,
    payload: AdminUpdateIn,
    request: Request,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    admin = await db.scalar(
        select(User).where(User.id == admin_id, User.role == Role.ADMIN).with_for_update()
    )
    if not admin:
        raise HTTPException(status_code=404, detail="admin not found")
    wallet = await db.scalar(
        select(Wallet).where(Wallet.owner_user_id == admin.id).with_for_update()
    )
    before = {
        "display_name": admin.display_name,
        "status": admin.status.value,
        "low_balance_threshold_toman": str(wallet.low_balance_threshold_toman),
        "debt_limit_toman": str(wallet.debt_limit_toman),
        "block_new_clients_when_low": wallet.block_new_clients_when_low,
        "block_renewals_when_low": wallet.block_renewals_when_low,
    }

    if payload.display_name is not None:
        admin.display_name = payload.display_name
    if payload.telegram_id is not None:
        admin.telegram_id = payload.telegram_id
    if payload.status is not None:
        admin.status = payload.status
    if payload.password is not None:
        admin.password_hash = hash_password(payload.password)
    if payload.low_balance_threshold_toman is not None:
        wallet.low_balance_threshold_toman = payload.low_balance_threshold_toman
    if payload.debt_limit_toman is not None:
        wallet.debt_limit_toman = payload.debt_limit_toman
    if payload.block_new_clients_when_low is not None:
        wallet.block_new_clients_when_low = payload.block_new_clients_when_low
    if payload.block_renewals_when_low is not None:
        wallet.block_renewals_when_low = payload.block_renewals_when_low

    await write_audit(
        db,
        actor_user_id=owner.id,
        action="admin.update",
        entity_type="admin",
        entity_id=str(admin.id),
        before_data=before,
        after_data={
            "display_name": admin.display_name,
            "status": admin.status.value,
            "password_rotated": payload.password is not None,
            "low_balance_threshold_toman": str(wallet.low_balance_threshold_toman),
            "debt_limit_toman": str(wallet.debt_limit_toman),
            "block_new_clients_when_low": wallet.block_new_clients_when_low,
            "block_renewals_when_low": wallet.block_renewals_when_low,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {"ok": True}


@app.post(f"{settings.api_prefix}/admins/{{admin_id}}/wallet/adjust")
async def adjust_admin_wallet(
    admin_id: uuid.UUID,
    payload: WalletAdjustmentIn,
    request: Request,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    if payload.amount_toman == 0:
        raise HTTPException(status_code=400, detail="adjustment amount cannot be zero")
    admin = await db.scalar(select(User).where(User.id == admin_id, User.role == Role.ADMIN))
    if not admin:
        raise HTTPException(status_code=404, detail="admin not found")
    wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == admin.id))
    txn = await apply_wallet_transaction(
        db,
        wallet_id=wallet.id,
        txn_type=WalletTxnType.ADJUSTMENT,
        amount_toman=payload.amount_toman,
        idempotency_key=f"adjustment:{uuid.uuid4()}",
        actor_user_id=owner.id,
        reference_type="admin",
        reference_id=str(admin.id),
        description=payload.note,
    )
    await write_audit(
        db,
        actor_user_id=owner.id,
        action="wallet.adjust",
        entity_type="wallet",
        entity_id=str(wallet.id),
        after_data={
            "admin_id": str(admin.id),
            "amount_toman": str(payload.amount_toman),
            "balance_after_toman": str(txn.balance_after_toman),
            "note": payload.note,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {
        "transaction_id": str(txn.id),
        "balance_toman": str(txn.balance_after_toman),
    }


@app.get(f"{settings.api_prefix}/wallet/transactions")
async def wallet_transactions(
    limit: int = 100,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == user.id))
    if not wallet:
        return []
    rows = (
        await db.execute(
            select(WalletTransaction)
            .where(WalletTransaction.wallet_id == wallet.id)
            .order_by(WalletTransaction.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return [{
        "id": str(item.id),
        "type": item.txn_type.value,
        "amount_toman": str(item.amount_toman),
        "balance_after_toman": str(item.balance_after_toman),
        "reference_type": item.reference_type,
        "reference_id": item.reference_id,
        "description": item.description,
        "created_at": item.created_at,
    } for item in rows]


@app.get(f"{settings.api_prefix}/admins/{{admin_id}}/wallet/transactions")
async def owner_admin_wallet_transactions(
    admin_id: uuid.UUID,
    limit: int = 100,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == admin_id))
    if not wallet:
        raise HTTPException(status_code=404, detail="admin wallet not found")
    rows = (
        await db.execute(
            select(WalletTransaction)
            .where(WalletTransaction.wallet_id == wallet.id)
            .order_by(WalletTransaction.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return [{
        "id": str(item.id),
        "type": item.txn_type.value,
        "amount_toman": str(item.amount_toman),
        "balance_after_toman": str(item.balance_after_toman),
        "description": item.description,
        "created_at": item.created_at,
    } for item in rows]


@app.patch(f"{settings.api_prefix}/connections/{{connection_id}}")
async def update_connection(
    connection_id: uuid.UUID,
    payload: ConnectionUpdateIn,
    request: Request,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(
        select(PasarGuardConnection).where(PasarGuardConnection.id == connection_id).with_for_update()
    )
    if not row:
        raise HTTPException(status_code=404, detail="connection not found")

    before = {"name": row.name, "base_url": row.base_url, "enabled": row.enabled}
    if payload.name is not None:
        row.name = payload.name
    if payload.base_url is not None:
        row.base_url = str(payload.base_url).rstrip("/")
    if payload.api_token is not None:
        row.encrypted_api_token = encrypt_secret(payload.api_token)
    if payload.enabled is not None:
        row.enabled = payload.enabled

    pg = PasarGuardClient(row.base_url, row.encrypted_api_token)
    try:
        await pg.health()
        row.last_error = None
    except Exception as exc:
        row.last_error = str(exc)[:1000]
        raise HTTPException(status_code=400, detail="updated PasarGuard connection failed validation") from exc

    await write_audit(
        db,
        actor_user_id=owner.id,
        action="pasarguard_connection.update",
        entity_type="pasarguard_connection",
        entity_id=str(row.id),
        before_data=before,
        after_data={"name": row.name, "base_url": row.base_url, "enabled": row.enabled},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {"ok": True}


@app.post(f"{settings.api_prefix}/connections/{{connection_id}}/test")
async def test_connection(
    connection_id: uuid.UUID,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(select(PasarGuardConnection).where(PasarGuardConnection.id == connection_id))
    if not row:
        raise HTTPException(status_code=404, detail="connection not found")
    pg = PasarGuardClient(row.base_url, row.encrypted_api_token)
    try:
        identity = await pg.health()
        row.last_error = None
        await db.commit()
        return {"connected": True, "identity": identity}
    except Exception as exc:
        row.last_error = str(exc)[:1000]
        await db.commit()
        raise HTTPException(status_code=502, detail="PasarGuard connection failed") from exc


@app.delete(f"{settings.api_prefix}/connections/{{connection_id}}", status_code=204)
async def disable_connection(
    connection_id: uuid.UUID,
    request: Request,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(select(PasarGuardConnection).where(PasarGuardConnection.id == connection_id))
    if not row:
        raise HTTPException(status_code=404, detail="connection not found")
    row.enabled = False
    await write_audit(
        db,
        actor_user_id=owner.id,
        action="pasarguard_connection.disable",
        entity_type="pasarguard_connection",
        entity_id=str(row.id),
        after_data={"enabled": False},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return None


@app.patch(f"{settings.api_prefix}/plans/{{plan_id}}")
async def update_plan(
    plan_id: uuid.UUID,
    payload: PlanUpdateIn,
    request: Request,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    plan = await db.scalar(select(Plan).where(Plan.id == plan_id).with_for_update())
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found")
    before = {
        "name": plan.name,
        "enabled": plan.enabled,
        "base_price_per_gib_toman": str(plan.base_price_per_gib_toman),
    }
    for field in (
        "name",
        "enabled",
        "base_price_per_gib_toman",
        "min_quota_gib",
        "max_quota_gib",
        "max_duration_days",
        "default_hwid_limit",
        "allow_custom_quota",
        "allow_custom_duration",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(plan, field, value)

    if (
        plan.min_quota_gib is not None
        and plan.max_quota_gib is not None
        and plan.min_quota_gib > plan.max_quota_gib
    ):
        raise HTTPException(status_code=400, detail="min quota cannot exceed max quota")

    await write_audit(
        db,
        actor_user_id=owner.id,
        action="plan.update",
        entity_type="plan",
        entity_id=str(plan.id),
        before_data=before,
        after_data={
            "name": plan.name,
            "enabled": plan.enabled,
            "base_price_per_gib_toman": str(plan.base_price_per_gib_toman),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {"ok": True}


@app.delete(f"{settings.api_prefix}/plans/{{plan_id}}", status_code=204)
async def disable_plan(
    plan_id: uuid.UUID,
    request: Request,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    plan = await db.scalar(select(Plan).where(Plan.id == plan_id))
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found")
    plan.enabled = False
    await write_audit(
        db,
        actor_user_id=owner.id,
        action="plan.disable",
        entity_type="plan",
        entity_id=str(plan.id),
        after_data={"enabled": False},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return None


@app.delete(f"{settings.api_prefix}/admins/{{admin_id}}/plans/{{plan_id}}", status_code=204)
async def unassign_admin_plan(
    admin_id: uuid.UUID,
    plan_id: uuid.UUID,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    item = await db.scalar(
        select(AdminPlan).where(AdminPlan.admin_id == admin_id, AdminPlan.plan_id == plan_id)
    )
    if not item:
        return None
    item.enabled = False
    await db.commit()
    return None


@app.patch(f"{settings.api_prefix}/my-plans/{{plan_id}}/retail-price")
async def update_my_retail_price(
    plan_id: uuid.UUID,
    payload: RetailPriceIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="admin access required")
    item = await db.scalar(
        select(AdminPlan).where(
            AdminPlan.admin_id == user.id,
            AdminPlan.plan_id == plan_id,
            AdminPlan.enabled.is_(True),
        ).with_for_update()
    )
    if not item:
        raise HTTPException(status_code=404, detail="assigned plan not found")
    plan = await db.scalar(select(Plan).where(Plan.id == plan_id))
    if payload.retail_price_per_gib_toman < plan.base_price_per_gib_toman:
        raise HTTPException(status_code=400, detail="retail price cannot be below owner cost")
    item.retail_price_per_gib_toman = payload.retail_price_per_gib_toman
    await db.commit()
    return {"ok": True, "retail_price_per_gib_toman": str(item.retail_price_per_gib_toman)}


@app.get(f"{settings.api_prefix}/notifications")
async def list_notifications(
    unread_only: bool = False,
    limit: int = 100,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    rows = (
        await db.execute(stmt.order_by(Notification.created_at.desc()).limit(max(1, min(limit, 300))))
    ).scalars()
    return [{
        "id": str(item.id),
        "kind": item.kind,
        "title": item.title,
        "message": item.message,
        "entity_type": item.entity_type,
        "entity_id": item.entity_id,
        "is_read": item.is_read,
        "created_at": item.created_at,
    } for item in rows]


@app.post(f"{settings.api_prefix}/notifications/{{notification_id}}/read")
async def read_notification(
    notification_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="notification not found")
    row.is_read = True
    await db.commit()
    return {"ok": True}


@app.get(f"{settings.api_prefix}/audit-logs")
async def audit_logs(
    limit: int = 100,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    ).scalars()
    return [{
        "id": str(item.id),
        "actor_user_id": str(item.actor_user_id) if item.actor_user_id else None,
        "action": item.action,
        "entity_type": item.entity_type,
        "entity_id": item.entity_id,
        "before_data": item.before_data,
        "after_data": item.after_data,
        "ip_address": item.ip_address,
        "created_at": item.created_at,
    } for item in rows]


@app.get(f"{settings.api_prefix}/dashboard/summary")
async def dashboard_summary(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    today = datetime.now(timezone.utc).date()

    client_stmt = select(func.count(Client.id))
    active_client_stmt = select(func.count(Client.id)).where(Client.status == ClientStatus.ACTIVE)
    usage_stmt = select(func.coalesce(func.sum(Client.last_lifetime_usage_bytes), 0))
    order_stmt = select(func.count(Order.id))
    today_order_stmt = select(func.count(Order.id)).where(
        func.date(Order.created_at) == today
    )
    payment_stmt = select(func.coalesce(func.sum(Payment.amount_toman), 0)).where(
        Payment.status == PaymentStatus.PAID
    )
    today_payment_stmt = select(func.coalesce(func.sum(Payment.amount_toman), 0)).where(
        Payment.status == PaymentStatus.PAID,
        func.date(Payment.created_at) == today,
    )

    if user.role == Role.ADMIN:
        client_stmt = client_stmt.where(Client.admin_id == user.id)
        active_client_stmt = active_client_stmt.where(Client.admin_id == user.id)
        usage_stmt = usage_stmt.where(Client.admin_id == user.id)
        order_stmt = order_stmt.where(Order.admin_id == user.id)
        today_order_stmt = today_order_stmt.where(Order.admin_id == user.id)
        payment_stmt = payment_stmt.where(Payment.admin_id == user.id)
        today_payment_stmt = today_payment_stmt.where(Payment.admin_id == user.id)

    wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == user.id))
    return {
        "role": user.role.value,
        "admins": int(await db.scalar(select(func.count(User.id)).where(User.role == Role.ADMIN)))
        if user.role == Role.OWNER else None,
        "clients": int(await db.scalar(client_stmt) or 0),
        "active_clients": int(await db.scalar(active_client_stmt) or 0),
        "lifetime_usage_bytes": int(await db.scalar(usage_stmt) or 0),
        "orders": int(await db.scalar(order_stmt) or 0),
        "today_orders": int(await db.scalar(today_order_stmt) or 0),
        "paid_volume_toman": str(await db.scalar(payment_stmt) or 0),
        "today_paid_toman": str(await db.scalar(today_payment_stmt) or 0),
        "wallet_balance_toman": str(wallet.balance_toman if wallet else 0),
        "pending_payments": int(
            await db.scalar(
                select(func.count(Payment.id)).where(
                    Payment.status == PaymentStatus.AWAITING_REVIEW,
                    *([] if user.role == Role.OWNER else [Payment.admin_id == user.id]),
                )
            ) or 0
        ),
    }


@app.get(f"{settings.api_prefix}/reports/financial")
async def financial_report(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    payment_stmt = select(
        func.coalesce(func.sum(Payment.amount_toman), 0)
    ).where(Payment.status == PaymentStatus.PAID)
    billing_stmt = select(
        func.coalesce(func.sum(BillingEvent.amount_toman), 0)
    )
    orders_stmt = select(func.count(Order.id)).where(Order.status == OrderStatus.PROVISIONED)

    if user.role == Role.ADMIN:
        payment_stmt = payment_stmt.where(Payment.admin_id == user.id)
        billing_stmt = billing_stmt.where(BillingEvent.admin_id == user.id)
        orders_stmt = orders_stmt.where(Order.admin_id == user.id)

    revenue = Decimal(await db.scalar(payment_stmt) or 0)
    cost = Decimal(await db.scalar(billing_stmt) or 0)
    return {
        "sales_toman": str(revenue),
        "actual_usage_cost_toman": str(cost),
        "gross_margin_toman": str(revenue - cost),
        "provisioned_orders": int(await db.scalar(orders_stmt) or 0),
    }


# ---- Commerce / order checkout ---------------------------------------------

from fastapi.responses import RedirectResponse

from app.services.commerce import (
    create_admin_gateway_topup,
    create_card_order_payment,
    create_gateway_order_payment,
    create_order as commerce_create_order,
    get_or_create_customer,
    pay_order_from_customer_wallet,
    verify_gateway_payment,
)


class CustomerCreateIn(BaseModel):
    admin_id: uuid.UUID | None = None
    username: str | None = Field(default=None, max_length=160)
    display_name: str | None = Field(default=None, max_length=200)
    telegram_user_id: int | None = None


class OrderCreateIn(BaseModel):
    admin_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    plan_id: uuid.UUID
    quota_gib: Decimal = Field(gt=0)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    payment_method: PaymentMethod


class GatewayTopupIn(BaseModel):
    amount_toman: Decimal = Field(gt=0)


async def _resolve_order_admin(
    user: User,
    requested_admin_id: uuid.UUID | None,
    db: AsyncSession,
) -> User:
    if user.role == Role.ADMIN:
        if requested_admin_id and requested_admin_id != user.id:
            raise HTTPException(status_code=403, detail="cannot act for another admin")
        return user
    if not requested_admin_id:
        raise HTTPException(status_code=400, detail="admin_id is required")
    admin = await db.scalar(
        select(User).where(User.id == requested_admin_id, User.role == Role.ADMIN)
    )
    if not admin:
        raise HTTPException(status_code=404, detail="admin not found")
    return admin


@app.get(f"{settings.api_prefix}/customers")
async def list_customers(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Customer).order_by(Customer.created_at.desc())
    if user.role == Role.ADMIN:
        stmt = stmt.where(Customer.admin_id == user.id)
    rows = (await db.execute(stmt)).scalars()
    return [{
        "id": str(item.id),
        "admin_id": str(item.admin_id),
        "telegram_user_id": item.telegram_user_id,
        "username": item.username,
        "display_name": item.display_name,
        "wallet_balance_toman": str(item.wallet_balance_toman),
        "created_at": item.created_at,
    } for item in rows]


@app.post(f"{settings.api_prefix}/customers", status_code=201)
async def create_customer(
    payload: CustomerCreateIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    admin = await _resolve_order_admin(user, payload.admin_id, db)
    customer = await get_or_create_customer(
        db,
        admin_id=admin.id,
        telegram_user_id=payload.telegram_user_id,
        username=payload.username,
        display_name=payload.display_name,
    )
    await db.commit()
    return {
        "id": str(customer.id),
        "admin_id": str(customer.admin_id),
        "wallet_balance_toman": str(customer.wallet_balance_toman),
    }


@app.get(f"{settings.api_prefix}/customers/{{customer_id}}/wallet/transactions")
async def customer_wallet_transactions(
    customer_id: uuid.UUID,
    limit: int = 100,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models import CustomerWalletTransaction

    customer = await db.scalar(select(Customer).where(Customer.id == customer_id))
    if not customer:
        raise HTTPException(status_code=404, detail="customer not found")
    if user.role == Role.ADMIN and customer.admin_id != user.id:
        raise HTTPException(status_code=403, detail="customer belongs to another admin")

    rows = (
        await db.execute(
            select(CustomerWalletTransaction)
            .where(CustomerWalletTransaction.customer_id == customer.id)
            .order_by(CustomerWalletTransaction.created_at.desc())
            .limit(max(1, min(limit, 300)))
        )
    ).scalars()
    return [{
        "id": str(item.id),
        "type": item.txn_type,
        "amount_toman": str(item.amount_toman),
        "balance_after_toman": str(item.balance_after_toman),
        "description": item.description,
        "created_at": item.created_at,
    } for item in rows]


@app.get(f"{settings.api_prefix}/orders")
async def list_orders(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Order).order_by(Order.created_at.desc())
    if user.role == Role.ADMIN:
        stmt = stmt.where(Order.admin_id == user.id)
    rows = (await db.execute(stmt)).scalars()
    return [{
        "id": str(item.id),
        "admin_id": str(item.admin_id),
        "customer_id": str(item.customer_id) if item.customer_id else None,
        "plan_id": str(item.plan_id),
        "quota_bytes": item.quota_bytes,
        "duration_days": item.duration_days,
        "retail_amount_toman": str(item.retail_amount_toman),
        "payment_method": item.payment_method.value,
        "status": item.status.value,
        "client_id": str(item.client_id) if item.client_id else None,
        "created_at": item.created_at,
    } for item in rows]


@app.post(f"{settings.api_prefix}/orders", status_code=201)
async def create_order_checkout(
    payload: OrderCreateIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    admin = await _resolve_order_admin(user, payload.admin_id, db)
    customer = None
    if payload.customer_id:
        customer = await db.scalar(
            select(Customer).where(
                Customer.id == payload.customer_id,
                Customer.admin_id == admin.id,
            )
        )
        if not customer:
            raise HTTPException(status_code=404, detail="customer not found")

    try:
        order = await commerce_create_order(
            db,
            admin_id=admin.id,
            customer_id=customer.id if customer else None,
            plan_id=payload.plan_id,
            quota_gib=payload.quota_gib,
            duration_days=payload.duration_days,
            payment_method=payload.payment_method,
        )

        if payload.payment_method == PaymentMethod.CUSTOMER_WALLET:
            payment, client = await pay_order_from_customer_wallet(db, order)
            await db.commit()
            return {
                "order_id": str(order.id),
                "status": order.status.value,
                "payment_id": str(payment.id),
                "client_id": str(client.id),
                "subscription_url": client.subscription_url,
            }

        if payload.payment_method == PaymentMethod.CARD_TO_CARD:
            payment = await create_card_order_payment(db, order)
            from app.services.commerce import default_bank_card
            card = await default_bank_card(db, admin.id)
            await db.commit()
            return {
                "order_id": str(order.id),
                "status": order.status.value,
                "payment_id": str(payment.id),
                "payment_status": payment.status.value,
                "amount_toman": str(payment.amount_toman),
                "card_id": str(card.id) if card else None,
                "card_number": card.card_number if card else None,
                "card_holder_name": card.card_holder_name if card else None,
                "card_instructions": card.instructions if card else None,
            }

        if payload.payment_method == PaymentMethod.GATEWAY:
            payment, gateway = await create_gateway_order_payment(db, order)
            await db.commit()
            return {
                "order_id": str(order.id),
                "status": order.status.value,
                "payment_id": str(payment.id),
                "payment_status": payment.status.value,
                "amount_toman": str(payment.amount_toman),
                "redirect_url": gateway.redirect_url,
            }

        raise HTTPException(status_code=400, detail="unsupported checkout payment method")

    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        if exc.__class__.__name__ == "CustomerInsufficientFundsError":
            raise HTTPException(status_code=402, detail="customer wallet balance is insufficient") from exc
        if isinstance(exc, PermissionError):
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise


@app.post(f"{settings.api_prefix}/wallet/topups/gateway", status_code=201)
async def create_wallet_gateway_topup(
    payload: GatewayTopupIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="admin access required")
    try:
        payment, gateway = await create_admin_gateway_topup(
            db,
            admin=user,
            amount_toman=payload.amount_toman,
        )
        await db.commit()
        return {
            "payment_id": str(payment.id),
            "amount_toman": str(payment.amount_toman),
            "redirect_url": gateway.redirect_url,
        }
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/payments/{{payment_id}}/receipt", status_code=201)
async def upload_payment_receipt(
    payment_id: uuid.UUID,
    receipt: UploadFile = File(...),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    payment = await db.scalar(select(Payment).where(Payment.id == payment_id))
    if not payment:
        raise HTTPException(status_code=404, detail="payment not found")
    if user.role == Role.ADMIN and payment.admin_id != user.id:
        raise HTTPException(status_code=403, detail="payment belongs to another admin")
    if payment.method != PaymentMethod.CARD_TO_CARD:
        raise HTTPException(status_code=409, detail="payment is not card-to-card")
    if payment.status not in {PaymentStatus.PENDING, PaymentStatus.AWAITING_REVIEW}:
        raise HTTPException(status_code=409, detail="payment no longer accepts receipts")

    allowed_types = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
    if receipt.content_type not in allowed_types:
        raise HTTPException(status_code=415, detail="receipt must be JPG, PNG, WEBP or PDF")
    raw = await receipt.read(5 * 1024 * 1024 + 1)
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="receipt must be between 1 byte and 5 MB")

    existing = await db.scalar(
        select(PaymentReceipt).where(PaymentReceipt.payment_id == payment.id)
    )
    values = {
        "original_name": (receipt.filename or "")[:255] or None,
        "mime_type": receipt.content_type or "application/octet-stream",
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "encrypted_data": encrypt_secret(base64.b64encode(raw).decode()),
    }
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
    else:
        db.add(PaymentReceipt(payment_id=payment.id, **values))

    payment.status = PaymentStatus.AWAITING_REVIEW
    await db.commit()
    return {"payment_id": str(payment.id), "status": payment.status.value}


@app.get(f"{settings.api_prefix}/gateway/callback/{{payment_id}}")
async def gateway_callback(
    payment_id: uuid.UUID,
    Authority: str,
    Status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        payment, client = await verify_gateway_payment(
            db,
            payment_id=payment_id,
            authority=Authority,
            callback_status=Status,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        return RedirectResponse(
            url=settings.public_web_url.rstrip("/") + "/?payment=failed",
            status_code=302,
        )

    result = "success" if payment.status == PaymentStatus.PAID else "failed"
    suffix = f"&client={client.id}" if client else ""
    return RedirectResponse(
        url=settings.public_web_url.rstrip("/") + f"/?payment={result}{suffix}",
        status_code=302,
    )


# ---- Readiness and recovery -------------------------------------------------

from sqlalchemy import text as sql_text

from app.services.backup import export_backup, merge_restore


@app.get("/ready")
async def readiness():
    from redis.asyncio import Redis

    database_ok = False
    redis_ok = False
    try:
        async with SessionLocal() as db:
            await db.execute(sql_text("SELECT 1"))
            database_ok = True
    except Exception:
        database_ok = False

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        redis_ok = bool(await redis.ping())
    except Exception:
        redis_ok = False
    finally:
        try:
            await redis.aclose()
        except Exception:
            pass

    code = 200 if database_ok and redis_ok else 503
    return Response(
        content=json.dumps(
            {
                "ok": database_ok and redis_ok,
                "database": database_ok,
                "redis": redis_ok,
                "service": "primevpn-api",
            }
        ),
        status_code=code,
        media_type="application/json",
    )


@app.get(f"{settings.api_prefix}/backups/export")
async def download_backup(
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone

    encrypted = await export_backup(db)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=encrypted.encode(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="primevpn-{stamp}.pvbackup"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post(f"{settings.api_prefix}/backups/restore")
async def restore_backup(
    request: Request,
    backup: UploadFile = File(...),
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    raw = await backup.read(25 * 1024 * 1024 + 1)
    if not raw or len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="backup must be between 1 byte and 25 MB")
    try:
        result = await merge_restore(db, raw.decode())
        await write_audit(
            db,
            actor_user_id=owner.id,
            action="backup.restore_merge",
            entity_type="system",
            entity_id=None,
            after_data=result,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()
        return result
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail="backup could not be restored") from exc


# ---- Scalable directories and standalone bank cards ------------------------

from math import ceil
from sqlalchemy import or_

from app.models import BankCard


def _page_meta(total: int, page: int, page_size: int) -> dict:
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, ceil(total / page_size)) if total else 0,
    }


@app.get(f"{settings.api_prefix}/directory/admins")
async def directory_admins(
    q: str = "",
    status_filter: AccountStatus | None = None,
    page: int = 1,
    page_size: int = 25,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    page = max(1, page)
    page_size = max(10, min(page_size, 100))
    stmt = select(User).where(User.role == Role.ADMIN)
    count_stmt = select(func.count(User.id)).where(User.role == Role.ADMIN)
    if q.strip():
        term = f"%{q.strip()}%"
        clause = or_(User.username.ilike(term), User.display_name.ilike(term))
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if status_filter is not None:
        stmt = stmt.where(User.status == status_filter)
        count_stmt = count_stmt.where(User.status == status_filter)
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.execute(
            stmt.order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars()
    items = []
    for admin in rows:
        wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == admin.id))
        client_count = int(
            await db.scalar(select(func.count(Client.id)).where(Client.admin_id == admin.id)) or 0
        )
        items.append({
            "id": str(admin.id),
            "username": admin.username,
            "display_name": admin.display_name,
            "telegram_id": admin.telegram_id,
            "status": admin.status.value,
            "wallet_balance_toman": str(wallet.balance_toman if wallet else 0),
            "low_balance_threshold_toman": str(wallet.low_balance_threshold_toman if wallet else 0),
            "debt_limit_toman": str(wallet.debt_limit_toman if wallet else 0),
            "client_count": client_count,
            "created_at": admin.created_at,
        })
    return {"items": items, **_page_meta(total, page, page_size)}


@app.get(f"{settings.api_prefix}/directory/clients")
async def directory_clients(
    q: str = "",
    status_filter: ClientStatus | None = None,
    admin_id: uuid.UUID | None = None,
    plan_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 25,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    page = max(1, page)
    page_size = max(10, min(page_size, 100))
    filters = []
    if user.role == Role.ADMIN:
        filters.append(Client.admin_id == user.id)
    elif admin_id:
        filters.append(Client.admin_id == admin_id)
    if status_filter is not None:
        filters.append(Client.status == status_filter)
    if plan_id:
        filters.append(Client.plan_id == plan_id)
    if q.strip():
        filters.append(Client.username.ilike(f"%{q.strip()}%"))

    stmt = select(Client).where(*filters)
    count_stmt = select(func.count(Client.id)).where(*filters)
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.execute(
            stmt.order_by(Client.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars()

    admin_ids = {row.admin_id for row in rows}
    # Re-run because scalars iterator was consumed.
    rows = (
        await db.execute(
            stmt.order_by(Client.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    admins_map = {}
    if admin_ids:
        admin_rows = (await db.execute(select(User).where(User.id.in_(admin_ids)))).scalars().all()
        admins_map = {a.id: a.username for a in admin_rows}

    return {
        "items": [{
            "id": str(item.id),
            "admin_id": str(item.admin_id),
            "admin_username": admins_map.get(item.admin_id),
            "username": item.username,
            "status": item.status.value,
            "quota_bytes": item.quota_bytes,
            "expires_at": item.expires_at,
            "hwid_limit": item.hwid_limit,
            "lifetime_usage_bytes": item.last_lifetime_usage_bytes,
            "subscription_url": item.subscription_url,
            "plan_id": str(item.plan_id) if item.plan_id else None,
            "group_id": str(item.group_id),
            "created_at": item.created_at,
        } for item in rows],
        **_page_meta(total, page, page_size),
    }


@app.get(f"{settings.api_prefix}/directory/orders")
async def directory_orders(
    q: str = "",
    status_filter: OrderStatus | None = None,
    admin_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 25,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    page = max(1, page)
    page_size = max(10, min(page_size, 100))
    filters = []
    if user.role == Role.ADMIN:
        filters.append(Order.admin_id == user.id)
    elif admin_id:
        filters.append(Order.admin_id == admin_id)
    if status_filter:
        filters.append(Order.status == status_filter)

    stmt = select(Order).where(*filters)
    count_stmt = select(func.count(Order.id)).where(*filters)
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.execute(
            stmt.order_by(Order.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    if q.strip():
        term = q.strip().lower()
        rows = [r for r in rows if term in str(r.id).lower()]
    return {
        "items": [{
            "id": str(item.id),
            "admin_id": str(item.admin_id),
            "customer_id": str(item.customer_id) if item.customer_id else None,
            "plan_id": str(item.plan_id),
            "quota_bytes": item.quota_bytes,
            "duration_days": item.duration_days,
            "retail_amount_toman": str(item.retail_amount_toman),
            "payment_method": item.payment_method.value,
            "status": item.status.value,
            "client_id": str(item.client_id) if item.client_id else None,
            "created_at": item.created_at,
        } for item in rows],
        **_page_meta(total, page, page_size),
    }


@app.get(f"{settings.api_prefix}/directory/payments")
async def directory_payments(
    status_filter: PaymentStatus | None = None,
    method: PaymentMethod | None = None,
    admin_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 25,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    page = max(1, page)
    page_size = max(10, min(page_size, 100))
    filters = []
    if user.role == Role.ADMIN:
        filters.append(Payment.admin_id == user.id)
    elif admin_id:
        filters.append(Payment.admin_id == admin_id)
    if status_filter:
        filters.append(Payment.status == status_filter)
    if method:
        filters.append(Payment.method == method)
    stmt = select(Payment).where(*filters)
    total = int(await db.scalar(select(func.count(Payment.id)).where(*filters)) or 0)
    rows = (
        await db.execute(
            stmt.order_by(Payment.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return {
        "items": [{
            "id": str(item.id),
            "admin_id": str(item.admin_id),
            "customer_id": str(item.customer_id) if item.customer_id else None,
            "order_id": str(item.order_id) if item.order_id else None,
            "method": item.method.value,
            "status": item.status.value,
            "amount_toman": str(item.amount_toman),
            "provider": item.provider,
            "provider_reference": item.provider_reference,
            "purpose": (item.meta or {}).get("purpose"),
            "created_at": item.created_at,
        } for item in rows],
        **_page_meta(total, page, page_size),
    }


@app.get(f"{settings.api_prefix}/directory/customers")
async def directory_customers(
    q: str = "",
    admin_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 25,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    page = max(1, page)
    page_size = max(10, min(page_size, 100))
    filters = []
    if user.role == Role.ADMIN:
        filters.append(Customer.admin_id == user.id)
    elif admin_id:
        filters.append(Customer.admin_id == admin_id)
    if q.strip():
        term = f"%{q.strip()}%"
        filters.append(or_(Customer.username.ilike(term), Customer.display_name.ilike(term)))
    stmt = select(Customer).where(*filters)
    total = int(await db.scalar(select(func.count(Customer.id)).where(*filters)) or 0)
    rows = (
        await db.execute(
            stmt.order_by(Customer.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return {
        "items": [{
            "id": str(item.id),
            "admin_id": str(item.admin_id),
            "telegram_user_id": item.telegram_user_id,
            "username": item.username,
            "display_name": item.display_name,
            "wallet_balance_toman": str(item.wallet_balance_toman),
            "created_at": item.created_at,
        } for item in rows],
        **_page_meta(total, page, page_size),
    }


class BankCardIn(BaseModel):
    title: str = Field(default="کارت اصلی", min_length=1, max_length=120)
    card_number: str = Field(min_length=16, max_length=24)
    card_holder_name: str | None = Field(default=None, max_length=160)
    instructions: str | None = Field(default=None, max_length=1000)
    enabled: bool = True
    is_default: bool = False


class BankCardUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    card_number: str | None = Field(default=None, min_length=16, max_length=24)
    card_holder_name: str | None = Field(default=None, max_length=160)
    instructions: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = None
    is_default: bool | None = None


async def _set_default_card(db: AsyncSession, user_id: uuid.UUID, card_id: uuid.UUID):
    cards = (
        await db.execute(select(BankCard).where(BankCard.owner_user_id == user_id))
    ).scalars().all()
    for card in cards:
        card.is_default = card.id == card_id


@app.get(f"{settings.api_prefix}/bank-cards")
async def list_bank_cards(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(BankCard)
            .where(BankCard.owner_user_id == user.id)
            .order_by(BankCard.is_default.desc(), BankCard.created_at.desc())
        )
    ).scalars().all()
    return [{
        "id": str(card.id),
        "title": card.title,
        "card_number": card.card_number,
        "card_holder_name": card.card_holder_name,
        "instructions": card.instructions,
        "enabled": card.enabled,
        "is_default": card.is_default,
    } for card in rows]


@app.post(f"{settings.api_prefix}/bank-cards", status_code=201)
async def create_bank_card(
    payload: BankCardIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    clean = "".join(ch for ch in payload.card_number if ch.isdigit())
    if len(clean) != 16:
        raise HTTPException(status_code=400, detail="card number must contain 16 digits")
    existing_count = int(
        await db.scalar(select(func.count(BankCard.id)).where(BankCard.owner_user_id == user.id)) or 0
    )
    card = BankCard(
        owner_user_id=user.id,
        title=payload.title,
        card_number=clean,
        card_holder_name=payload.card_holder_name,
        instructions=payload.instructions,
        enabled=payload.enabled,
        is_default=payload.is_default or existing_count == 0,
    )
    db.add(card)
    await db.flush()
    if card.is_default:
        await _set_default_card(db, user.id, card.id)
    await db.commit()
    return {"id": str(card.id), "is_default": card.is_default}


@app.patch(f"{settings.api_prefix}/bank-cards/{{card_id}}")
async def update_bank_card(
    card_id: uuid.UUID,
    payload: BankCardUpdateIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    card = await db.scalar(
        select(BankCard).where(BankCard.id == card_id, BankCard.owner_user_id == user.id)
    )
    if not card:
        raise HTTPException(status_code=404, detail="bank card not found")
    if payload.card_number is not None:
        clean = "".join(ch for ch in payload.card_number if ch.isdigit())
        if len(clean) != 16:
            raise HTTPException(status_code=400, detail="card number must contain 16 digits")
        card.card_number = clean
    for field in ("title", "card_holder_name", "instructions", "enabled"):
        value = getattr(payload, field)
        if value is not None:
            setattr(card, field, value)
    if payload.is_default:
        await _set_default_card(db, user.id, card.id)
    await db.commit()
    return {"ok": True}


@app.delete(f"{settings.api_prefix}/bank-cards/{{card_id}}", status_code=204)
async def delete_bank_card(
    card_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    card = await db.scalar(
        select(BankCard).where(BankCard.id == card_id, BankCard.owner_user_id == user.id)
    )
    if not card:
        return None
    await db.delete(card)
    await db.commit()
    return None


@app.get(f"{settings.api_prefix}/bots/{{bot_id}}/catalog")
async def get_bot_catalog(
    bot_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    bot = await db.scalar(select(TelegramBot).where(TelegramBot.id == bot_id))
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    if user.role == Role.ADMIN and bot.admin_id != user.id:
        raise HTTPException(status_code=403, detail="bot belongs to another admin")

    rows = (
        await db.execute(
            select(AdminPlan, Plan, TelegramBotPlan)
            .join(Plan, Plan.id == AdminPlan.plan_id)
            .outerjoin(
                TelegramBotPlan,
                (TelegramBotPlan.bot_id == bot.id)
                & (TelegramBotPlan.plan_id == Plan.id),
            )
            .where(AdminPlan.admin_id == bot.admin_id, AdminPlan.enabled.is_(True))
            .order_by(Plan.name)
        )
    ).all()
    return [{
        "plan_id": str(plan.id),
        "name": plan.name,
        "base_price_per_gib_toman": str(plan.base_price_per_gib_toman),
        "retail_price_per_gib_toman": str(assignment.retail_price_per_gib_toman),
        "enabled_in_bot": bool(bot_plan and bot_plan.enabled),
        "sort_order": bot_plan.sort_order if bot_plan else 0,
    } for assignment, plan, bot_plan in rows]


class BotCatalogIn(BaseModel):
    plan_ids: list[uuid.UUID]


@app.put(f"{settings.api_prefix}/bots/{{bot_id}}/catalog")
async def update_bot_catalog(
    bot_id: uuid.UUID,
    payload: BotCatalogIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    bot = await db.scalar(select(TelegramBot).where(TelegramBot.id == bot_id))
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    if user.role == Role.ADMIN and bot.admin_id != user.id:
        raise HTTPException(status_code=403, detail="bot belongs to another admin")

    allowed = set(
        (
            await db.execute(
                select(AdminPlan.plan_id).where(
                    AdminPlan.admin_id == bot.admin_id,
                    AdminPlan.enabled.is_(True),
                )
            )
        ).scalars().all()
    )
    requested = set(payload.plan_ids)
    if not requested.issubset(allowed):
        raise HTTPException(status_code=403, detail="catalog contains an unassigned plan")

    existing = (
        await db.execute(select(TelegramBotPlan).where(TelegramBotPlan.bot_id == bot.id))
    ).scalars().all()
    by_plan = {row.plan_id: row for row in existing}
    for index, plan_id in enumerate(payload.plan_ids):
        row = by_plan.get(plan_id)
        if row is None:
            row = TelegramBotPlan(bot_id=bot.id, plan_id=plan_id)
            db.add(row)
        row.enabled = True
        row.sort_order = index
    for plan_id, row in by_plan.items():
        if plan_id not in requested:
            row.enabled = False

    await db.commit()
    return {"ok": True, "enabled_plans": len(payload.plan_ids)}
