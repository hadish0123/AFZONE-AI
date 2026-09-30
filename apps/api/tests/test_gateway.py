import pytest

from app.services.gateways import UnsupportedGatewayError, ZarinpalGateway, build_gateway


def test_zarinpal_adapter_selection():
    gateway = build_gateway("zarinpal", {"merchant_id": "12345678-1234-1234-1234-123456789012"})
    assert isinstance(gateway, ZarinpalGateway)


def test_unknown_gateway_is_rejected():
    with pytest.raises(UnsupportedGatewayError):
        build_gateway("unknown", {})
