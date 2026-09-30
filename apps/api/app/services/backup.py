import enum
import json
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret, encrypt_secret
from app.models import Base

BACKUP_VERSION = 1
EXCLUDED_TABLES = {"auth_sessions"}


def encode_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, uuid.UUID):
        return {"__type__": "uuid", "value": str(value)}
    if isinstance(value, datetime):
        return {"__type__": "datetime", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"__type__": "decimal", "value": str(value)}
    if isinstance(value, enum.Enum):
        return {"__type__": "enum", "value": value.value}
    if isinstance(value, dict):
        return {str(k): encode_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_value(v) for v in value]
    return str(value)


def decode_value(value):
    if isinstance(value, list):
        return [decode_value(v) for v in value]
    if not isinstance(value, dict):
        return value
    tag = value.get("__type__")
    if tag == "uuid":
        return uuid.UUID(value["value"])
    if tag == "datetime":
        return datetime.fromisoformat(value["value"])
    if tag == "decimal":
        return Decimal(value["value"])
    if tag == "enum":
        return value["value"]
    return {k: decode_value(v) for k, v in value.items()}


async def export_backup(db: AsyncSession) -> str:
    tables = {}
    for table in Base.metadata.sorted_tables:
        if table.name in EXCLUDED_TABLES:
            continue
        result = await db.execute(table.select())
        rows = []
        for mapping in result.mappings().all():
            rows.append({key: encode_value(value) for key, value in mapping.items()})
        tables[table.name] = rows

    payload = {
        "format": "PRIMEVPN_BACKUP",
        "version": BACKUP_VERSION,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "tables": tables,
    }
    return encrypt_secret(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


async def merge_restore(db: AsyncSession, encrypted_payload: str) -> dict:
    raw = decrypt_secret(encrypted_payload.strip())
    payload = json.loads(raw)
    if payload.get("format") != "PRIMEVPN_BACKUP" or payload.get("version") != BACKUP_VERSION:
        raise ValueError("unsupported PRIMEVPN backup format")
    source = payload.get("tables")
    if not isinstance(source, dict):
        raise ValueError("invalid backup tables")

    restored = {}
    # Foreign-key safe insertion order follows SQLAlchemy's sorted metadata.
    for table in Base.metadata.sorted_tables:
        if table.name in EXCLUDED_TABLES:
            continue
        encoded_rows = source.get(table.name) or []
        if not encoded_rows:
            restored[table.name] = 0
            continue
        rows = [
            {key: decode_value(value) for key, value in row.items()}
            for row in encoded_rows
        ]
        stmt = insert(table).values(rows).on_conflict_do_nothing()
        result = await db.execute(stmt)
        restored[table.name] = max(0, int(result.rowcount or 0))

    await db.flush()
    return {
        "backup_created_at": payload.get("created_at"),
        "inserted": restored,
    }
