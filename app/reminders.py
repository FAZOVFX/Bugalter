import asyncio
import logging
import os

from aiogram import Bot
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Order, SessionLocal
from app.formatting import debt_of, format_date, today_local
from app.handlers.views import client_card_text
from app.keyboards import event_check_keyboard
from app.logsafe import safe_db_message
from app.services import paid_sum

logger = logging.getLogger(__name__)


async def due_orders(session: AsyncSession) -> list[Order]:
    today = today_local()
    found = await session.scalars(
        select(Order).where(
            Order.payment_due_date.is_not(None),
            Order.payment_due_date <= today,
        )
    )
    ready: list[Order] = []
    for order in found:
        due = order.payment_due_date
        if due is None:
            continue
        sent = order.reminder_sent_on
        if sent is not None and sent >= due:
            continue
        paid = await paid_sum(session, order.id)
        if debt_of(order.total_price, paid) <= 0:
            continue
        ready.append(order)
    return ready


def reminder_text(order: Order, paid: object) -> str:
    return (
        "<b>Ogohlantirish</b>\n"
        f"{order.client_name} ning qarz sanasi keldi. Bugun pul berishi kerak.\n"
        f"Sana: {format_date(order.payment_due_date)}\n\n"
        f"{client_card_text(order, paid)}"
    )


async def due_event_orders(session: AsyncSession) -> list[Order]:
    today = today_local()
    found = await session.scalars(
        select(Order).where(
            Order.event_date.is_not(None),
            Order.event_date <= today,
            or_(
                Order.event_checked_on.is_(None),
                Order.event_checked_on < Order.event_date,
            ),
        )
    )
    return list(found)


def event_question(order: Order, paid: object) -> str:
    return (
        "<b>Bugungi xizmat</b>\n"
        "Xizmat kuni keldi. Nima bo'ldi, pul olindimi?\n\n"
        f"{client_card_text(order, paid)}\n\n"
        "To'liq, yarim yoki boshqa summani belgilang."
    )


async def send_event_questions(bot: Bot) -> None:
    admin_raw = os.getenv("ADMIN_ID", "").strip()
    if not admin_raw.isdigit():
        return
    admin_id = int(admin_raw)
    async with SessionLocal() as session:
        orders = await due_event_orders(session)
        for order in orders:
            paid = await paid_sum(session, order.id)
            try:
                await bot.send_message(
                    admin_id,
                    event_question(order, paid),
                    reply_markup=event_check_keyboard(order.id),
                )
            except Exception as exc:
                logger.exception("Xizmat so'rovi yuborilmadi: %s", safe_db_message(exc))
                continue
            order.event_checked_on = today_local()
        await session.commit()


async def send_due_reminders(bot: Bot) -> None:
    admin_raw = os.getenv("ADMIN_ID", "").strip()
    if not admin_raw.isdigit():
        return
    admin_id = int(admin_raw)
    async with SessionLocal() as session:
        orders = await due_orders(session)
        for order in orders:
            paid = await paid_sum(session, order.id)
            try:
                await bot.send_message(admin_id, reminder_text(order, paid))
            except Exception as exc:
                logger.exception("Eslatma yuborilmadi: %s", safe_db_message(exc))
                continue
            order.reminder_sent_on = today_local()
        await session.commit()


async def reminder_loop(bot: Bot) -> None:
    while True:
        try:
            await send_event_questions(bot)
            await send_due_reminders(bot)
        except Exception as exc:
            logger.exception("Eslatma tekshiruvi: %s", safe_db_message(exc))
        await asyncio.sleep(900)
