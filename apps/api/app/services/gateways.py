from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(slots=True)
class GatewayCreateResult:
    authority: str
    redirect_url: str


@dataclass(slots=True)
class GatewayVerifyResult:
    paid: bool
    reference: str | None = None
    raw: dict | None = None


class PaymentGatewayAdapter(Protocol):
    async def create_payment(
        self,
        *,
        amount_toman: Decimal,
        callback_url: str,
        description: str,
        metadata: dict,
    ) -> GatewayCreateResult: ...

    async def verify_payment(
        self,
        *,
        authority: str,
        amount_toman: Decimal,
    ) -> GatewayVerifyResult: ...


class UnsupportedGatewayError(RuntimeError):
    pass


def build_gateway(provider: str, credentials: dict) -> PaymentGatewayAdapter:
    # Concrete providers are deliberately adapters. Once Owner selects the
    # production gateway (e.g. Zarinpal or another provider), its implementation
    # plugs in here without changing order/wallet domain logic.
    raise UnsupportedGatewayError(f"payment gateway provider is not installed: {provider}")
