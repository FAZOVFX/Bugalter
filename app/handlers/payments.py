from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.database import Order, SessionLocal
from app.formatting import as_moment, debt_of, money, parse_amount, to_decimal
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
    main_menu,
    method_menu,
    note_menu,
    order_choice_keyboard,
)
from app.locks import user_lock
from app.services import (
    UserFacingError,
    add_payment,
    order_label,
    paid_sum,
    search_orders,
)
from app.texts import OTHER_METHOD, PAYMENT_TEXTS

menu_router = Router()
form_router = Router()


class PaymentForm(StatesGroup):
    query = State()
    amount = State()
    method = State()
    method_custom = State()
    note = State()
    paid_on = State()
    confirm = State()


async def _show_amount(message: Message, state: FSMContext, order_id: int) -> None:
    async with SessionLocal() as session:
        order = await session.get(Order, order_id)
        if order is None:
            await message.answer("Buyurtma topilmadi. Raqam yoki ismni qayta kiriting.")
            return
        paid = await paid_sum(session, order.id)
        remaining = debt_of(order.total_price, paid)
        label = order_label(order)
        total = order.total_price
    if remaining <= 0:
        await message.answer(f"{h(label)} bo'yicha qarz yo'q.")
        data = await state.get_data()
        if data.get("card_back") == "order_card":
            # orders payments ni yuklaydi; kechiktirilgan import aylanishni uzadi.
            from app.handlers.orders import show_order_card

            await show_order_card(message, state, order_id)
            return
        if data.get("card_back") == "debtor":
            from app.handlers.reports_bot import show_debtor_card

            await state.clear()
            await state.update_data(place="debtor", order_id=order_id)
            await show_debtor_card(message, order_id)
            return
        await message.answer("Kerakli bo'limni menyudan tanlang.", reply_markup=main_menu())
        return
    await state.update_data(
        order_id=order_id,
        order_label=label,
        remaining=str(remaining),
        total_price=str(to_decimal(total)),
        place="payment",
    )
    await state.set_state(PaymentForm.amount)
    await message.answer(
        f"<b>{h(label)}</b>\n"
        f"Kelishilgan narx: {money(total)}\n"
        f"Qolgan qarz: {money(remaining)}\n\n"
        "To'lov summasini kiriting.",
        reply_markup=cancel_menu(),
    )


def _confirm_text(data: dict) -> str:
    return (
        "<b>To'lovni tasdiqlang</b>\n"
        f"Buyurtma: {h(data.get('order_label'))}\n"
        f"Summa: {money(data.get('amount'))}\n"
        f"Usul: {h(data.get('method'))}\n"
        f"Izoh: {h(data.get('note')) or '-'}\n"
        f"Sana: {h(data.get('paid_on_label'))}"
    )


async def begin_payment(message: Message, state: FSMContext, order_id: int) -> None:
    await _show_amount(message, state, order_id)


@menu_router.message(Command("payment"))
@menu_router.message(F.text.in_(PAYMENT_TEXTS))
async def start_payment(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Pul qo'shish Qarzdorlar bo'limida.",
        reply_markup=main_menu(),
    )


@form_router.message(PaymentForm.query)
async def payment_query(message: Message, state: FSMContext) -> None:
    query = message_text(message)
    if len(query) < 1:
        await message.answer("Buyurtma raqami yoki mijoz ismini kiriting.")
        return
    async with SessionLocal() as session:
        found = await search_orders(session, query)
        choices = [(order.id, order_label(order)) for order in found[:10]]
        truncated = len(found) > 10
    if not choices:
        await message.answer("Buyurtma topilmadi. Raqam yoki ismni qayta kiriting.")
        return
    if truncated:
        await message.answer("Juda ko'p moslik. Buyurtma raqamini yoki to'liqroq ismni kiriting.")
        return
    if len(choices) == 1:
        await _show_amount(message, state, choices[0][0])
        return
    await state.set_state(PaymentForm.query)
    await message.answer(
        "Qaysi buyurtma ekanini tanlang.",
        reply_markup=order_choice_keyboard(choices),
    )


@form_router.callback_query(PaymentForm.query, F.data.startswith("pick:"))
async def pick_order(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    raw = (callback.data or "").split(":", maxsplit=1)[-1]
    if not raw.isdigit() or message is None:
        await callback.answer("Buyurtma tanlanmadi", show_alert=True)
        return
    await callback.answer()
    await _show_amount(message, state, int(raw))


@form_router.message(PaymentForm.amount)
async def payment_amount(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message_text(message))
    if amount is None:
        await message.answer("Summani musbat son bilan kiriting.")
        return
    data = await state.get_data()
    remaining = to_decimal(data.get("remaining"))
    if amount > remaining:
        await message.answer(f"Qolgan qarz {money(remaining)}. Shu summadan katta to'lov qabul qilinmaydi.")
        return
    await state.update_data(amount=str(amount))
    await state.set_state(PaymentForm.method)
    await message.answer("To'lov usulini tanlang.", reply_markup=method_menu())


@form_router.message(PaymentForm.method)
async def payment_method(message: Message, state: FSMContext) -> None:
    method = message_text(message)
    if not method or len(method) > 40:
        await message.answer("To'lov usulini tanlang yoki 40 belgigacha yozing.")
        return
    if method == OTHER_METHOD:
        await state.set_state(PaymentForm.method_custom)
        await message.answer("To'lov usulini yozing.", reply_markup=cancel_menu())
        return
    await state.update_data(method=method)
    await state.set_state(PaymentForm.note)
    await message.answer("To'lov izohini yozing yoki Izohsiz ni bosing.", reply_markup=note_menu())


@form_router.message(PaymentForm.method_custom)
async def payment_method_custom(message: Message, state: FSMContext) -> None:
    method = message_text(message)
    if not method or len(method) > 40:
        await message.answer("Usul nomini 40 belgigacha kiriting.")
        return
    await state.update_data(method=method)
    await state.set_state(PaymentForm.note)
    await message.answer("To'lov izohini yozing yoki Izohsiz ni bosing.", reply_markup=note_menu())


@form_router.message(PaymentForm.note)
async def payment_note(message: Message, state: FSMContext) -> None:
    note = blank_note(message_text(message))
    if len(note) > 2000:
        await message.answer("Izoh 2000 belgidan oshmasin.")
        return
    await state.update_data(note=note)
    await state.set_state(PaymentForm.paid_on)
    await message.answer(
        "To'lov sanasini tanlang yoki yozing.",
        reply_markup=date_menu(),
    )


@form_router.message(PaymentForm.paid_on)
async def payment_date(message: Message, state: FSMContext) -> None:
    ok, day = read_day(message_text(message), allow_empty=False)
    if not ok or day is None:
        await message.answer("Sanani tanlang yoki yozing.")
        return
    await state.update_data(paid_on=day.isoformat(), paid_on_label=day.strftime("%d.%m.%Y"))
    await remember_key(state)
    await state.set_state(PaymentForm.confirm)
    data = await state.get_data()
    await message.answer(_confirm_text(data), reply_markup=confirm_keyboard("payment"))


@form_router.message(PaymentForm.confirm)
async def payment_confirm_text(message: Message) -> None:
    await message.answer("Saqlash tugmasini bosing yoki Bekor qilishni tanlang.")


@form_router.callback_query(PaymentForm.confirm, F.data == "save:payment")
async def save_payment(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    async with user_lock(actor_id(callback)):
        if await state.get_state() != PaymentForm.confirm.state:
            await callback.answer("Bu amal allaqachon yakunlangan.", show_alert=True)
            return
        data = await state.get_data()
        if data.get("done"):
            await callback.answer("To'lov allaqachon saqlangan.", show_alert=True)
            return
        await callback.answer()
        await state.update_data(done=True)
        try:
            paid_on = date.fromisoformat(str(data["paid_on"]))
            async with unit_of_work() as session:
                payment, order, created = await add_payment(
                    session,
                    order_id=int(data["order_id"]),
                    amount=to_decimal(data.get("amount")),
                    method=str(data.get("method") or "Naqd"),
                    note=str(data.get("note") or ""),
                    paid_at=as_moment(paid_on),
                    idempotency_key=str(data["idempotency_key"]),
                )
                paid = payment.amount
                number = order.order_number
                client = order.client_name
                total_paid = order.paid_amount
                debt = debt_of(order.total_price, order.paid_amount)
                saved_order_id = order.id
        except UserFacingError as exc:
            await state.update_data(done=False)
            await state.set_state(PaymentForm.amount)
            if message is not None:
                await message.answer(h(exc.user_message), reply_markup=cancel_menu())
            return
        except Exception:
            await state.update_data(done=False)
            raise
        card_back = str(data.get("card_back") or "")
        await state.clear()
    if message is None:
        return
    prefix = "To'lov saqlandi." if created else "Bu to'lov avval saqlangan, qayta yozilmadi."
    await message.answer(
        f"<b>{h(prefix)}</b>\n"
        f"Buyurtma: {h(number)} — {h(client)}\n"
        f"Kiritilgan summa: {money(paid)}\n"
        f"Jami to'langan: {money(total_paid)}\n"
        f"Qolgan qarz: {money(debt)}",
    )
    if card_back == "order_card":
        from app.handlers.orders import show_order_card

        await show_order_card(message, state, saved_order_id)
        return
    if card_back == "debtor":
        from app.handlers.reports_bot import show_debtor_card

        await state.update_data(place="debtor", order_id=saved_order_id)
        await show_debtor_card(message, saved_order_id)
        return
    await message.answer("Kerakli bo'limni menyudan tanlang.", reply_markup=main_menu())
