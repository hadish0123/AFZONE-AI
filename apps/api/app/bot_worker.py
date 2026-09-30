import asyncio
import base64
import hashlib
import logging
import uuid
from contextlib import suppress
from decimal import Decimal, InvalidOperation

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret
from app.db import SessionLocal
from app.models import (
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
    TelegramBot,
    User,
)
from app.services.commerce import (
    create_card_order_payment,
    create_customer_card_topup,
    create_customer_gateway_topup,
    create_gateway_order_payment,
    create_order,
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
    storage = RedisStorage.from_url(settings.redis_url, state_ttl=3600, data_ttl=3600)
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
                    select(AdminPlan, Plan)
                    .join(Plan, Plan.id == AdminPlan.plan_id)
                    .where(
                        AdminPlan.admin_id == bot_row.admin_id,
                        AdminPlan.enabled.is_(True),
                        AdminPlan.bot_visible.is_(True),
                        Plan.enabled.is_(True),
                    )
                    .order_by(Plan.name)
                )
            ).all()
        if not rows:
            await target.answer("در حال حاضر پلن فعالی برای فروش وجود ندارد.")
            return
        kb = InlineKeyboardBuilder()
        for admin_plan, plan in rows:
            kb.button(
                text=f"{plan.name} · {money_text(admin_plan.retail_price_per_gib_toman)}/GB",
                callback_data=f"plan:{plan.id}",
            )
        kb.button(text="↩️ منوی اصلی", callback_data="main:home")
        kb.adjust(1)
        await state.clear()
        await target.answer("پلن موردنظر را انتخاب کنید:", reply_markup=kb.as_markup())

    async def show_quota(callback: CallbackQuery, state: FSMContext, plan_id: uuid.UUID):
        bot_row, _ = await get_context(callback.from_user)
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(AdminPlan, Plan)
                    .join(Plan, Plan.id == AdminPlan.plan_id)
                    .where(
                        AdminPlan.admin_id == bot_row.admin_id,
                        AdminPlan.plan_id == plan_id,
                        AdminPlan.enabled.is_(True),
                        Plan.enabled.is_(True),
                    )
                )
            ).first()
        if not row:
            await callback.answer("این پلن دیگر در دسترس نیست.", show_alert=True)
            return
        _, plan = row
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
        await target.answer("مدت سرویس را انتخاب کنید:", reply_markup=kb.as_markup())

    async def show_checkout(target, state: FSMContext, tg_user):
        data = await state.get_data()
        bot_row, customer = await get_context(tg_user)
        plan_id = uuid.UUID(data["plan_id"])
        quota = Decimal(str(data["quota_gib"]))
        duration = data.get("duration_days")

        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(AdminPlan, Plan)
                    .join(Plan, Plan.id == AdminPlan.plan_id)
                    .where(
                        AdminPlan.admin_id == bot_row.admin_id,
                        AdminPlan.plan_id == plan_id,
                        AdminPlan.enabled.is_(True),
                        Plan.enabled.is_(True),
                    )
                )
            ).first()
            profile = await db.scalar(
                select(PaymentProfile).where(PaymentProfile.owner_user_id == bot_row.admin_id)
            )
        if not row:
            await target.answer("پلن در دسترس نیست.")
            return
        admin_plan, plan = row
        amount = Decimal(admin_plan.retail_price_per_gib_toman) * quota

        text = (
            f"🧾 <b>پیش‌فاکتور</b>\n\n"
            f"پلن: {plan.name}\n"
            f"حجم: {quota.normalize()} GB\n"
            f"مدت: {'بدون انقضا' if not duration else str(duration) + ' روز'}\n"
            f"مبلغ: <b>{money_text(amount)}</b>\n"
            f"موجودی کیف پول: {money_text(customer.wallet_balance_toman)}"
        )
        kb = InlineKeyboardBuilder()
        if bot_row.customer_wallet_enabled:
            kb.button(text="💰 پرداخت از کیف پول", callback_data="pay:wallet")
        if bot_row.card_to_card_enabled and profile and profile.card_to_card_enabled and profile.card_number:
            kb.button(text="💳 کارت به کارت", callback_data="pay:card")
        if bot_row.gateway_enabled and profile and profile.gateway_enabled:
            kb.button(text="🌐 درگاه پرداخت", callback_data="pay:gateway")
        kb.button(text="↩️ تغییر پلن", callback_data="main:buy")
        kb.adjust(1)
        await target.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

    @router.message(CommandStart())
    @router.message(Command("menu"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        bot_row, customer = await get_context(message.from_user)
        if not bot_row:
            await message.answer("این ربات غیرفعال است.")
            return
        await message.answer(
            f"سلام {message.from_user.first_name or ''} 👋\n"
            "به فروشگاه PRIMEVPN خوش آمدید. یکی از گزینه‌ها را انتخاب کنید.",
            reply_markup=main_menu(),
        )

    @router.callback_query(F.data == "main:home")
    async def home(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        await callback.message.edit_text("منوی اصلی:", reply_markup=main_menu())
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
            await callback.message.answer("حجم دلخواه را به گیگ وارد کنید؛ مثلاً 75")
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
            await callback.message.answer("مدت دلخواه را به روز وارد کنید.")
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
                    profile = await db.scalar(
                        select(PaymentProfile).where(PaymentProfile.owner_user_id == bot_row.admin_id)
                    )
                    await db.commit()
                    await state.update_data(payment_id=str(payment.id))
                    await state.set_state(SaleFlow.waiting_order_receipt)
                    await callback.message.answer(
                        "💳 مبلغ را کارت‌به‌کارت کنید و تصویر رسید را همینجا ارسال کنید.\n\n"
                        f"مبلغ: {money_text(payment.amount_toman)}\n"
                        f"شماره کارت: {profile.card_number}\n"
                        f"به نام: {profile.card_holder_name or '-'}\n"
                        f"{profile.card_instructions or ''}"
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
            await message.answer(str(exc)[:300])

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
                    f"وضعیت فعلی: {payment.status.value}",
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
            text = ["📱 <b>سرویس‌های شما</b>"]
            for order, client in rows:
                text.append(
                    f"\n• {client.username}\n"
                    f"حجم: {Decimal(order.quota_bytes) / Decimal(1024**3):.0f} GB\n"
                    f"وضعیت: {client.status.value}\n"
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
        await state.update_data(topup_amount=str(amount))
        kb = InlineKeyboardBuilder()
        if bot_row.card_to_card_enabled and profile and profile.card_to_card_enabled and profile.card_number:
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
                    profile = await db.scalar(
                        select(PaymentProfile).where(PaymentProfile.owner_user_id == bot_row.admin_id)
                    )
                    await db.commit()
                    await state.update_data(payment_id=str(payment.id))
                    await state.set_state(SaleFlow.wallet_topup_receipt)
                    await callback.message.answer(
                        "مبلغ را واریز و رسید را ارسال کنید.\n\n"
                        f"مبلغ: {money_text(amount)}\n"
                        f"شماره کارت: {profile.card_number}\n"
                        f"به نام: {profile.card_holder_name or '-'}"
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
                await callback.answer(str(exc)[:180], show_alert=True)

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
            await message.answer(str(exc)[:300])

    dp.include_router(router)
    return dp


async def run_bot(bot_id: uuid.UUID, encrypted_token: str):
    token = decrypt_secret(encrypted_token)
    bot = Bot(token=token)
    dp = build_dispatcher(bot_id)
    try:
        me = await bot.get_me()
        logger.info("Starting Telegram bot @%s id=%s", me.username, bot_id)
        await dp.start_polling(
            bot,
            handle_signals=False,
            allowed_updates=dp.resolve_used_update_types(),
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Telegram bot crashed id=%s", bot_id)
    finally:
        with suppress(Exception):
            await dp.storage.close()
        with suppress(Exception):
            await bot.session.close()


async def enabled_bots():
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(TelegramBot).where(TelegramBot.enabled.is_(True))
            )
        ).scalars()
        return [(row.id, row.encrypted_token) for row in rows]


async def main():
    tasks: dict[uuid.UUID, tuple[str, asyncio.Task]] = {}
    logger.info("PRIMEVPN Telegram worker started")
    while True:
        try:
            current = dict(await enabled_bots())

            for bot_id, (token_snapshot, task) in list(tasks.items()):
                if bot_id not in current or current[bot_id] != token_snapshot or task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    tasks.pop(bot_id, None)

            for bot_id, encrypted_token in current.items():
                if bot_id not in tasks:
                    task = asyncio.create_task(run_bot(bot_id, encrypted_token))
                    tasks[bot_id] = (encrypted_token, task)

        except Exception:
            logger.exception("Telegram reconciliation failed")

        await asyncio.sleep(15)


if __name__ == "__main__":
    asyncio.run(main())
