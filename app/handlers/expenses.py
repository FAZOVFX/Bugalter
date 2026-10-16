from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.formatting import as_moment, money, parse_amount, to_decimal
from app.handlers.access import actor_id
from app.handlers.support import (
    blank_note,
    callback_message,
    message_text,
    read_day,
    remember_key,
    unit_of_work,
)
from app.handlers.views import h
from app.keyboards import (
    cancel_menu,
    confirm_keyboard,
    date_menu,
    expense_menu,
    main_menu,
    note_menu,
)
from app.locks import user_lock
from app.services import UserFacingError, add_expense
from app.texts import EXPENSE_TEXTS, OTHER_EXPENSE

menu_router = Router()
form_router = Router()


class ExpenseForm(StatesGroup):
    category = State()
    category_custom = State()
    amount = State()
    note = State()
    spent_on = State()
    confirm = State()


def _confirm_text(data: dict) -> str:
    return (
        "<b>Xarajatni tasdiqlang</b>\n"
        f"Kategoriya: {h(data.get('category'))}\n"
        f"Summa: {money(data.get('amount'))}\n"
        f"Izoh: {h(data.get('description')) or '-'}\n"
        f"Sana: {h(data.get('spent_on_label'))}"
    )


async def show_expense_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(ExpenseForm.category)
    await state.update_data(place="expense")
    await message.answer("Xarajat kategoriyasini tanlang yoki yozing.", reply_markup=expense_menu())


@menu_router.message(Command("expense"))
@menu_router.message(F.text.in_(EXPENSE_TEXTS))
async def start_expense(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_expense_menu(message, state)


@form_router.message(ExpenseForm.category)
async def expense_category(message: Message, state: FSMContext) -> None:
    category = message_text(message)
    if not category or len(category) > 120:
        await message.answer("Kategoriyani 120 belgigacha kiriting.")
        return
    if category == OTHER_EXPENSE:
        await state.update_data(place="expense_form")
        await state.set_state(ExpenseForm.category_custom)
        await message.answer("Xarajat kategoriyasini yozing.", reply_markup=cancel_menu())
        return
    await state.update_data(category=category, place="expense_form")
    await state.set_state(ExpenseForm.amount)
    await message.answer("Xarajat summasini kiriting.", reply_markup=cancel_menu())


@form_router.message(ExpenseForm.category_custom)
async def expense_category_custom(message: Message, state: FSMContext) -> None:
    category = message_text(message)
    if len(category) < 2 or len(category) > 120:
        await message.answer("Kategoriyani 2 tadan 120 tagacha belgi bilan kiriting.")
        return
    await state.update_data(category=category, place="expense_form")
    await state.set_state(ExpenseForm.amount)
    await message.answer("Xarajat summasini kiriting.", reply_markup=cancel_menu())


@form_router.message(ExpenseForm.amount)
async def expense_amount(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message_text(message))
    if amount is None:
        await message.answer("Summani musbat son bilan kiriting.")
        return
    await state.update_data(amount=str(amount))
    await state.set_state(ExpenseForm.note)
    await message.answer("Izoh yozing yoki Izohsiz ni bosing.", reply_markup=note_menu())


@form_router.message(ExpenseForm.note)
async def expense_note(message: Message, state: FSMContext) -> None:
    description = blank_note(message_text(message))
    if len(description) > 2000:
        await message.answer("Izoh 2000 belgidan oshmasin.")
        return
    await state.update_data(description=description)
    await state.set_state(ExpenseForm.spent_on)
    await message.answer(
        "Xarajat sanasini 25.10.2026 ko'rinishida kiriting yoki Bugun ni bosing.",
        reply_markup=date_menu(),
    )


@form_router.message(ExpenseForm.spent_on)
async def expense_date(message: Message, state: FSMContext) -> None:
    ok, day = read_day(message_text(message), allow_empty=False)
    if not ok or day is None:
        await message.answer("Sanani 25.10.2026 ko'rinishida kiriting yoki Bugun ni bosing.")
        return
    await state.update_data(spent_on=day.isoformat(), spent_on_label=day.strftime("%d.%m.%Y"))
    await remember_key(state)
    await state.set_state(ExpenseForm.confirm)
    data = await state.get_data()
    await message.answer(_confirm_text(data), reply_markup=confirm_keyboard("expense"))


@form_router.message(ExpenseForm.confirm)
async def expense_confirm_text(message: Message) -> None:
    await message.answer("Saqlash tugmasini bosing yoki Bekor qilishni tanlang.")


@form_router.callback_query(ExpenseForm.confirm, F.data == "save:expense")
async def save_expense(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    async with user_lock(actor_id(callback)):
        if await state.get_state() != ExpenseForm.confirm.state:
            await callback.answer("Bu amal allaqachon yakunlangan.", show_alert=True)
            return
        data = await state.get_data()
        if data.get("done"):
            await callback.answer("Xarajat allaqachon saqlangan.", show_alert=True)
            return
        await callback.answer()
        await state.update_data(done=True)
        try:
            spent_on = date.fromisoformat(str(data["spent_on"]))
            async with unit_of_work() as session:
                expense, created = await add_expense(
                    session,
                    category=str(data["category"]),
                    amount=to_decimal(data.get("amount")),
                    description=str(data.get("description") or ""),
                    spent_at=as_moment(spent_on),
                    idempotency_key=str(data["idempotency_key"]),
                )
                category = expense.category
                amount = expense.amount
        except UserFacingError as exc:
            await state.update_data(done=False)
            if message is not None:
                await message.answer(h(exc.user_message), reply_markup=cancel_menu())
            return
        except Exception:
            await state.update_data(done=False)
            raise
        await state.clear()
    if message is None:
        return
    prefix = "Xarajat saqlandi." if created else "Bu xarajat avval saqlangan, qayta yozilmadi."
    await message.answer(
        f"<b>{h(prefix)}</b>\n{h(category)} — {money(amount)}",
        reply_markup=main_menu(),
    )
