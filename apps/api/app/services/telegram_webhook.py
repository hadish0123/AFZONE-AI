import hashlib
import hmac
import uuid

from app.core.config import get_settings

settings = get_settings()

TELEGRAM_UPDATE_STREAM = "primevpn:telegram:updates"
TELEGRAM_UPDATE_GROUP = "primevpn:telegram-workers"
TELEGRAM_CONTROL_STREAM = "primevpn:telegram:control"
TELEGRAM_CONTROL_GROUP = "primevpn:telegram-control-workers"
TELEGRAM_DONE_TTL_SECONDS = 7 * 24 * 60 * 60
TELEGRAM_PROCESSING_TTL_SECONDS = 120
TELEGRAM_MAX_UPDATE_BYTES = 1_000_000


def telegram_webhook_secret(bot_id: uuid.UUID) -> str:
    key = settings.encryption_key.encode("utf-8")
    payload = f"primevpn:telegram:webhook:{bot_id}".encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def telegram_webhook_url(bot_id: uuid.UUID) -> str:
    base = settings.public_api_url.rstrip("/")
    return f"{base}{settings.api_prefix}/telegram/webhook/{bot_id}"


def telegram_done_key(bot_id: uuid.UUID, update_id: int) -> str:
    return f"primevpn:telegram:done:{bot_id}:{update_id}"


def telegram_processing_key(bot_id: uuid.UUID, update_id: int) -> str:
    return f"primevpn:telegram:processing:{bot_id}:{update_id}"
