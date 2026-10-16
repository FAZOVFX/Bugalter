from datetime import date
from pathlib import Path

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.database import Order, SessionLocal
from app.excel_report import write_excel
from app.formatting import format_date, today_local
from app.handlers.payments import begin_payment
from app.handlers.support import callback_message, message_text, read_day, send_text, unit_of_work
from app.handlers.views import client_card_text, daily_text, h, monthly_text, period_stats_text
from app.keyboards import (
    cancel_menu,
    choice_inline,
    current_year,
    date_menu,
    debtor_card_keyboard,
    excel_scope_keyboard,
    main_menu,
    month_keyboard,
    report_menu,
    stats_scope_keyboard,
    year_keyboard,
)
from app.reports import (
    daily_period,
    excel_data,
    figures_for,
    listed_orders,
    monthly_clients,
    monthly_period,
    yearly_period,
)
from app.services import UserFacingError, paid_sum, set_payment_due
from app.texts import DAILY, DEBTOR_TEXTS, EXCEL_TEXTS, MONTHLY_TEXTS, REPORT_TEXTS, STATS

menu_router = Router()


class DueForm(StatesGroup):
    day = State()


async def _debtor_list_markup():
    async with SessionLocal() as session:
        buttons, total = await listed_orders(session, debts_only=True)
    if total == 0:
        return "Hozircha qarzi bor mijoz yo'q.", None
    extra = ""
    if total > len(buttons):
        extra = f"\nKo'rsatildi: {len(buttons)} / {total}."
    return f"<b>Qarzdorlar</b>\nMijozni tanlang.{extra}", choice_inline(buttons, "dbt")


async def show_debtor_list(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(place="debtors")
    text, markup = await _debtor_list_markup()
    await message.answer(text, reply_markup=markup or main_menu())


async def show_debtor_card(message: Message, order_id: int) -> None:
    async with SessionLocal() as session:
        order = await session.get(Order, order_id)
        if order is None:
            await message.answer("Buyurtma topilmadi.")
            return
        paid = await paid_sum(session, order.id)
        text = client_card_text(order, paid)
    await message.answer(text, reply_markup=debtor_card_keyboard(order_id))


async def _show_debtor(message: Message, order_id: int) -> None:
    async with SessionLocal() as session:
        order = await session.get(Order, order_id)
        if order is None:
            await message.answer("Buyurtma topilmadi.")
            return
        paid = await paid_sum(session, order.id)
        text = client_card_text(order, paid)
    try:
        await message.edit_text(text, reply_markup=debtor_card_keyboard(order_id))
    except TelegramBadRequest:
        await message.answer(text, reply_markup=debtor_card_keyboard(order_id))


async def _edit_or_send(message: Message, text: str, markup) -> None:
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=markup)


def _valid_year(raw: str) -> int | None:
    if not raw.isdigit():
        return None
    year = int(raw)
    if year < 2020 or year > 2100:
        return None
    return year


async def _send_daily(message: Message) -> None:
    period = daily_period(today_local())
    async with SessionLocal() as session:
        figures = await figures_for(session, period)
    await message.answer(daily_text(figures, period.label), reply_markup=main_menu())


async def _send_excel(message: Message, day: date | None, year: int | None, month: int | None) -> None:
    if day is not None:
        period = daily_period(day)
    elif year is not None and month is not None:
        period = monthly_period(year, month)
    else:
        await message.answer("Hisobot davri tanlanmadi.", reply_markup=main_menu())
        return
    path: Path | None = None
    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)
        async with SessionLocal() as session:
            data = await excel_data(session, period)
        path = write_excel(data)
        filename = f"FAZO_{period.kind}_{period.start:%Y_%m_%d}.xlsx"
        await message.answer_document(
            FSInputFile(path, filename=filename),
            caption=f"FAZO CREATIVE GROUP — {h(period.label)}",
            reply_markup=main_menu(),
        )
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


@menu_router.message(Command("report"))
@menu_router.message(F.text.in_(REPORT_TEXTS))
async def open_reports(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Hisobot turini tanlang.", reply_markup=report_menu())


@menu_router.callback_query(F.data == "rep:menu")
async def back_to_reports(callback: CallbackQuery) -> None:
    message = await callback_message(callback)
    await callback.answer()
    if message is not None:
        await _edit_or_send(message, "Hisobot turini tanlang.", report_menu())


@menu_router.message(Command("daily"))
@menu_router.message(F.text == DAILY)
async def daily_report(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_daily(message)


@menu_router.callback_query(F.data == "rep:day")
async def report_daily(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    await callback.answer()
    await state.clear()
    if message is not None:
        await _send_daily(message)


@menu_router.message(Command("month"))
@menu_router.message(F.text.in_(MONTHLY_TEXTS))
async def monthly_prompt(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Oyni tanlang.", reply_markup=month_keyboard("mrep", current_year()))


@menu_router.callback_query(F.data == "rep:month")
async def report_month(callback: CallbackQuery) -> None:
    message = await callback_message(callback)
    await callback.answer()
    if message is not None:
        await _edit_or_send(message, "Oyni tanlang.", month_keyboard("mrep", current_year()))


@menu_router.callback_query(F.data.startswith("mrepy:"))
async def monthly_year(callback: CallbackQuery) -> None:
    year = _valid_year((callback.data or "").split(":", maxsplit=1)[-1])
    if year is None:
        await callback.answer("Bu yil oralig'i qo'llab-quvvatlanmaydi.", show_alert=True)
        return
    message = await callback_message(callback)
    await callback.answer()
    if message is not None:
        await message.edit_reply_markup(reply_markup=month_keyboard("mrep", year))


@menu_router.callback_query(F.data.startswith("mrep:"))
async def monthly_report(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await callback.answer("Oy noto'g'ri", show_alert=True)
        return
    year = int(parts[1])
    month = int(parts[2])
    if not 1 <= month <= 12:
        await callback.answer("Oy noto'g'ri", show_alert=True)
        return
    message = await callback_message(callback)
    await callback.answer()
    await state.clear()
    if message is None:
        return
    period = monthly_period(year, month)
    async with SessionLocal() as session:
        figures = await figures_for(session, period)
        clients = await monthly_clients(session, year, month)
    await send_text(message, monthly_text(figures, clients, period.label), reply_markup=main_menu())


@menu_router.message(Command("debtors"))
@menu_router.message(F.text.in_(DEBTOR_TEXTS))
async def debtor_report(message: Message, state: FSMContext) -> None:
    await show_debtor_list(message, state)


def _debtor_action(data: str) -> tuple[str, str] | None:
    prefixes = (
        ("dbt:closeok:", "closeok"),
        ("dbt:delok:", "delok"),
        ("dbt:close:", "close"),
        ("dbt:del:", "del"),
    )
    for prefix, kind in prefixes:
        if data.startswith(prefix):
            return kind, data.removeprefix(prefix)
    return None


@menu_router.callback_query(F.data.startswith("dbt:"))
async def debtor_callback(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    if message is None:
        await callback.answer()
        return
    data = callback.data or ""
    if data == "dbt:list":
        await state.clear()
        await state.update_data(place="debtors")
        await callback.answer()
        text, markup = await _debtor_list_markup()
        try:
            await message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest:
            await message.answer(text, reply_markup=markup or main_menu())
        return
    if data.startswith("dbt:pay:"):
        raw = data.removeprefix("dbt:pay:")
        if not raw.isdigit():
            await callback.answer()
            return
        await state.update_data(card_back="debtor", order_id=int(raw))
        await callback.answer()
        await begin_payment(message, state, int(raw))
        return
    if data.startswith("dbt:due:"):
        raw = data.removeprefix("dbt:due:")
        if not raw.isdigit():
            await callback.answer()
            return
        await state.update_data(
            due_order_id=int(raw),
            order_id=int(raw),
            place="due",
            card_back="debtor",
        )
        await state.set_state(DueForm.day)
        await callback.answer()
        await message.answer(
            "Qolgan qarzni berish sanasini tanlang yoki yozing.",
            reply_markup=date_menu(),
        )
        return
    listed = _debtor_action(data)
    if listed is not None:
        kind, raw_id = listed
        if not raw_id.isdigit():
            await callback.answer()
            return
        # orders reports_bot ni yuklaydi; bu yerda kechiktirilgan import aylanishni uzadi.
        from app.handlers.orders import finish_delete, finish_full_close, prompt_delete, prompt_full_close

        order_id = int(raw_id)
        await callback.answer()
        if kind == "close":
            await prompt_full_close(message, state, order_id, card_back="debtor")
            return
        if kind == "closeok":
            await finish_full_close(message, state, order_id)
            return
        if kind == "del":
            await prompt_delete(message, state, order_id, card_back="debtor")
            return
        if kind == "delok":
            await finish_delete(message, state, order_id)
            return
        return
    raw = data.removeprefix("dbt:")
    if not raw.isdigit():
        await callback.answer()
        return
    await state.update_data(place="debtor", order_id=int(raw))
    await callback.answer()
    await _show_debtor(message, int(raw))


@menu_router.message(DueForm.day)
async def due_day(message: Message, state: FSMContext) -> None:
    ok, day = read_day(message_text(message), allow_empty=False)
    if not ok or day is None:
        await message.answer("Sanani tanlang yoki yozing.")
        return
    data = await state.get_data()
    order_id = int(data.get("due_order_id") or 0)
    if order_id <= 0:
        await state.clear()
        await message.answer("Mijoz tanlanmagan.", reply_markup=main_menu())
        return
    try:
        async with unit_of_work() as session:
            order = await set_payment_due(session, order_id, day)
            client = order.client_name
    except UserFacingError as exc:
        await message.answer(h(exc.user_message), reply_markup=cancel_menu())
        return
    card_back = str(data.get("card_back") or "")
    await message.answer(
        f"<b>Qarz sanasi saqlandi</b>\n"
        f"{h(client)}\n"
        f"Sana: {format_date(day)}\n"
        "Shu kuni bot eslatma yuboradi.",
    )
    if card_back == "order_card":
        # orders reports_bot ni yuklaydi; bu yerda kechiktirilgan import aylanishni uzadi.
        from app.handlers.orders import show_order_card

        await show_order_card(message, state, order_id)
        return
    if card_back == "debtor":
        await state.clear()
        await state.update_data(place="debtor", order_id=order_id)
        await show_debtor_card(message, order_id)
        return
    await state.clear()
    await message.answer("Kerakli bo'limni menyudan tanlang.", reply_markup=main_menu())


@menu_router.message(Command("stats"))
@menu_router.message(F.text == STATS)
async def statistics(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Statistika davrini tanlang.", reply_markup=stats_scope_keyboard())


@menu_router.callback_query(F.data == "rep:stats")
async def report_stats(callback: CallbackQuery) -> None:
    message = await callback_message(callback)
    await callback.answer()
    if message is not None:
        await _edit_or_send(message, "Statistika davrini tanlang.", stats_scope_keyboard())


@menu_router.callback_query(F.data == "stat:month")
async def stats_choose_month(callback: CallbackQuery) -> None:
    message = await callback_message(callback)
    await callback.answer()
    if message is not None:
        await _edit_or_send(message, "Oyni tanlang.", month_keyboard("mstat", current_year()))


@menu_router.callback_query(F.data == "stat:year")
async def stats_choose_year(callback: CallbackQuery) -> None:
    message = await callback_message(callback)
    await callback.answer()
    if message is not None:
        await _edit_or_send(message, "Yilni tanlang.", year_keyboard("ystat", current_year()))


@menu_router.callback_query(F.data.startswith("mstaty:"))
async def stats_month_year(callback: CallbackQuery) -> None:
    year = _valid_year((callback.data or "").split(":", maxsplit=1)[-1])
    if year is None:
        await callback.answer("Bu yil oralig'i qo'llab-quvvatlanmaydi.", show_alert=True)
        return
    message = await callback_message(callback)
    await callback.answer()
    if message is not None:
        await message.edit_reply_markup(reply_markup=month_keyboard("mstat", year))


@menu_router.callback_query(F.data.startswith("mstat:"))
async def stats_month(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await callback.answer("Oy noto'g'ri", show_alert=True)
        return
    year = int(parts[1])
    month = int(parts[2])
    if not 1 <= month <= 12:
        await callback.answer("Oy noto'g'ri", show_alert=True)
        return
    message = await callback_message(callback)
    await callback.answer()
    await state.clear()
    if message is None:
        return
    period = monthly_period(year, month)
    async with SessionLocal() as session:
        figures = await figures_for(session, period)
    await message.answer(
        period_stats_text(figures, period.label, "monthly"),
        reply_markup=main_menu(),
    )


@menu_router.callback_query(F.data.startswith("ystaty:"))
async def stats_year_nav(callback: CallbackQuery) -> None:
    year = _valid_year((callback.data or "").split(":", maxsplit=1)[-1])
    if year is None:
        await callback.answer("Bu yil oralig'i qo'llab-quvvatlanmaydi.", show_alert=True)
        return
    message = await callback_message(callback)
    await callback.answer()
    if message is not None:
        await message.edit_reply_markup(reply_markup=year_keyboard("ystat", year))


@menu_router.callback_query(F.data.startswith("ystat:"))
async def stats_year(callback: CallbackQuery, state: FSMContext) -> None:
    year = _valid_year((callback.data or "").split(":", maxsplit=1)[-1])
    if year is None:
        await callback.answer("Bu yil oralig'i qo'llab-quvvatlanmaydi.", show_alert=True)
        return
    message = await callback_message(callback)
    await callback.answer()
    await state.clear()
    if message is None:
        return
    period = yearly_period(year)
    async with SessionLocal() as session:
        figures = await figures_for(session, period)
    await message.answer(
        period_stats_text(figures, period.label, "yearly"),
        reply_markup=main_menu(),
    )


@menu_router.message(Command("export"))
@menu_router.message(F.text.in_(EXCEL_TEXTS))
async def excel_prompt(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Excel fayl qaysi davr uchun?", reply_markup=excel_scope_keyboard())


@menu_router.callback_query(F.data == "rep:excel")
async def report_excel(callback: CallbackQuery) -> None:
    message = await callback_message(callback)
    await callback.answer()
    if message is not None:
        await _edit_or_send(message, "Excel fayl qaysi davr uchun?", excel_scope_keyboard())


@menu_router.callback_query(F.data == "xlscope:day")
async def excel_today(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    await callback.answer()
    await state.clear()
    if message is None:
        return
    await _send_excel(message, today_local(), None, None)


@menu_router.callback_query(F.data == "xlscope:month")
async def excel_month_prompt(callback: CallbackQuery) -> None:
    message = await callback_message(callback)
    await callback.answer()
    if message is not None:
        await message.answer("Oyni tanlang.", reply_markup=month_keyboard("mxls", current_year()))


@menu_router.callback_query(F.data.startswith("mxlsy:"))
async def excel_year(callback: CallbackQuery) -> None:
    year = _valid_year((callback.data or "").split(":", maxsplit=1)[-1])
    if year is None:
        await callback.answer("Bu yil oralig'i qo'llab-quvvatlanmaydi.", show_alert=True)
        return
    message = await callback_message(callback)
    await callback.answer()
    if message is not None:
        await message.edit_reply_markup(reply_markup=month_keyboard("mxls", year))


@menu_router.callback_query(F.data.startswith("mxls:"))
async def excel_month(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await callback.answer("Oy noto'g'ri", show_alert=True)
        return
    year = int(parts[1])
    month = int(parts[2])
    if not 1 <= month <= 12:
        await callback.answer("Oy noto'g'ri", show_alert=True)
        return
    message = await callback_message(callback)
    await callback.answer()
    await state.clear()
    if message is None:
        return
    await _send_excel(message, None, year, month)
