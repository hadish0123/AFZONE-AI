from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Client,
    ClientStatus,
    Order,
    OrderStatus,
    PasarGuardConnection,
    PasarGuardGroup,
    Plan,
    UsageCheckpoint,
)
from app.services.pasarguard import PasarGuardClient, PasarGuardError


async def provision_paid_order(db: AsyncSession, order_id) -> Client:
    order = await db.scalar(
        select(Order).where(Order.id == order_id).with_for_update()
    )
    if not order:
        raise ValueError("order not found")
    if order.status not in {OrderStatus.PAID, OrderStatus.PROVISIONED}:
        raise ValueError("order must be paid before provisioning")

    if order.client_id:
        existing = await db.scalar(select(Client).where(Client.id == order.client_id))
        if existing:
            return existing

    plan = await db.scalar(select(Plan).where(Plan.id == order.plan_id))
    if not plan or not plan.enabled:
        raise ValueError("order plan is unavailable")

    group = await db.scalar(
        select(PasarGuardGroup).where(PasarGuardGroup.id == plan.group_id)
    )
    if not group or not group.enabled_remote:
        raise ValueError("PasarGuard group is unavailable")

    connection = await db.scalar(
        select(PasarGuardConnection).where(
            PasarGuardConnection.id == group.connection_id,
            PasarGuardConnection.enabled.is_(True),
        )
    )
    if not connection:
        raise ValueError("PasarGuard connection is unavailable")

    username = f"pv_{order.id.hex[:20]}"
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=order.duration_days)
        if order.duration_days
        else None
    )

    payload = {
        "username": username,
        "status": "active",
        "expire": expires_at.isoformat() if expires_at else 0,
        "data_limit": int(order.quota_bytes),
        "data_limit_reset_strategy": "no_reset",
        "group_ids": [group.remote_group_id],
        "note": f"PRIMEVPN order {order.id}",
        "hwid_limit": plan.default_hwid_limit,
    }
    payload = {key: value for key, value in payload.items() if value is not None}

    pg = PasarGuardClient(connection.base_url, connection.encrypted_api_token)
    try:
        remote = await pg.create_user(payload)
    except PasarGuardError as exc:
        # Deterministic usernames make the external create idempotent. If a
        # previous attempt created the PasarGuard user but PRIMEVPN did not
        # commit, recover the existing remote user on retry.
        if "HTTP 409" not in str(exc):
            raise
        remote = await pg.get_user(username)

    client = await db.scalar(
        select(Client).where(
            Client.connection_id == connection.id,
            Client.username == username,
        )
    )
    if client is None:
        client = Client(
            admin_id=order.admin_id,
            connection_id=connection.id,
            plan_id=plan.id,
            group_id=group.id,
            remote_user_id=int(remote["id"]),
            username=remote["username"],
            quota_bytes=int(remote.get("data_limit") or order.quota_bytes),
            expires_at=expires_at,
            hwid_limit=remote.get("hwid_limit", plan.default_hwid_limit),
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

    order.client_id = client.id
    order.status = OrderStatus.PROVISIONED
    await db.flush()
    return client
