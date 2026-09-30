import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def write_audit(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    before_data: dict | None = None,
    after_data: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    row = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_data=before_data,
        after_data=after_data,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(row)
    await db.flush()
    return row
