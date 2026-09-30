import asyncio
import logging
import os
from contextlib import asynccontextmanager

from redis.asyncio import Redis
from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import Client, ClientStatus, Notification, PasarGuardConnection, User, Wallet
from app.services.billing import BillingAnomaly, bill_lifetime_usage
from app.services.pasarguard import PasarGuardClient, PasarGuardError
from app.services.wallet import InsufficientFundsError

settings = get_settings()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("primevpn.worker")

SYNC_INTERVAL_SECONDS = max(15, int(os.getenv("BILLING_SYNC_INTERVAL_SECONDS", "60")))
LOCK_TTL_SECONDS = max(SYNC_INTERVAL_SECONDS * 2, 120)
LOCK_KEY = "primevpn:billing-worker:lock"


@asynccontextmanager
async def distributed_lock(redis: Redis):
    token = os.urandom(18).hex()
    acquired = await redis.set(LOCK_KEY, token, nx=True, ex=LOCK_TTL_SECONDS)
    if not acquired:
        yield False
        return

    try:
        yield True
    finally:
        # Release only our own lock.
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
          return redis.call('del', KEYS[1])
        end
        return 0
        """
        try:
            await redis.eval(script, 1, LOCK_KEY, token)
        except Exception:
            logger.exception("Failed to release Redis billing lock")


async def list_billable_client_ids() -> list:
    async with SessionLocal() as db:
        result = await db.execute(
            select(Client.id)
            .where(Client.status == ClientStatus.ACTIVE)
            .order_by(Client.created_at)
        )
        return list(result.scalars())


async def sync_one_client(client_id) -> None:
    async with SessionLocal() as db:
        client = await db.scalar(select(Client).where(Client.id == client_id))
        if client is None or client.status != ClientStatus.ACTIVE:
            return

        connection = await db.scalar(
            select(PasarGuardConnection).where(
                PasarGuardConnection.id == client.connection_id,
                PasarGuardConnection.enabled.is_(True),
            )
        )
        if connection is None:
            logger.warning("Client %s skipped: connection unavailable", client.id)
            return

        pg = PasarGuardClient(connection.base_url, connection.encrypted_api_token)

        try:
            if client.remote_user_id is not None:
                remote = await pg.get_user_by_id(client.remote_user_id)
            else:
                remote = await pg.get_user(client.username)

            lifetime = int(remote.get("lifetime_used_traffic") or 0)
            client.last_lifetime_usage_bytes = lifetime
            client.subscription_url = remote.get("subscription_url") or client.subscription_url
            client.remote_payload = remote

            event = await bill_lifetime_usage(
                db,
                client_id=client.id,
                current_lifetime_usage_bytes=lifetime,
            )
            await db.commit()

            if event is not None:
                wallet = await db.scalar(
                    select(Wallet).where(Wallet.owner_user_id == client.admin_id)
                )
                if wallet and wallet.balance_toman <= wallet.low_balance_threshold_toman:
                    from datetime import date
                    key = f"low-balance:{client.admin_id}:{date.today().isoformat()}"
                    exists = await db.scalar(
                        select(Notification).where(Notification.dedupe_key == key)
                    )
                    if not exists:
                        db.add(Notification(
                            user_id=client.admin_id,
                            kind="low_balance",
                            title="موجودی کیف پول پایین است",
                            message=(
                                f"موجودی فعلی {wallet.balance_toman} تومان است. "
                                "برای جلوگیری از توقف ساخت یا تمدید سرویس، کیف پول را شارژ کنید."
                            ),
                            entity_type="wallet",
                            entity_id=str(wallet.id),
                            dedupe_key=key,
                        ))
                        await db.commit()
                logger.info(
                    "Billed client=%s admin=%s delta_bytes=%s amount_toman=%s",
                    client.username,
                    client.admin_id,
                    event.delta_bytes,
                    event.amount_toman,
                )

        except BillingAnomaly as exc:
            await db.commit()
            logger.error("Billing suspended for client=%s: %s", client.username, exc)
        except InsufficientFundsError:
            await db.rollback()
            admin = await db.scalar(select(User).where(User.id == client.admin_id))
            if admin:
                key = f"billing-deferred:{client.id}"
                exists = await db.scalar(
                    select(Notification).where(Notification.dedupe_key == key)
                )
                if not exists:
                    db.add(Notification(
                        user_id=admin.id,
                        kind="billing_deferred",
                        title="هزینه مصرف در انتظار تسویه",
                        message=(
                            f"مصرف کلاینت {client.username} از سقف موجودی/بدهی کیف پول عبور کرده "
                            "و هزینه آن در چرخه بعدی دوباره محاسبه می‌شود."
                        ),
                        entity_type="client",
                        entity_id=str(client.id),
                        dedupe_key=key,
                    ))
                    await db.commit()
            logger.warning(
                "Billing deferred for client=%s: admin wallet debt limit exceeded",
                client.username,
            )
        except PasarGuardError as exc:
            await db.rollback()
            logger.warning("PasarGuard sync failed for client=%s: %s", client.username, exc)
        except Exception:
            await db.rollback()
            logger.exception("Unexpected billing sync failure client=%s", client.username)


async def billing_cycle(redis: Redis) -> None:
    async with distributed_lock(redis) as acquired:
        if not acquired:
            logger.info("Another billing worker owns the cycle lock; skipping")
            return

        client_ids = await list_billable_client_ids()
        if not client_ids:
            logger.debug("No active clients to bill")
            return

        logger.info("Starting usage sync for %d active clients", len(client_ids))
        for client_id in client_ids:
            await sync_one_client(client_id)
        logger.info("Usage sync cycle complete")


async def main() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.ping()
        logger.info(
            "PRIMEVPN billing worker started interval_seconds=%d",
            SYNC_INTERVAL_SECONDS,
        )
        while True:
            started = asyncio.get_running_loop().time()
            try:
                await billing_cycle(redis)
            except Exception:
                logger.exception("Billing cycle failed")

            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(1, SYNC_INTERVAL_SECONDS - elapsed))
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
