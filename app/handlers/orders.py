import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.database import Order, SessionLocal
from app.formatting import as_moment, debt_of, money, parse_amount, today_local, to_decimal
from app.handlers.access import actor_id
from app.handlers.support import (
    blank_note,
    callback_message,
    message_text,
    read_day,
    remember_key,
    unit_of_work,
    valid_phone,
)
from app.handlers.payments import begin_payment
from app.handlers.reports_bot import DueForm, show_debtor_card, show_debtor_list
from app.handlers.views import client_card_text, h, saved_order_text
from app.keyboards import (
    cancel_menu,
    confirm_keyboard,
    date_menu,
    main_menu,
    note_menu,
    month_calendar,
    order_card_keyboard,
    order_confirm_keyboard,
    order_list_keyboard,
    wedding_keyboard,
    prepaid_menu,
    service_keyboard,
)
from app.locks import user_lock
from app.logsafe import safe_db_message
from app.order_pdf import ClientPage, write_client_pdf, write_orders_pdf
from app.reports import all_order_lines, listed_orders
from app.services import (
    UserFacingError,
    add_payment,
    collect_event_share,
    create_order,
    delete_order,
    mark_event_checked,
    paid_sum,
    settle_order,
)
from app.texts import (
    NEW_ORDER_TEXTS,
    NO_PREPAY_TEXTS,
    ORDER_LIST_TEXTS,
    SERVICE_LABELS,
    SERVICE_OTHER,
    WEDDING_LABELS,
)

menu_router = Router()
form_router = Router()
logger = logging.getLogger(__name__)


class OrderForm(StatesGroup):
    event_kind = State()
    event_kind_custom = State()
    client_name = State()
    phone = State()
    service = State()
    service_custom = State()
    service_price = State()
    prepaid = State()
    event_date = State()
    note = State()
    confirm = State()
    event_collect = State()


def _service_items(data: dict) -> list[dict[str, str]]:
    raw = data.get("service_items")
    if not isinstance(raw, list):
        return []
    items: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "")
        label = str(item.get("label") or "")
        amount = str(item.get("amount") or "")
        if code and label and amount:
            items.append({"code": code, "label": label, "amount": amount})
    return items


def _with_price(
    items: list[dict[str, str]],
    code: str,
    label: str,
    amount: Decimal,
) -> list[dict[str, str]]:
    updated = [
        {"code": code, "label": label, "amount": str(amount)} if item["code"] == code else item
        for item in items
    ]
    if any(item["code"] == code for item in items):
        return updated
    return [*updated, {"code": code, "label": label, "amount": str(amount)}]


def _service_text(items: list[dict[str, str]]) -> str:
    return ", ".join(f"{item['label']} — {money(item['amount'])}" for item in items)


def _service_total(items: list[dict[str, str]]) -> Decimal:
    total = Decimal("0.00")
    for item in items:
        total += to_decimal(item["amount"])
    return to_decimal(total)


def _confirm_text(data: dict) -> str:
    event = data.get("event_date") or ""
    prepaid = to_decimal(data.get("prepaid"))
    total = to_decimal(data.get("total_price"))
    return (
        "<b>Buyurtmani tasdiqlang</b>\n"
        f"To'y: {h(data.get('client_name'))}\n"
        f"Telefon: {h(data.get('phone'))}\n"
        f"Xizmat: {h(data.get('service'))}\n"
        f"Kelishilgan narx: {money(total)}\n"
        f"Oldindan to'lov: {money(prepaid)}\n"
        f"Qolgan qarz: {money(total - prepaid)}\n"
        f"Tadbir sanasi: {h(event) or 'Ko‘rsatilmagan'}\n"
        f"Izoh: {h(data.get('notes')) or '-'}"
    )


@menu_router.message(Command("neworder"))
@menu_router.message(F.text.in_(NEW_ORDER_TEXTS))
async def start_order(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(OrderForm.event_kind)
    await state.update_data(place="order")
    await message.answer("To'y turini tanlang yoki yozing.", reply_markup=cancel_menu())
    await message.answer("Tugmadan tanlang.", reply_markup=wedding_keyboard())


async def _order_list_markup():
    async with SessionLocal() as session:
        buttons, total = await listed_orders(session, debts_only=False)
    if total == 0:
        return "Hali buyurtma yo'q.", None
    extra = ""
    if total > len(buttons):
        extra = f"\nKo'rsatildi: {len(buttons)} / {total}."
    return f"<b>Buyurtmalar</b>\nMijozni tanlang.{extra}", order_list_keyboard(buttons)


async def show_order_list(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(place="orders")
    text, markup = await _order_list_markup()
    await message.answer(text, reply_markup=markup or main_menu())


async def _card_payload(order_id: int) -> tuple[str, object] | None:
    async with SessionLocal() as session:
        order = await session.get(Order, order_id)
        if order is None:
            return None
        paid = await paid_sum(session, order.id)
        return client_card_text(order, paid), order_card_keyboard(order.id)


async def show_order_card(message: Message, state: FSMContext, order_id: int) -> None:
    payload = await _card_payload(order_id)
    if payload is None:
        await message.answer("Buyurtma topilmadi.")
        await show_order_list(message, state)
        return
    text, markup = payload
    await state.clear()
    await state.update_data(place="order_card", order_id=order_id)
    await message.answer(text, reply_markup=markup)


async def prompt_full_close(
    message: Message,
    state: FSMContext,
    order_id: int,
    *,
    card_back: str,
) -> None:
    async with SessionLocal() as session:
        order = await session.get(Order, order_id)
        if order is None:
            await message.answer("Buyurtma topilmadi.")
            return
        remaining = debt_of(order.total_price, await paid_sum(session, order.id))
        client = order.client_name
    if remaining <= 0:
        await message.answer(f"{h(client)} allaqachon to'liq yopilgan.")
        if card_back == "debtor":
            await show_debtor_card(message, order_id)
            await state.update_data(place="debtor", order_id=order_id, card_back="debtor")
            return
        await show_order_card(message, state, order_id)
        return
    await remember_key(state)
    await state.update_data(
        place="order_close",
        order_id=order_id,
        card_back=card_back,
        done=False,
    )
    await message.answer(
        f"<b>{h(client)}</b>\n"
        f"Qolgan qarz: {money(remaining)}\n\n"
        "Shu summa to'liq berilgan deb yopilsinmi?",
        reply_markup=order_confirm_keyboard(order_id, "close", back=card_back),
    )


async def prompt_delete(
    message: Message,
    state: FSMContext,
    order_id: int,
    *,
    card_back: str,
) -> None:
    async with SessionLocal() as session:
        order = await session.get(Order, order_id)
        if order is None:
            await message.answer("Buyurtma topilmadi.")
            return
        client = order.client_name
        number = order.order_number or f"#{order.id}"
    await state.update_data(place="order_delete", order_id=order_id, card_back=card_back)
    await message.answer(
        f"<b>{h(number)} — {h(client)}</b>\n"
        "Bu mijoz buyurtmasi o'chirilsinmi?\n"
        "Mijoz to'lovlari ham o'chadi. Hodimga berilgan pul va hodim qarzi saqlanadi.",
        reply_markup=order_confirm_keyboard(order_id, "delete", back=card_back),
    )


async def finish_full_close(message: Message, state: FSMContext, order_id: int) -> None:
    async with user_lock(actor_id(message)):
        data = await state.get_data()
        if data.get("done"):
            await message.answer("Bu amal allaqachon bajarilgan.")
            return
        await state.update_data(done=True)
        key = str(data.get("idempotency_key") or "")
        if not key:
            key = await remember_key(state)
        try:
            async with unit_of_work() as session:
                payment, order, created = await settle_order(
                    session,
                    order_id=order_id,
                    paid_at=as_moment(today_local()),
                    idempotency_key=key,
                )
                client = order.client_name
                paid = payment.amount
        except UserFacingError as exc:
            await state.update_data(done=False)
            await message.answer(h(exc.user_message))
            return
        except Exception:
            await state.update_data(done=False)
            raise
    prefix = "Buyurtma to'liq yopildi." if created else "Bu yopish avval saqlangan."
    await message.answer(f"<b>{h(prefix)}</b>\n{h(client)}\n{money(paid)}")
    card_back = str(data.get("card_back") or "order_card")
    if card_back == "debtor":
        await show_debtor_list(message, state)
        return
    await show_order_card(message, state, order_id)


async def finish_delete(message: Message, state: FSMContext, order_id: int) -> None:
    card_back = str((await state.get_data()).get("card_back") or "order_card")
    try:
        async with unit_of_work() as session:
            client = await delete_order(session, order_id)
    except UserFacingError as exc:
        await message.answer(h(exc.user_message))
        return
    await message.answer(f"<b>Mijoz o'chirildi</b>\n{h(client)}")
    if card_back == "debtor":
        await show_debtor_list(message, state)
        return
    await show_order_list(message, state)


@menu_router.message(Command("orders"))
@menu_router.message(F.text.in_(ORDER_LIST_TEXTS))
async def list_orders(message: Message, state: FSMContext) -> None:
    await show_order_list(message, state)


@menu_router.callback_query(F.data.startswith("lst:"))
async def order_list_callback(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    if message is None:
        await callback.answer()
        return
    data = callback.data or ""
    if data == "lst:list":
        await state.update_data(place="orders")
        await callback.answer()
        text, markup = await _order_list_markup()
        try:
            await message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest:
            await message.answer(text, reply_markup=markup or main_menu())
        return
    if data == "lst:pdf":
        await callback.answer()
        await _send_orders_pdf(message)
        return
    if data.startswith("lst:doc:"):
        raw_doc = data.removeprefix("lst:doc:")
        if not raw_doc.isdigit():
            await callback.answer()
            return
        await callback.answer()
        await _send_client_pdf(message, int(raw_doc))
        return
    action = _list_action(data)
    if action is not None:
        kind, raw_id = action
        if not raw_id.isdigit():
            await callback.answer()
            return
        order_id = int(raw_id)
        await callback.answer()
        if kind == "card":
            await _edit_order_card(message, state, order_id)
            return
        if kind == "pay":
            await state.update_data(card_back="order_card", order_id=order_id)
            await begin_payment(message, state, order_id)
            return
        if kind == "due":
            await state.update_data(
                due_order_id=order_id,
                order_id=order_id,
                place="due",
                card_back="order_card",
            )
            await state.set_state(DueForm.day)
            await message.answer(
                "Qolgan qarzni berish sanasini kiriting.",
                reply_markup=date_menu(),
            )
            return
        if kind == "close":
            await prompt_full_close(message, state, order_id, card_back="order_card")
            return
        if kind == "closeok":
            await finish_full_close(message, state, order_id)
            return
        if kind == "del":
            await prompt_delete(message, state, order_id, card_back="order_card")
            return
        if kind == "delok":
            await finish_delete(message, state, order_id)
            return
        return
    raw = data.removeprefix("lst:")
    if not raw.isdigit():
        await callback.answer()
        return
    await callback.answer()
    await _edit_order_card(message, state, int(raw))


def _list_action(data: str) -> tuple[str, str] | None:
    prefixes = (
        ("lst:closeok:", "closeok"),
        ("lst:delok:", "delok"),
        ("lst:close:", "close"),
        ("lst:del:", "del"),
        ("lst:card:", "card"),
        ("lst:pay:", "pay"),
        ("lst:due:", "due"),
    )
    for prefix, kind in prefixes:
        if data.startswith(prefix):
            return kind, data.removeprefix(prefix)
    return None


async def _edit_order_card(message: Message, state: FSMContext, order_id: int) -> None:
    payload = await _card_payload(order_id)
    if payload is None:
        await message.answer("Buyurtma topilmadi.")
        return
    text, markup = payload
    await state.update_data(place="order_card", order_id=order_id)
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=markup)


async def _send_client_pdf(message: Message, order_id: int) -> None:
    path: Path | None = None
    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)
        async with SessionLocal() as session:
            order = await session.get(Order, order_id)
            if order is None:
                await message.answer("Buyurtma topilmadi.")
                return
            paid = await paid_sum(session, order.id)
            page = ClientPage(
                number=order.order_number or f"#{order.id}",
                client_name=order.client_name,
                phone=order.phone or "",
                service=order.service or "",
                total_price=to_decimal(order.total_price),
                paid=paid,
                debt=debt_of(order.total_price, paid),
                event_date=order.event_date,
                due_date=order.payment_due_date,
                notes=order.notes or "",
                status=order.status or "",
            )
            filename = page.number.replace(" ", "_")
        path = write_client_pdf(page)
        await message.answer_document(
            FSInputFile(path, filename=f"FAZO_{filename}.pdf"),
            caption=f"FAZO CREATIVE GROUP — {page.client_name}",
        )
    except Exception as exc:
        logger.exception("Mijoz PDF yuborilmadi: %s", safe_db_message(exc))
        await message.answer("PDF tayyorlanmadi. Qayta urinib ko'ring.")
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


async def _send_orders_pdf(message: Message) -> None:
    path: Path | None = None
    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)
        async with SessionLocal() as session:
            lines = await all_order_lines(session)
        path = write_orders_pdf(lines)
        await message.answer_document(
            FSInputFile(path, filename="FAZO_buyurtmalar.pdf"),
            caption="FAZO CREATIVE GROUP — buyurtmalar",
        )
    except Exception as exc:
        logger.exception("PDF yuborilmadi: %s", safe_db_message(exc))
        await message.answer("PDF tayyorlanmadi. Qayta urinib ko'ring.")
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def _plain_wedding(label: str) -> str:
    parts = label.split(" ", 1)
    if len(parts) == 2:
        return parts[1]
    return label


async def _ask_event_date(message: Message, state: FSMContext) -> None:
    day = today_local()
    await state.set_state(OrderForm.event_date)
    await message.answer("Tadbir sanasini tanlang yoki yozing.", reply_markup=cancel_menu())
    await message.answer("Sanani tugmadan tanlang.", reply_markup=month_calendar(day.year, day.month))


async def _store_event_date(message: Message, state: FSMContext, day: date) -> None:
    await state.update_data(event_date=day.isoformat())
    await state.set_state(OrderForm.phone)
    await message.answer("Telefon raqamini kiriting.", reply_markup=cancel_menu())


@form_router.message(OrderForm.event_kind)
@form_router.message(OrderForm.event_kind_custom)
async def order_wedding_text(message: Message, state: FSMContext) -> None:
    name = message_text(message)
    if len(name) < 2 or len(name) > 200:
        await message.answer("To'y turini 2 tadan 200 tagacha belgi bilan yozing.")
        return
    await state.update_data(client_name=name)
    await _ask_event_date(message, state)


@form_router.callback_query(OrderForm.event_kind, F.data.startswith("toy:"))
@form_router.callback_query(OrderForm.event_kind_custom, F.data.startswith("toy:"))
async def order_wedding_pick(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    code = (callback.data or "").removeprefix("toy:")
    if message is None:
        await callback.answer()
        return
    if code == "boshqa":
        await state.set_state(OrderForm.event_kind_custom)
        await callback.answer()
        await message.answer("To'y turini yozing.", reply_markup=cancel_menu())
        return
    label = WEDDING_LABELS.get(code)
    if label is None:
        await callback.answer()
        return
    await state.update_data(client_name=_plain_wedding(label))
    await callback.answer()
    await _ask_event_date(message, state)


@form_router.message(OrderForm.event_date)
async def order_event_date(message: Message, state: FSMContext) -> None:
    ok, day = read_day(message_text(message), allow_empty=False)
    if not ok or day is None:
        await message.answer("Sanani tanlang yoki yozing.")
        return
    await _store_event_date(message, state, day)


@form_router.callback_query(OrderForm.event_date, F.data.startswith("cal:"))
async def order_event_calendar(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    if message is None:
        await callback.answer()
        return
    data = (callback.data or "").removeprefix("cal:")
    if data.startswith("m:"):
        raw = data.removeprefix("m:")
        year_text, _, month_text = raw.partition("-")
        if not year_text.isdigit() or not month_text.isdigit():
            await callback.answer()
            return
        await callback.answer()
        try:
            await message.edit_reply_markup(
                reply_markup=month_calendar(int(year_text), int(month_text))
            )
        except TelegramBadRequest:
            await message.answer(
                "Sanani tugmadan tanlang.",
                reply_markup=month_calendar(int(year_text), int(month_text)),
            )
        return
    if not data.startswith("d:"):
        await callback.answer()
        return
    raw_day = data.removeprefix("d:")
    if raw_day == "today":
        day = today_local()
    else:
        ok, day = read_day(raw_day, allow_empty=False)
        if not ok or day is None:
            await callback.answer()
            return
    await callback.answer()
    await _store_event_date(message, state, day)


@form_router.message(OrderForm.client_name)
async def order_name(message: Message, state: FSMContext) -> None:
    name = message_text(message)
    if len(name) < 2 or len(name) > 200:
        await message.answer("Ism-familiyani 2 tadan 200 tagacha belgi bilan kiriting.")
        return
    await state.update_data(client_name=name)
    await state.set_state(OrderForm.phone)
    await message.answer("Telefon raqamini kiriting.", reply_markup=cancel_menu())


@form_router.message(OrderForm.phone)
async def order_phone(message: Message, state: FSMContext) -> None:
    phone = valid_phone(message_text(message))
    if phone is None:
        await message.answer("Telefon raqamida kamida 7 ta raqam bo'lsin. Masalan: +998901234567")
        return
    await state.update_data(phone=phone, service_items=[])
    await state.set_state(OrderForm.service)
    await message.answer("Xizmat turini tanlang.", reply_markup=service_keyboard([]))


def _is_custom_code(action: str) -> bool:
    return len(action) > 1 and action.startswith("c") and action[1:].isdigit()


async def _ask_service_price(message: Message, state: FSMContext, code: str, label: str) -> None:
    await state.update_data(pending_code=code, pending_label=label)
    await state.set_state(OrderForm.service_price)
    await message.answer("Xizmat haqqini kiriting.", reply_markup=cancel_menu())


@form_router.message(OrderForm.service)
async def order_service_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(
        "Xizmat turini tanlang.",
        reply_markup=service_keyboard(_service_items(data)),
    )


@form_router.callback_query(OrderForm.service, F.data.startswith("svc:"))
@form_router.callback_query(OrderForm.service_custom, F.data.startswith("svc:"))
@form_router.callback_query(OrderForm.service_price, F.data.startswith("svc:"))
async def order_service_pick(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    action = (callback.data or "").removeprefix("svc:")
    data = await state.get_data()
    items = _service_items(data)
    if action == "done":
        service = _service_text(items)
        if not service:
            await callback.answer("Kamida bitta xizmat haqqini kiriting.", show_alert=True)
            return
        if len(service) > 500:
            await callback.answer("Xizmatlar ro'yxati juda uzun.", show_alert=True)
            return
        await callback.answer()
        await state.update_data(service=service, total_price=str(_service_total(items)))
        await state.set_state(OrderForm.prepaid)
        if message is not None:
            try:
                await message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass
            await message.answer(
                "Oldindan to'langan summani kiriting. Bo'lmasa tugmani bosing.",
                reply_markup=prepaid_menu(),
            )
        return
    if action == SERVICE_OTHER:
        await state.set_state(OrderForm.service_custom)
        await callback.answer()
        if message is not None:
            await message.answer("Xizmat nomini yozing.", reply_markup=cancel_menu())
        return
    if action in SERVICE_LABELS and action != SERVICE_OTHER:
        await callback.answer()
        if message is not None:
            await _ask_service_price(message, state, action, SERVICE_LABELS[action])
        return
    custom = next((item for item in items if item["code"] == action), None)
    if custom is None or not _is_custom_code(action):
        await callback.answer()
        return
    await callback.answer()
    if message is not None:
        await _ask_service_price(message, state, custom["code"], custom["label"])


@form_router.message(OrderForm.service_custom)
async def order_service_custom(message: Message, state: FSMContext) -> None:
    label = message_text(message)
    if len(label) < 2 or len(label) > 120:
        await message.answer("Xizmat nomini 2 tadan 120 tagacha belgi bilan yozing.")
        return
    data = await state.get_data()
    seq = int(data.get("custom_seq") or 0) + 1
    await state.update_data(custom_seq=seq)
    await _ask_service_price(message, state, f"c{seq}", label)


@form_router.message(OrderForm.service_price)
async def order_service_price(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message_text(message))
    if amount is None:
        await message.answer("Summani musbat son bilan kiriting.")
        return
    data = await state.get_data()
    code = str(data.get("pending_code") or "")
    label = str(data.get("pending_label") or "")
    if not code or not label:
        await state.set_state(OrderForm.service)
        await message.answer(
            "Xizmat turini tanlang.",
            reply_markup=service_keyboard(_service_items(data)),
        )
        return
    items = _with_price(_service_items(data), code, label, amount)
    await state.update_data(service_items=items, pending_code="", pending_label="")
    await state.set_state(OrderForm.service)
    await message.answer("Xizmat turini tanlang.", reply_markup=service_keyboard(items))


@form_router.message(OrderForm.prepaid)
async def order_prepaid(message: Message, state: FSMContext) -> None:
    raw = message_text(message)
    if raw in NO_PREPAY_TEXTS:
        prepaid = Decimal("0.00")
    else:
        parsed = parse_amount(raw, allow_zero=True)
        if parsed is None:
            await message.answer("Summani musbat son bilan kiriting.")
            return
        prepaid = parsed
    data = await state.get_data()
    total = to_decimal(data.get("total_price"))
    if prepaid > total:
        await message.answer(
            f"Oldindan to'lov kelishilgan narxdan katta. Eng ko'pi: {money(total)}"
        )
        return
    await state.update_data(prepaid=str(prepaid))
    await state.set_state(OrderForm.note)
    await message.answer("Izoh yozing yoki Izohsiz ni bosing.", reply_markup=note_menu())


@form_router.message(OrderForm.note)
async def order_note(message: Message, state: FSMContext) -> None:
    note = blank_note(message_text(message))
    if len(note) > 2000:
        await message.answer("Izoh 2000 belgidan oshmasin.")
        return
    await state.update_data(notes=note)
    await remember_key(state)
    await state.set_state(OrderForm.confirm)
    data = await state.get_data()
    await message.answer(
        _confirm_text(data),
        reply_markup=confirm_keyboard("order"),
    )


@form_router.message(OrderForm.confirm)
async def order_confirm_text(message: Message) -> None:
    await message.answer("Saqlash tugmasini bosing yoki Bekor qilishni tanlang.")


@form_router.callback_query(OrderForm.confirm, F.data == "save:order")
async def save_order(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    async with user_lock(actor_id(callback)):
        if await state.get_state() != OrderForm.confirm.state:
            await callback.answer("Bu amal allaqachon yakunlangan.", show_alert=True)
            return
        data = await state.get_data()
        if data.get("done"):
            await callback.answer("Buyurtma allaqachon saqlangan.", show_alert=True)
            return
        await callback.answer()
        await state.update_data(done=True)
        try:
            event_raw = str(data.get("event_date") or "")
            event_date = date.fromisoformat(event_raw) if event_raw else None
            async with unit_of_work() as session:
                order, created = await create_order(
                    session,
                    client_name=str(data["client_name"]),
                    phone=str(data["phone"]),
                    service=str(data["service"]),
                    total_price=to_decimal(data.get("total_price")),
                    prepaid=to_decimal(data.get("prepaid")),
                    event_date=event_date,
                    notes=str(data.get("notes") or ""),
                    idempotency_key=str(data["idempotency_key"]),
                )
                answer = saved_order_text(order, created=created)
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
        await message.answer(answer, reply_markup=main_menu())


@menu_router.callback_query(F.data.startswith("evt:"))
async def event_check_callback(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    if message is None:
        await callback.answer()
        return
    kind, _, raw = (callback.data or "").removeprefix("evt:").partition(":")
    if kind not in {"full", "half", "ask", "none"} or not raw.isdigit():
        await callback.answer()
        return
    order_id = int(raw)
    if kind == "ask":
        await state.update_data(place="event_pay", order_id=order_id, done=False)
        await remember_key(state)
        await state.set_state(OrderForm.event_collect)
        await callback.answer()
        await message.answer("Olingan summani kiriting.", reply_markup=cancel_menu())
        return
    await callback.answer()
    try:
        async with unit_of_work() as session:
            payment, order, created = await collect_event_share(
                session,
                order_id=order_id,
                mode=kind,
                paid_at=as_moment(today_local()),
                idempotency_key=f"evt-{kind}-{order_id}-{today_local().isoformat()}",
            )
            client = order.client_name
            amount = None if payment is None else payment.amount
    except UserFacingError as exc:
        await message.answer(h(exc.user_message))
        return
    if kind == "none":
        await message.answer(f"{h(client)} bo'yicha pul hali olinmadi deb belgilandi.")
        return
    prefix = "To'lov saqlandi." if created else "Bu to'lov avval saqlangan."
    await message.answer(f"<b>{h(prefix)}</b>\n{h(client)}\n{money(amount)}")


@form_router.message(OrderForm.event_collect)
async def event_collect_amount(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message_text(message))
    if amount is None:
        await message.answer("Summani musbat son bilan kiriting.")
        return
    data = await state.get_data()
    order_id = int(data.get("order_id") or 0)
    if order_id <= 0:
        await state.clear()
        await message.answer("Xizmat tanlanmagan.", reply_markup=main_menu())
        return
    key = str(data.get("idempotency_key") or "")
    if not key:
        key = await remember_key(state)
    try:
        async with unit_of_work() as session:
            payment, order, created = await add_payment(
                session,
                order_id=order_id,
                amount=amount,
                method="Naqd",
                note="Tadbir kuni",
                paid_at=as_moment(today_local()),
                idempotency_key=key,
            )
            await mark_event_checked(session, order.id)
            client = order.client_name
            paid = payment.amount
    except UserFacingError as exc:
        await message.answer(h(exc.user_message), reply_markup=cancel_menu())
        return
    prefix = "To'lov saqlandi." if created else "Bu to'lov avval saqlangan."
    await state.clear()
    await message.answer(
        f"<b>{h(prefix)}</b>\n{h(client)}\n{money(paid)}",
        reply_markup=main_menu(),
    )
