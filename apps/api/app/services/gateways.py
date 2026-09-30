from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import httpx


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


class GatewayRequestError(RuntimeError):
    pass


class ZarinpalGateway:
    REQUEST_URL = "https://api.zarinpal.com/pg/v4/payment/request.json"
    VERIFY_URL = "https://api.zarinpal.com/pg/v4/payment/verify.json"
    PAY_URL = "https://www.zarinpal.com/pg/StartPay/"

    def __init__(self, *, merchant_id: str, timeout: float = 20.0):
        if not merchant_id or len(merchant_id) < 20:
            raise ValueError("invalid Zarinpal merchant_id")
        self.merchant_id = merchant_id
        self.timeout = timeout

    async def create_payment(
        self,
        *,
        amount_toman: Decimal,
        callback_url: str,
        description: str,
        metadata: dict,
    ) -> GatewayCreateResult:
        # PRIMEVPN keeps money in Toman. Zarinpal v4 receives amount in Rial,
        # so conversion is explicit at the adapter boundary.
        amount_rial = int(Decimal(amount_toman) * 10)
        payload = {
            "merchant_id": self.merchant_id,
            "amount": amount_rial,
            "description": description[:255] or "PRIMEVPN payment",
            "callback_url": callback_url,
            "metadata": {
                key: str(value)
                for key, value in (metadata or {}).items()
                if value not in (None, "")
            },
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.REQUEST_URL, json=payload)
        if response.status_code >= 400:
            raise GatewayRequestError(f"Zarinpal request failed with HTTP {response.status_code}")

        body = response.json()
        data = body.get("data") or {}
        if int(data.get("code") or 0) != 100 or not data.get("authority"):
            errors = body.get("errors") or {}
            raise GatewayRequestError(
                f"Zarinpal request rejected: {errors.get('code') or data.get('code') or 'unknown'}"
            )
        authority = str(data["authority"])
        return GatewayCreateResult(
            authority=authority,
            redirect_url=f"{self.PAY_URL}{authority}",
        )

    async def verify_payment(
        self,
        *,
        authority: str,
        amount_toman: Decimal,
    ) -> GatewayVerifyResult:
        amount_rial = int(Decimal(amount_toman) * 10)
        payload = {
            "merchant_id": self.merchant_id,
            "amount": amount_rial,
            "authority": authority,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.VERIFY_URL, json=payload)
        if response.status_code >= 400:
            raise GatewayRequestError(f"Zarinpal verify failed with HTTP {response.status_code}")

        body = response.json()
        data = body.get("data") or {}
        code = int(data.get("code") or 0)
        paid = code in {100, 101}
        reference = str(data.get("ref_id")) if data.get("ref_id") is not None else None
        return GatewayVerifyResult(paid=paid, reference=reference, raw=body)


def build_gateway(provider: str, credentials: dict) -> PaymentGatewayAdapter:
    normalized = (provider or "").strip().lower()
    if normalized in {"zarinpal", "زرین پال", "زرین‌پال"}:
        merchant_id = str((credentials or {}).get("merchant_id") or "").strip()
        return ZarinpalGateway(merchant_id=merchant_id)
    raise UnsupportedGatewayError(f"payment gateway provider is not installed: {provider}")
