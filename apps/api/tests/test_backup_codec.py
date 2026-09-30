import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.services.backup import decode_value, encode_value


def test_backup_codec_preserves_supported_types():
    value = {
        "id": uuid.uuid4(),
        "at": datetime.now(timezone.utc).replace(microsecond=0),
        "amount": Decimal("1234.5000"),
        "items": [Decimal("1.25"), "ok", None],
    }
    assert decode_value(encode_value(value)) == value
