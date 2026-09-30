import asyncio
import base64
import hashlib
import json
import logging
import os
import socket
import uuid
from contextlib import suppress
from decimal import Decimal, InvalidOperation

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message, Update
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import and_, func, select
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret
from app.db import SessionLocal
from app.models import (
    AccountStatus,
    AdminPlan,
    Client,
    Customer,
    Notification,
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentProfile,
    PaymentReceipt,
    PaymentStatus,
    Plan,
    Role,
    TelegramBot,
    TelegramBotPlan,
    User,
    Wallet,
)
from app.services.customer_wallet import apply_customer_wallet_transaction
from app.services.orders import provision_paid_order
from app.services.telegram_webhook import (
    TELEGRAM_CONTROL_GROUP,
    TELEGRAM_CONTROL_STREAM,
    TELEGRAM_DONE_TTL_SECONDS,
    TELEGRAM_PROCESSING_TTL_SECONDS,
    TELEGRAM_UPDATE_GROUP,
    TELEGRAM_UPDATE_STREAM,
    telegram_done_key,
    telegram_processing_key,
    telegram_webhook_secret,
    telegram_webhook_url,
)
from app.services.commerce import (
    create_card_order_payment,
    create_customer_card_topup,
    create_customer_gateway_topup,
    create_gateway_order_payment,
    create_order,
    default_bank_card,
    get_or_create_customer,
    pay_order_from_customer_wallet,
)

settings = get_settings()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("primevpn.telegram")


class SaleFlow(StatesGroup):
    custom_quota = State()
    custom_duration = State()
    waiting_order_receipt = State()
    wallet_topup_amount = State()
    wallet_topup_receipt = State()


def money_text(value) -> str:
    return f"{int(Decimal(value)):,} تومان"


def brand_title(title: str, subtitle: str | None = None) -> str:
    text = f"🛡 <b>PRIMEVPN</b>\n<b>{title}</b>"
    if subtitle:
        text += f"\n\n{subtitle}"
    return text


def status_text(value) -> str:
    raw = getattr(value, "value", value)
    mapping = {
        "active": "فعال",
        "disabled": "غیرفعال",
        "error": "خطا",
        "pending": "در انتظار",
        "awaiting_review": "در انتظار بررسی",
        "paid": "پرداخت‌شده",
        "rejected": "ردشده",
        "failed": "ناموفق",
        "provisioned": "فعال‌شده",
        "cancelled": "لغوشده",
    }
    return mapping.get(str(raw), str(raw))


def purpose_text(value: str | None) -> str:
    return {
        "order_card": "خرید سرویس / کارت‌به‌کارت",
        "customer_wallet_topup": "شارژ کیف پول مشتری",
        "order_wallet": "خرید از کیف پول",
    }.get(value or "", "پرداخت")


def user_error_text(exc: Exception) -> str:
    message = str(exc).strip()
    known = {
        "order ownership mismatch": "اطلاعات سفارش با این نماینده همخوانی ندارد.",
        "customer missing": "اطلاعات مشتری پیدا نشد.",
        "customer ownership mismatch": "اطلاعات مشتری با این نماینده همخوانی ندارد.",
        "plan not found or disabled": "پلن انتخاب‌شده در دسترس نیست.",
        "quota must be positive": "حجم سرویس باید بیشتر از صفر باشد.",
    }
    if message in known:
        return known[message]
    if any("\u0600" <= ch <= "\u06ff" for ch in message):
        return message[:220]
    return "عملیات انجام نشد. دوباره تلاش کنید."


async def load_bot(bot_id: uuid.UUID) -> TelegramBot | None:
    async with SessionLocal() as db:
        return await db.scalar(select(TelegramBot).where(TelegramBot.id == bot_id))


async def resolve_customer(db, *, bot_row: TelegramBot, tg_user) -> Customer:
    display = " ".join(
        part for part in [tg_user.first_name, tg_user.last_name] if part
    ).strip() or None
    return await get_or_create_customer(
        db,
        admin_id=bot_row.admin_id,
        telegram_user_id=tg_user.id,
        username=tg_user.username,
        display_name=display,
    )


def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 خرید سرویس", callback_data="main:buy")
    kb.button(text="💰 کیف پول", callback_data="main:wallet")
    kb.button(text="📱 سرویس‌های من", callback_data="main:services")
    kb.button(text="➕ شارژ کیف پول", callback_data="main:topup")
    kb.adjust(2, 2)
    return kb.as_markup()


async def notify_admin(bot: Bot, admin_id: uuid.UUID, text: str):
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.id == admin_id))
        if admin and admin.telegram_id:
            with suppress(Exception):
                await bot.send_message(admin.telegram_id, text)


async def add_notification(
    db,
    *,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    message: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    dedupe_key: str | None = None,
):
    if dedupe_key:
        exists = await db.scalar(
            select(Notification).where(Notification.dedupe_key == dedupe_key)
        )
        if exists:
            return exists
    row = Notification(
        user_id=user_id,
        kind=kind,
        title=title,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
        dedupe_key=dedupe_key,
    )
    db.add(row)
    await db.flush()
    return row


async def receipt_bytes(message: Message, bot: Bot) -> tuple[bytes, str, str]:
    if message.photo:
        item = message.photo[-1]
        stream = await bot.download(item)
        raw = stream.read()
        return raw, "receipt.jpg", "image/jpeg"
    if message.document:
        doc = message.document
        allowed = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
        if doc.mime_type not in allowed:
            raise ValueError("فرمت رسید باید JPG، PNG، WEBP یا PDF باشد.")
        stream = await bot.download(doc)
        raw = stream.read()
        return raw, doc.file_name or "receipt", doc.mime_type or "application/octet-stream"
    raise ValueError("لطفاً تصویر یا فایل رسید را ارسال کنید.")


async def store_receipt(
    db,
    *,
    payment: Payment,
    raw: bytes,
    filename: str,
    mime_type: str,
):
    if not raw:
        raise ValueError("فایل رسید خالی است.")
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("حجم رسید نباید بیشتر از ۵ مگابایت باشد.")

    existing = await db.scalar(
        select(PaymentReceipt).where(PaymentReceipt.payment_id == payment.id)
    )
    values = {
        "original_name": filename[:255],
        "mime_type": mime_type,
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


def build_dispatcher(bot_id: uuid.UUID) -> Dispatcher:
    storage = RedisStorage.from_url(
        settings.redis_url,
        state_ttl=3600,
        data_ttl=3600,
        key_builder=DefaultKeyBuilder(with_bot_id=True),
    )
    dp = Dispatcher(storage=storage)
    router = Router(name=f"primevpn-bot-{bot_id}")

    async def get_context(tg_user):
        async with SessionLocal() as db:
            bot_row = await db.scalar(
                select(TelegramBot).where(
                    TelegramBot.id == bot_id,
                    TelegramBot.enabled.is_(True),
                )
            )
            if not bot_row:
                return None, None
            customer = await resolve_customer(db, bot_row=bot_row, tg_user=tg_user)
            await db.commit()
            return bot_row, customer

    async def show_plans(target, state: FSMContext, tg_user):
        bot_row, _ = await get_context(tg_user)
        if not bot_row:
            await target.answer("ربات موقتاً غیرفعال است.")
            return
        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(Plan, AdminPlan)
                    .outerjoin(
                        AdminPlan,
                        and_(
                            AdminPlan.plan_id == Plan.id,
                            AdminPlan.admin_id == bot_row.admin_id,
                            AdminPlan.enabled.is_(True),
                        ),
                    )
                    .where(Plan.enabled.is_(True))
                    .order_by(Plan.name)
                )
            ).all()
        if not rows:
            await target.answer("در حال حاضر پلن فعالی برای فروش وجود ندارد.")
            return
        kb = InlineKeyboardBuilder()
        for plan, admin_plan in rows:
            retail = admin_plan.retail_price_per_gib_toman if admin_plan else plan.base_price_per_gib_toman
            kb.button(
                text=f"{plan.name} · {money_text(retail)}/GB",
                callback_data=f"plan:{plan.id}",
            )
        kb.button(text="↩️ منوی اصلی", callback_data="main:home")
        kb.adjust(1)
        await state.clear()
        await target.answer("پلن موردنظر را انتخاب کنید:", reply_markup=kb.as_markup())

    async def show_quota(callback: CallbackQuery, state: FSMContext, plan_id: uuid.UUID):
        bot_row, _ = await get_context(callback.from_user)
        async with SessionLocal() as db:
            plan = await db.scalar(
                select(Plan).where(Plan.id == plan_id, Plan.enabled.is_(True))
            )
        if not plan:
            await callback.answer("این پلن دیگر در دسترس نیست.", show_alert=True)
            return
        await state.update_data(plan_id=str(plan.id))
        minimum = Decimal(plan.min_quota_gib or 1)
        maximum = Decimal(plan.max_quota_gib) if plan.max_quota_gib is not None else None
        presets = [10, 20, 30, 50, 100, 200]
        valid = [x for x in presets if Decimal(x) >= minimum and (maximum is None or Decimal(x) <= maximum)]
        kb = InlineKeyboardBuilder()
        for value in valid[:6]:
            kb.button(text=f"{value} GB", callback_data=f"quota:{value}")
        if plan.allow_custom_quota:
            kb.button(text="✏️ حجم دلخواه", callback_data="quota:custom")
        kb.button(text="↩️ پلن‌ها", callback_data="main:buy")
        kb.adjust(3, 3, 1)
        await callback.message.edit_text("حجم سرویس را انتخاب کنید:", reply_markup=kb.as_markup())
        await callback.answer()

    async def show_duration(target, state: FSMContext):
        data = await state.get_data()
        plan_id = uuid.UUID(data["plan_id"])
        async with SessionLocal() as db:
            plan = await db.scalar(select(Plan).where(Plan.id == plan_id))
        maximum = plan.max_duration_days if plan else None
        presets = [30, 60, 90, 180, 365]
        valid = [x for x in presets if maximum is None or x <= maximum]
        kb = InlineKeyboardBuilder()
        for value in valid[:5]:
            kb.button(text=f"{value} روز", callback_data=f"duration:{value}")
        if plan and plan.allow_custom_duration:
            kb.button(text="✏️ مدت دلخواه", callback_data="duration:custom")
        kb.button(text="بدون انقضا", callback_data="duration:0")
        kb.adjust(3, 3, 1)
        await target.answer(
            brand_title("انتخاب مدت", "مدت سرویس را انتخاب کنید."),
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )

    async def show_checkout(target, state: FSMContext, tg_user):
        data = await state.get_data()
        bot_row, customer = await get_context(tg_user)
        plan_id = uuid.UUID(data["plan_id"])
        quota = Decimal(str(data["quota_gib"]))
        duration = data.get("duration_days")

        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(Plan, AdminPlan)
                    .outerjoin(
                        AdminPlan,
                        and_(
                            AdminPlan.plan_id == Plan.id,
                            AdminPlan.admin_id == bot_row.admin_id,
                            AdminPlan.enabled.is_(True),
                        ),
                    )
                    .where(Plan.id == plan_id, Plan.enabled.is_(True))
                )
            ).first()
            profile = await db.scalar(
                select(PaymentProfile).where(PaymentProfile.owner_user_id == bot_row.admin_id)
            )
            card = await default_bank_card(db, bot_row.admin_id)
        if not row:
            await target.answer("پلن در دسترس نیست.")
            return
        plan, admin_plan = row
        retail = Decimal(admin_plan.retail_price_per_gib_toman if admin_plan else plan.base_price_per_gib_toman)
        amount = retail * quota

        text = brand_title(
            "پیش‌فاکتور",
            f"📦 پلن: <b>{plan.name}</b>\n"
            f"📊 حجم: <b>{quota.normalize()} GB</b>\n"
            f"📅 مدت: <b>{'بدون انقضا' if not duration else str(duration) + ' روز'}</b>\n"
            f"💳 مبلغ: <b>{money_text(amount)}</b>\n"
            f"👛 موجودی کیف پول: <b>{money_text(customer.wallet_balance_toman)}</b>",
        )
        kb = InlineKeyboardBuilder()
        if bot_row.customer_wallet_enabled:
            kb.button(text="💰 پرداخت از کیف پول", callback_data="pay:wallet")
        if bot_row.card_to_card_enabled and card:
            kb.button(text="💳 کارت به کارت", callback_data="pay:card")
        if bot_row.gateway_enabled and profile and profile.gateway_enabled:
            kb.button(text="🌐 درگاه پرداخت", callback_data="pay:gateway")
        kb.button(text="↩️ تغییر پلن", callback_data="main:buy")
        kb.adjust(1)
        await target.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


    async def manager_context(tg_user):
        async with SessionLocal() as db:
            bot_row = await db.scalar(
                select(TelegramBot).where(
                    TelegramBot.id == bot_id,
                    TelegramBot.enabled.is_(True),
                )
            )
            if not bot_row:
                return None, None
            admin = await db.scalar(
                select(User).where(
                    User.id == bot_row.admin_id,
                    User.role == Role.ADMIN,
                    User.status == AccountStatus.ACTIVE,
                )
            )
            if not admin or not admin.telegram_id or int(admin.telegram_id) != int(tg_user.id):
                return None, None
            return bot_row, admin

    def manager_menu():
        kb = InlineKeyboardBuilder()
        kb.button(text="📊 داشبورد", callback_data="mgmt:dashboard")
        kb.button(text="🧾 رسیدهای منتظر", callback_data="mgmt:pending")
        kb.button(text="📦 سفارش‌های اخیر", callback_data="mgmt:orders")
        kb.button(text="💰 کیف پول نماینده", callback_data="mgmt:wallet")
        kb.adjust(2, 2)
        return kb.as_markup()

    @router.message(Command("admin"))
    async def admin_panel(message: Message):
        bot_row, admin = await manager_context(message.from_user)
        if not bot_row or not admin:
            return
        await message.answer(
            brand_title(
                "مدیریت فروش نماینده",
                f"ربات: <b>{bot_row.name}</b>\nاین بخش فقط برای مدیر ثبت‌شده همین ربات قابل مشاهده است.",
            ),
            parse_mode="HTML",
            reply_markup=manager_menu(),
        )

    @router.callback_query(F.data.startswith("mgmt:"))
    async def manager_actions(callback: CallbackQuery):
        bot_row, admin = await manager_context(callback.from_user)
        if not bot_row or not admin:
            await callback.answer("دسترسی ندارید.", show_alert=True)
            return
        action = callback.data.split(":", 1)[1]
        async with SessionLocal() as db:
            if action == "dashboard":
                customers = int(await db.scalar(
                    select(func.count(Customer.id)).where(Customer.admin_id == admin.id)
                ) or 0)
                orders = int(await db.scalar(
                    select(func.count(Order.id)).where(Order.admin_id == admin.id)
                ) or 0)
                pending = int(await db.scalar(
                    select(func.count(Payment.id)).where(
                        Payment.admin_id == admin.id,
                        Payment.status == PaymentStatus.AWAITING_REVIEW,
                    )
                ) or 0)
                wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == admin.id))
                await callback.message.answer(
                    brand_title(
                        "داشبورد نماینده",
                        f"👥 مشتری‌ها: <b>{customers}</b>\n"
                        f"📦 سفارش‌ها: <b>{orders}</b>\n"
                        f"🧾 رسیدهای در انتظار: <b>{pending}</b>\n"
                        f"👛 کیف پول: <b>{money_text(wallet.balance_toman if wallet else 0)}</b>",
                    ),
                    parse_mode="HTML",
                    reply_markup=manager_menu(),
                )
            elif action == "wallet":
                wallet = await db.scalar(select(Wallet).where(Wallet.owner_user_id == admin.id))
                await callback.message.answer(
                    brand_title(
                        "کیف پول نماینده",
                        f"موجودی فعلی: <b>{money_text(wallet.balance_toman if wallet else 0)}</b>",
                    ),
                    parse_mode="HTML",
                    reply_markup=manager_menu(),
                )
            elif action == "orders":
                rows = (
                    await db.execute(
                        select(Order)
                        .where(Order.admin_id == admin.id)
                        .order_by(Order.created_at.desc())
                        .limit(10)
                    )
                ).scalars().all()
                lines = [brand_title("۱۰ سفارش اخیر")]
                for order in rows:
                    lines.append(
                        f"\n• {str(order.id)[:8]} · {status_text(order.status)}\n"
                        f"{money_text(order.retail_amount_toman)} · "
                        f"{Decimal(order.quota_bytes) / Decimal(1024**3):.0f} GB"
                    )
                await callback.message.answer(
                    "\n".join(lines) if rows else "سفارشی وجود ندارد.",
                    parse_mode="HTML",
                    reply_markup=manager_menu(),
                )
            elif action == "pending":
                rows = (
                    await db.execute(
                        select(Payment)
                        .where(
                            Payment.admin_id == admin.id,
                            Payment.status == PaymentStatus.AWAITING_REVIEW,
                        )
                        .order_by(Payment.created_at.asc())
                        .limit(10)
                    )
                ).scalars().all()
                if not rows:
                    await callback.message.answer("✅ رسید منتظری وجود ندارد.", reply_markup=manager_menu())
                for payment in rows:
                    purpose = (payment.meta or {}).get("purpose")
                    if purpose not in {"order_card", "customer_wallet_topup"}:
                        continue
                    kb = InlineKeyboardBuilder()
                    kb.button(text="✅ تأیید", callback_data=f"review:yes:{payment.id}")
                    kb.button(text="❌ رد", callback_data=f"review:no:{payment.id}")
                    kb.adjust(2)
                    await callback.message.answer(
                        "🧾 <b>رسید منتظر</b>\n"
                        f"مبلغ: {money_text(payment.amount_toman)}\n"
                        f"نوع: {purpose_text(purpose)}\n"
                        f"شناسه: {str(payment.id)[:8]}",
                        parse_mode="HTML",
                        reply_markup=kb.as_markup(),
                    )
        await callback.answer()

    @router.callback_query(F.data.startswith("review:"))
    async def manager_review(callback: CallbackQuery):
        from datetime import datetime, timezone

        bot_row, admin = await manager_context(callback.from_user)
        if not bot_row or not admin:
            await callback.answer("دسترسی ندارید.", show_alert=True)
            return
        try:
            _, decision, raw_id = callback.data.split(":", 2)
            payment_id = uuid.UUID(raw_id)
        except Exception:
            await callback.answer("شناسه نامعتبر است.", show_alert=True)
            return

        async with SessionLocal() as db:
            payment = await db.scalar(
                select(Payment).where(
                    Payment.id == payment_id,
                    Payment.admin_id == admin.id,
                ).with_for_update()
            )
            if not payment or payment.status != PaymentStatus.AWAITING_REVIEW:
                await callback.answer("این پرداخت قبلاً بررسی شده است.", show_alert=True)
                return
            purpose = (payment.meta or {}).get("purpose")
            approved = decision == "yes"

            try:
                if approved and purpose == "order_card":
                    order = await db.scalar(
                        select(Order).where(Order.id == payment.order_id).with_for_update()
                    )
                    if not order or order.admin_id != admin.id or order.admin_id != payment.admin_id:
                        raise ValueError("order ownership mismatch")
                    payment.status = PaymentStatus.PAID
                    order.status = OrderStatus.PAID
                    client = await provision_paid_order(db, order.id)
                    payment.provider_reference = str(client.id)
                elif approved and purpose == "customer_wallet_topup":
                    if not payment.customer_id:
                        raise ValueError("customer missing")
                    customer = await db.scalar(
                        select(Customer).where(
                            Customer.id == payment.customer_id,
                            Customer.admin_id == admin.id,
                        )
                    )
                    if not customer:
                        raise ValueError("customer ownership mismatch")
                    txn = await apply_customer_wallet_transaction(
                        db,
                        customer_id=payment.customer_id,
                        amount_toman=payment.amount_toman,
                        txn_type="card_topup",
                        idempotency_key=f"payment:{payment.id}",
                        reference_type="payment",
                        reference_id=str(payment.id),
                        description="تأیید پرداخت از پنل مدیریت ربات",
                    )
                    payment.status = PaymentStatus.PAID
                    payment.provider_reference = str(txn.id)
                elif approved:
                    raise ValueError("این نوع پرداخت از ربات قابل تأیید نیست")
                else:
                    payment.status = PaymentStatus.REJECTED
                    if payment.order_id:
                        order = await db.scalar(select(Order).where(Order.id == payment.order_id))
                        if order and order.status == OrderStatus.PENDING:
                            order.status = OrderStatus.CANCELLED

                payment.reviewed_at = datetime.now(timezone.utc)
                payment.reviewed_by = admin.id
                await db.commit()
                await callback.message.edit_text(
                    "✅ پرداخت تأیید شد." if approved else "❌ پرداخت رد شد."
                )
                await callback.answer()
            except Exception as exc:
                await db.rollback()
                await callback.answer(user_error_text(exc), show_alert=True)

    @router.message(CommandStart())
    @router.message(Command("menu"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        bot_row, customer = await get_context(message.from_user)
        if not bot_row:
            await message.answer("این ربات غیرفعال است.")
            return
        await message.answer(
            brand_title(
                "مرکز فروش",
                f"سلام {message.from_user.first_name or 'کاربر'} 👋\n"
                "خرید سرویس، کیف پول و سرویس‌های شما از همین منو در دسترس است.",
            ),
            parse_mode="HTML",
            reply_markup=main_menu(),
        )

    @router.callback_query(F.data == "main:home")
    async def home(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        await callback.message.edit_text(
            brand_title("منوی اصلی", "گزینه موردنظر را انتخاب کنید."),
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        await callback.answer()

    @router.callback_query(F.data == "main:buy")
    async def buy(callback: CallbackQuery, state: FSMContext):
        await callback.answer()
        await show_plans(callback.message, state, callback.from_user)

    @router.callback_query(F.data.startswith("plan:"))
    async def choose_plan(callback: CallbackQuery, state: FSMContext):
        try:
            plan_id = uuid.UUID(callback.data.split(":", 1)[1])
        except Exception:
            await callback.answer("پلن نامعتبر است.", show_alert=True)
            return
        await show_quota(callback, state, plan_id)

    @router.callback_query(F.data.startswith("quota:"))
    async def choose_quota(callback: CallbackQuery, state: FSMContext):
        value = callback.data.split(":", 1)[1]
        if value == "custom":
            await state.set_state(SaleFlow.custom_quota)
            await callback.message.answer(
                brand_title("حجم دلخواه", "حجم را به گیگ وارد کنید؛ مثال: <b>75</b>"),
                parse_mode="HTML",
            )
            await callback.answer()
            return
        await state.update_data(quota_gib=value)
        await callback.answer()
        await show_duration(callback.message, state)

    @router.message(SaleFlow.custom_quota, F.text)
    async def custom_quota(message: Message, state: FSMContext):
        try:
            quota = Decimal(message.text.strip())
        except (InvalidOperation, AttributeError):
            await message.answer("یک عدد معتبر وارد کنید.")
            return
        data = await state.get_data()
        async with SessionLocal() as db:
            plan = await db.scalar(select(Plan).where(Plan.id == uuid.UUID(data["plan_id"])))
        if (
            quota <= 0
            or (plan.min_quota_gib is not None and quota < Decimal(plan.min_quota_gib))
            or (plan.max_quota_gib is not None and quota > Decimal(plan.max_quota_gib))
        ):
            await message.answer("حجم واردشده خارج از محدوده مجاز این پلن است.")
            return
        await state.update_data(quota_gib=str(quota))
        await state.set_state(None)
        await show_duration(message, state)

    @router.callback_query(F.data.startswith("duration:"))
    async def choose_duration(callback: CallbackQuery, state: FSMContext):
        value = callback.data.split(":", 1)[1]
        if value == "custom":
            await state.set_state(SaleFlow.custom_duration)
            await callback.message.answer(
                brand_title("مدت دلخواه", "تعداد روز را وارد کنید."),
                parse_mode="HTML",
            )
            await callback.answer()
            return
        await state.update_data(duration_days=None if value == "0" else int(value))
        await state.set_state(None)
        await callback.answer()
        await show_checkout(callback.message, state, callback.from_user)

    @router.message(SaleFlow.custom_duration, F.text)
    async def custom_duration(message: Message, state: FSMContext):
        try:
            days = int(message.text.strip())
        except Exception:
            await message.answer("تعداد روز معتبر وارد کنید.")
            return
        data = await state.get_data()
        async with SessionLocal() as db:
            plan = await db.scalar(select(Plan).where(Plan.id == uuid.UUID(data["plan_id"])))
        if days <= 0 or (plan.max_duration_days is not None and days > plan.max_duration_days):
            await message.answer("مدت واردشده خارج از محدوده مجاز است.")
            return
        await state.update_data(duration_days=days)
        await state.set_state(None)
        await show_checkout(message, state, message.from_user)

    @router.callback_query(F.data.startswith("pay:"))
    async def pay(callback: CallbackQuery, state: FSMContext):
        method_name = callback.data.split(":", 1)[1]
        method_map = {
            "wallet": PaymentMethod.CUSTOMER_WALLET,
            "card": PaymentMethod.CARD_TO_CARD,
            "gateway": PaymentMethod.GATEWAY,
        }
        method = method_map.get(method_name)
        if method is None:
            await callback.answer("روش پرداخت نامعتبر است.", show_alert=True)
            return

        data = await state.get_data()
        if not {"plan_id", "quota_gib"}.issubset(data):
            await callback.answer("جلسه خرید منقضی شده؛ دوباره شروع کنید.", show_alert=True)
            return

        bot_row, _ = await get_context(callback.from_user)
        async with SessionLocal() as db:
            bot_row = await db.scalar(select(TelegramBot).where(TelegramBot.id == bot_id))
            customer = await resolve_customer(db, bot_row=bot_row, tg_user=callback.from_user)
            try:
                order = await create_order(
                    db,
                    admin_id=bot_row.admin_id,
                    customer_id=customer.id,
                    plan_id=uuid.UUID(data["plan_id"]),
                    quota_gib=Decimal(str(data["quota_gib"])),
                    duration_days=data.get("duration_days"),
                    payment_method=method,
                )
                if method == PaymentMethod.CUSTOMER_WALLET:
                    payment, client = await pay_order_from_customer_wallet(db, order)
                    await db.commit()
                    await state.clear()
                    await callback.message.answer(
                        "✅ پرداخت و ساخت سرویس با موفقیت انجام شد.\n\n"
                        f"🔗 لینک اشتراک:\n{client.subscription_url or 'لینک از PasarGuard دریافت نشد.'}",
                        reply_markup=main_menu(),
                    )
                elif method == PaymentMethod.CARD_TO_CARD:
                    payment = await create_card_order_payment(db, order)
                    card = await default_bank_card(db, bot_row.admin_id)
                    await db.commit()
                    await state.update_data(payment_id=str(payment.id))
                    await state.set_state(SaleFlow.waiting_order_receipt)
                    await callback.message.answer(
                        "💳 مبلغ را کارت‌به‌کارت کنید و تصویر رسید را همینجا ارسال کنید.\n\n"
                        f"مبلغ: {money_text(payment.amount_toman)}\n"
                        f"شماره کارت: {card.card_number if card else '-'}\n"
                        f"به نام: {(card.card_holder_name if card else None) or '-'}\n"
                        f"{(card.instructions if card else None) or ''}"
                    )
                else:
                    payment, gateway = await create_gateway_order_payment(db, order)
                    await db.commit()
                    kb = InlineKeyboardBuilder()
                    kb.row(InlineKeyboardButton(text="💳 پرداخت آنلاین", url=gateway.redirect_url))
                    kb.button(text="✅ بررسی نتیجه پرداخت", callback_data=f"check:{payment.id}")
                    await callback.message.answer(
                        f"مبلغ قابل پرداخت: {money_text(payment.amount_toman)}",
                        reply_markup=kb.as_markup(),
                    )
                await callback.answer()
            except Exception as exc:
                await db.rollback()
                logger.warning("Checkout failed bot=%s user=%s: %s", bot_id, callback.from_user.id, exc)
                detail = str(exc)
                if "insufficient" in detail.lower():
                    detail = "موجودی کیف پول شما کافی نیست."
                await callback.answer(detail[:180] or "پرداخت انجام نشد.", show_alert=True)

    @router.message(SaleFlow.waiting_order_receipt)
    async def order_receipt(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        payment_id = data.get("payment_id")
        if not payment_id:
            await state.clear()
            await message.answer("جلسه پرداخت منقضی شده است.", reply_markup=main_menu())
            return
        try:
            raw, filename, mime = await receipt_bytes(message, bot)
            async with SessionLocal() as db:
                payment = await db.scalar(
                    select(Payment).where(Payment.id == uuid.UUID(payment_id)).with_for_update()
                )
                bot_row = await db.scalar(select(TelegramBot).where(TelegramBot.id == bot_id))
                if not payment or payment.admin_id != bot_row.admin_id:
                    raise ValueError("پرداخت پیدا نشد.")
                await store_receipt(db, payment=payment, raw=raw, filename=filename, mime_type=mime)
                await add_notification(
                    db,
                    user_id=payment.admin_id,
                    kind="payment_receipt",
                    title="رسید جدید مشتری",
                    message=f"رسید سفارش {payment.order_id} منتظر بررسی است.",
                    entity_type="payment",
                    entity_id=str(payment.id),
                    dedupe_key=f"receipt:{payment.id}",
                )
                await db.commit()
                await notify_admin(
                    bot,
                    payment.admin_id,
                    f"🧾 رسید جدید برای پرداخت {payment.id}\nمبلغ: {money_text(payment.amount_toman)}",
                )
            await state.clear()
            kb = InlineKeyboardBuilder()
            kb.button(text="🔄 بررسی وضعیت سفارش", callback_data=f"check:{payment_id}")
            kb.button(text="🏠 منوی اصلی", callback_data="main:home")
            kb.adjust(1)
            await message.answer(
                "✅ رسید ثبت شد. پس از تأیید نماینده، سرویس به‌صورت خودکار ساخته می‌شود.",
                reply_markup=kb.as_markup(),
            )
        except Exception as exc:
            await message.answer(user_error_text(exc))

    @router.callback_query(F.data.startswith("check:"))
    async def check_payment(callback: CallbackQuery):
        try:
            payment_id = uuid.UUID(callback.data.split(":", 1)[1])
        except Exception:
            await callback.answer("شناسه پرداخت نامعتبر است.", show_alert=True)
            return
        bot_row, customer = await get_context(callback.from_user)
        async with SessionLocal() as db:
            payment = await db.scalar(
                select(Payment).where(
                    Payment.id == payment_id,
                    Payment.admin_id == bot_row.admin_id,
                    Payment.customer_id == customer.id,
                )
            )
            if not payment:
                await callback.answer("پرداخت پیدا نشد.", show_alert=True)
                return
            if payment.status != PaymentStatus.PAID:
                await callback.answer(
                    f"وضعیت فعلی: {status_text(payment.status)}",
                    show_alert=True,
                )
                return
            if payment.order_id:
                order = await db.scalar(select(Order).where(Order.id == payment.order_id))
                if order and order.client_id:
                    client = await db.scalar(select(Client).where(Client.id == order.client_id))
                    await callback.message.answer(
                        "✅ پرداخت تأیید شده است.\n\n"
                        f"🔗 لینک اشتراک:\n{client.subscription_url or '-'}",
                        reply_markup=main_menu(),
                    )
                    await callback.answer()
                    return
            await callback.answer("پرداخت تأیید شده است.", show_alert=True)

    @router.callback_query(F.data == "main:wallet")
    async def wallet(callback: CallbackQuery):
        _, customer = await get_context(callback.from_user)
        await callback.message.edit_text(
            f"💰 موجودی کیف پول شما:\n<b>{money_text(customer.wallet_balance_toman)}</b>",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        await callback.answer()

    @router.callback_query(F.data == "main:services")
    async def services(callback: CallbackQuery):
        bot_row, customer = await get_context(callback.from_user)
        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(Order, Client)
                    .join(Client, Client.id == Order.client_id)
                    .where(
                        Order.admin_id == bot_row.admin_id,
                        Order.customer_id == customer.id,
                        Order.status == OrderStatus.PROVISIONED,
                    )
                    .order_by(Order.created_at.desc())
                    .limit(10)
                )
            ).all()
        if not rows:
            await callback.message.answer("هنوز سرویس فعالی ندارید.", reply_markup=main_menu())
        else:
            text = [brand_title("سرویس‌های شما")]
            for order, client in rows:
                text.append(
                    f"\n• {client.username}\n"
                    f"حجم: {Decimal(order.quota_bytes) / Decimal(1024**3):.0f} GB\n"
                    f"وضعیت: {status_text(client.status)}\n"
                    f"لینک: {client.subscription_url or '-'}"
                )
            await callback.message.answer("\n".join(text), parse_mode="HTML", reply_markup=main_menu())
        await callback.answer()

    @router.callback_query(F.data == "main:topup")
    async def topup_start(callback: CallbackQuery, state: FSMContext):
        await state.set_state(SaleFlow.wallet_topup_amount)
        await callback.message.answer("مبلغ شارژ کیف پول را به تومان وارد کنید؛ مثلاً 100000")
        await callback.answer()

    @router.message(SaleFlow.wallet_topup_amount, F.text)
    async def topup_amount(message: Message, state: FSMContext):
        try:
            amount = Decimal(message.text.replace(",", "").strip())
        except Exception:
            await message.answer("مبلغ معتبر وارد کنید.")
            return
        if amount < 1000:
            await message.answer("حداقل مبلغ شارژ ۱٬۰۰۰ تومان است.")
            return
        bot_row, _ = await get_context(message.from_user)
        async with SessionLocal() as db:
            profile = await db.scalar(
                select(PaymentProfile).where(PaymentProfile.owner_user_id == bot_row.admin_id)
            )
            card = await default_bank_card(db, bot_row.admin_id)
        await state.update_data(topup_amount=str(amount))
        kb = InlineKeyboardBuilder()
        if bot_row.card_to_card_enabled and card:
            kb.button(text="💳 کارت به کارت", callback_data="topup:card")
        if bot_row.gateway_enabled and profile and profile.gateway_enabled:
            kb.button(text="🌐 درگاه پرداخت", callback_data="topup:gateway")
        kb.adjust(1)
        await state.set_state(None)
        await message.answer(
            f"مبلغ شارژ: {money_text(amount)}\nروش پرداخت را انتخاب کنید:",
            reply_markup=kb.as_markup(),
        )

    @router.callback_query(F.data.startswith("topup:"))
    async def topup_method(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if "topup_amount" not in data:
            await callback.answer("جلسه شارژ منقضی شده است.", show_alert=True)
            return
        amount = Decimal(data["topup_amount"])
        bot_row, customer = await get_context(callback.from_user)
        method = callback.data.split(":", 1)[1]
        async with SessionLocal() as db:
            bot_row = await db.scalar(select(TelegramBot).where(TelegramBot.id == bot_id))
            customer = await resolve_customer(db, bot_row=bot_row, tg_user=callback.from_user)
            try:
                if method == "card":
                    payment = await create_customer_card_topup(
                        db, customer=customer, amount_toman=amount
                    )
                    card = await default_bank_card(db, bot_row.admin_id)
                    await db.commit()
                    await state.update_data(payment_id=str(payment.id))
                    await state.set_state(SaleFlow.wallet_topup_receipt)
                    await callback.message.answer(
                        "مبلغ را واریز و رسید را ارسال کنید.\n\n"
                        f"مبلغ: {money_text(amount)}\n"
                        f"شماره کارت: {card.card_number if card else '-'}\n"
                        f"به نام: {(card.card_holder_name if card else None) or '-'}"
                    )
                elif method == "gateway":
                    payment, gateway = await create_customer_gateway_topup(
                        db, customer=customer, amount_toman=amount
                    )
                    await db.commit()
                    kb = InlineKeyboardBuilder()
                    kb.row(InlineKeyboardButton(text="💳 پرداخت آنلاین", url=gateway.redirect_url))
                    kb.button(text="✅ بررسی شارژ", callback_data=f"check:{payment.id}")
                    await callback.message.answer(
                        f"برای شارژ {money_text(amount)} وارد درگاه شوید.",
                        reply_markup=kb.as_markup(),
                    )
                else:
                    raise ValueError("روش پرداخت نامعتبر است.")
                await callback.answer()
            except Exception as exc:
                await db.rollback()
                await callback.answer(user_error_text(exc), show_alert=True)

    @router.message(SaleFlow.wallet_topup_receipt)
    async def wallet_receipt(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        payment_id = data.get("payment_id")
        if not payment_id:
            await state.clear()
            await message.answer("جلسه شارژ منقضی شده است.", reply_markup=main_menu())
            return
        try:
            raw, filename, mime = await receipt_bytes(message, bot)
            async with SessionLocal() as db:
                payment = await db.scalar(
                    select(Payment).where(Payment.id == uuid.UUID(payment_id)).with_for_update()
                )
                bot_row = await db.scalar(select(TelegramBot).where(TelegramBot.id == bot_id))
                if not payment or payment.admin_id != bot_row.admin_id:
                    raise ValueError("پرداخت پیدا نشد.")
                await store_receipt(db, payment=payment, raw=raw, filename=filename, mime_type=mime)
                await add_notification(
                    db,
                    user_id=payment.admin_id,
                    kind="wallet_topup_receipt",
                    title="رسید شارژ کیف پول",
                    message=f"رسید شارژ مشتری به مبلغ {money_text(payment.amount_toman)} منتظر بررسی است.",
                    entity_type="payment",
                    entity_id=str(payment.id),
                    dedupe_key=f"receipt:{payment.id}",
                )
                await db.commit()
                await notify_admin(
                    bot,
                    payment.admin_id,
                    f"💰 رسید شارژ کیف پول مشتری\nمبلغ: {money_text(payment.amount_toman)}",
                )
            await state.clear()
            kb = InlineKeyboardBuilder()
            kb.button(text="🔄 بررسی وضعیت شارژ", callback_data=f"check:{payment_id}")
            kb.button(text="🏠 منوی اصلی", callback_data="main:home")
            kb.adjust(1)
            await message.answer(
                "✅ رسید شارژ ثبت شد و منتظر تأیید نماینده است.",
                reply_markup=kb.as_markup(),
            )
        except Exception as exc:
            await message.answer(user_error_text(exc))

    dp.include_router(router)
    return dp



BOT_RUNTIMES: dict[uuid.UUID, tuple[str, Bot, Dispatcher]] = {}
WEBHOOK_CONCURRENCY = max(1, min(int(os.getenv("TELEGRAM_WEBHOOK_RECONCILE_CONCURRENCY", "20")), 100))
QUEUE_BATCH_SIZE = max(1, min(int(os.getenv("TELEGRAM_QUEUE_BATCH_SIZE", "50")), 200))
CONSUMER_NAME = f"{socket.gethostname()}-{os.getpid()}"


async def close_runtime(bot_id: uuid.UUID) -> None:
    runtime = BOT_RUNTIMES.pop(bot_id, None)
    if not runtime:
        return
    _, bot, dp = runtime
    with suppress(Exception):
        await dp.storage.close()
    with suppress(Exception):
        await bot.session.close()


async def load_runtime(bot_id: uuid.UUID) -> tuple[Bot, Dispatcher] | None:
    async with SessionLocal() as db:
        row = await db.scalar(
            select(TelegramBot).where(
                TelegramBot.id == bot_id,
                TelegramBot.enabled.is_(True),
            )
        )
        if not row:
            await close_runtime(bot_id)
            return None
        encrypted_token = row.encrypted_token

    cached = BOT_RUNTIMES.get(bot_id)
    if cached and cached[0] == encrypted_token:
        return cached[1], cached[2]

    await close_runtime(bot_id)
    bot = Bot(token=decrypt_secret(encrypted_token))
    dp = build_dispatcher(bot_id)
    BOT_RUNTIMES[bot_id] = (encrypted_token, bot, dp)
    return bot, dp


async def configure_webhook(bot_id: uuid.UUID, encrypted_token: str, enabled: bool) -> None:
    bot = Bot(token=decrypt_secret(encrypted_token))
    try:
        if enabled:
            await bot.set_webhook(
                url=telegram_webhook_url(bot_id),
                secret_token=telegram_webhook_secret(bot_id),
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=False,
                max_connections=100,
            )
            me = await bot.get_me()
            logger.info("Webhook enabled bot=@%s id=%s", me.username, bot_id)
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            logger.info("Webhook removed bot_id=%s", bot_id)
            await close_runtime(bot_id)
    finally:
        with suppress(Exception):
            await bot.session.close()


async def reconcile_bot(bot_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        row = await db.scalar(select(TelegramBot).where(TelegramBot.id == bot_id))
        if not row:
            await close_runtime(bot_id)
            return
        encrypted_token = row.encrypted_token
        enabled = bool(row.enabled)

    cached = BOT_RUNTIMES.get(bot_id)
    if cached and cached[0] != encrypted_token:
        await close_runtime(bot_id)
    await configure_webhook(bot_id, encrypted_token, enabled)


async def reconcile_all_bots() -> None:
    logger.info("Reconciling existing Telegram bots to webhook mode")
    last_id: uuid.UUID | None = None
    semaphore = asyncio.Semaphore(WEBHOOK_CONCURRENCY)

    async def one(bot_id: uuid.UUID, encrypted_token: str, enabled: bool):
        async with semaphore:
            try:
                await configure_webhook(bot_id, encrypted_token, enabled)
            except Exception:
                logger.exception("Webhook reconciliation failed bot_id=%s", bot_id)

    while True:
        async with SessionLocal() as db:
            stmt = select(
                TelegramBot.id,
                TelegramBot.encrypted_token,
                TelegramBot.enabled,
            ).order_by(TelegramBot.id).limit(500)
            if last_id is not None:
                stmt = stmt.where(TelegramBot.id > last_id)
            rows = (await db.execute(stmt)).all()

        if not rows:
            break

        for offset in range(0, len(rows), WEBHOOK_CONCURRENCY):
            chunk = rows[offset : offset + WEBHOOK_CONCURRENCY]
            await asyncio.gather(*(one(bot_id, token, enabled) for bot_id, token, enabled in chunk))

        last_id = rows[-1][0]

    logger.info("Telegram webhook reconciliation complete")


async def ensure_stream_groups(redis: Redis) -> None:
    for stream, group in (
        (TELEGRAM_UPDATE_STREAM, TELEGRAM_UPDATE_GROUP),
        (TELEGRAM_CONTROL_STREAM, TELEGRAM_CONTROL_GROUP),
    ):
        try:
            await redis.xgroup_create(stream, group, id="0-0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise


async def handle_update_message(
    redis: Redis,
    message_id: str,
    fields: dict[str, str],
) -> None:
    try:
        bot_id = uuid.UUID(fields["bot_id"])
        update_id = int(fields["update_id"])
        payload = json.loads(fields["payload"])
    except Exception:
        logger.exception("Discarding malformed Telegram queue message id=%s", message_id)
        await redis.xack(TELEGRAM_UPDATE_STREAM, TELEGRAM_UPDATE_GROUP, message_id)
        return

    done_key = telegram_done_key(bot_id, update_id)
    if await redis.exists(done_key):
        await redis.xack(TELEGRAM_UPDATE_STREAM, TELEGRAM_UPDATE_GROUP, message_id)
        return

    lock_key = telegram_processing_key(bot_id, update_id)
    acquired = await redis.set(
        lock_key,
        CONSUMER_NAME,
        nx=True,
        ex=TELEGRAM_PROCESSING_TTL_SECONDS,
    )
    if not acquired:
        return

    try:
        runtime = await load_runtime(bot_id)
        if runtime is None:
            # Disabled/deleted bots should not keep retrying stale updates.
            await redis.set(done_key, "disabled", ex=TELEGRAM_DONE_TTL_SECONDS)
            await redis.xack(TELEGRAM_UPDATE_STREAM, TELEGRAM_UPDATE_GROUP, message_id)
            return

        bot, dp = runtime
        update = Update.model_validate(payload, context={"bot": bot})
        await dp.feed_update(bot, update)

        await redis.set(done_key, "1", ex=TELEGRAM_DONE_TTL_SECONDS)
        await redis.xack(TELEGRAM_UPDATE_STREAM, TELEGRAM_UPDATE_GROUP, message_id)
    except Exception:
        logger.exception(
            "Telegram update failed bot_id=%s update_id=%s stream_id=%s",
            bot_id,
            update_id,
            message_id,
        )
        # Leave the stream entry pending. xautoclaim will retry it.
    finally:
        with suppress(Exception):
            await redis.delete(lock_key)


async def recover_pending_updates(redis: Redis) -> None:
    start_id = "0-0"
    for _ in range(4):
        try:
            result = await redis.xautoclaim(
                TELEGRAM_UPDATE_STREAM,
                TELEGRAM_UPDATE_GROUP,
                CONSUMER_NAME,
                min_idle_time=30_000,
                start_id=start_id,
                count=QUEUE_BATCH_SIZE,
            )
        except Exception:
            logger.exception("Failed to reclaim pending Telegram updates")
            return

        if not result:
            return

        start_id = result[0]
        messages = result[1] if len(result) > 1 else []
        if not messages:
            return

        for message_id, fields in messages:
            await handle_update_message(redis, message_id, fields)

        if start_id == "0-0":
            return


async def consume_updates(redis: Redis) -> None:
    while True:
        try:
            await recover_pending_updates(redis)
            response = await redis.xreadgroup(
                TELEGRAM_UPDATE_GROUP,
                CONSUMER_NAME,
                {TELEGRAM_UPDATE_STREAM: ">"},
                count=QUEUE_BATCH_SIZE,
                block=5_000,
            )
            for _, messages in response or []:
                for message_id, fields in messages:
                    await handle_update_message(redis, message_id, fields)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram update consumer failed")
            await asyncio.sleep(1)


async def consume_control(redis: Redis) -> None:
    while True:
        try:
            response = await redis.xreadgroup(
                TELEGRAM_CONTROL_GROUP,
                CONSUMER_NAME,
                {TELEGRAM_CONTROL_STREAM: ">"},
                count=25,
                block=5_000,
            )
            for _, messages in response or []:
                for message_id, fields in messages:
                    try:
                        bot_id = uuid.UUID(fields["bot_id"])
                        await reconcile_bot(bot_id)
                        await redis.xack(
                            TELEGRAM_CONTROL_STREAM,
                            TELEGRAM_CONTROL_GROUP,
                            message_id,
                        )
                    except Exception:
                        logger.exception(
                            "Telegram bot reconcile event failed id=%s",
                            fields.get("bot_id"),
                        )
                        # Keep it pending for the periodic full reconciliation.
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram control consumer failed")
            await asyncio.sleep(1)


async def periodic_reconcile() -> None:
    # Safety net for missed control messages. This is intentionally infrequent;
    # normal bot changes are pushed through the Redis control stream immediately.
    while True:
        await asyncio.sleep(15 * 60)
        try:
            await reconcile_all_bots()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Periodic Telegram webhook reconciliation failed")


async def main():
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    tasks: list[asyncio.Task] = []
    try:
        await redis.ping()
        await ensure_stream_groups(redis)
        await reconcile_all_bots()

        logger.info(
            "PRIMEVPN Telegram webhook worker started consumer=%s queue_batch=%d",
            CONSUMER_NAME,
            QUEUE_BATCH_SIZE,
        )
        tasks = [
            asyncio.create_task(consume_updates(redis)),
            asyncio.create_task(consume_control(redis)),
            asyncio.create_task(periodic_reconcile()),
        ]
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        for bot_id in list(BOT_RUNTIMES):
            await close_runtime(bot_id)
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
