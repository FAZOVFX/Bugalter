from datetime import date

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from app.database import Order, SessionLocal, TeamMember
from app.formatting import as_moment, format_date, money, parse_amount, today_local, to_decimal
from app.handlers.access import actor_id
from app.handlers.support import (
    callback_message,
    message_text,
    read_day,
    remember_key,
    unit_of_work,
    valid_phone,
)
from app.handlers.views import h
from app.keyboards import (
    cancel_menu,
    date_menu,
    main_menu,
    member_action_keyboard,
    month_calendar,
    service_day_keyboard,
    team_debt_keyboard,
    team_debtors_keyboard,
    team_menu_keyboard,
    team_order_keyboard,
)
from app.locks import user_lock
from app.services import (
    UserFacingError,
    active_members,
    create_team_debt,
    debt_remaining,
    get_or_create_member,
    latest_orders,
    member_debts,
    members_with_balance,
    order_label,
    orders_on_date,
    pay_team_debt,
    record_member_cash,
    set_team_debt_date,
)
from app.texts import MY_DEBT_TEXTS, TEAM_TEXTS

menu_router = Router()
form_router = Router()


class TeamForm(StatesGroup):
    menu = State()
    new_name = State()
    amount = State()
    attach = State()
    pay_amount = State()
    new_phone = State()
    debt_date = State()
    cash_amount = State()
    cash_date = State()
    cash_order = State()


def _short_money(value: object) -> str:
    return money(value).removesuffix(" so'm")


def _person_label(name: str, phone: str, balance: object | None = None) -> str:
    parts = [name]
    if phone:
        parts.append(phone)
    if balance is not None and to_decimal(balance) > 0:
        parts.append(_short_money(balance))
    return f"👤 {' · '.join(parts)}"


async def _edit_or_send(message: Message, text: str, reply_markup) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=reply_markup)


async def _member_pairs() -> list[tuple[int, str]]:
    async with SessionLocal() as session:
        members = await active_members(session)
    return [(member.id, _person_label(member.name, member.phone or "")) for member in members]


async def show_team_menu(message: Message, state: FSMContext, *, edit: bool = False) -> None:
    await state.set_state(TeamForm.menu)
    await state.update_data(done=False, idempotency_key="", place="team", member_id=0)
    pairs = await _member_pairs()
    text = "<b>Hodimlar</b>\nHodimni tanlang yoki yangisini qo'shing."
    if not pairs:
        text = "<b>Hodimlar</b>\nHali hodim yo'q. Hodim qo'shishni bosing."
    markup = team_menu_keyboard(pairs)
    if edit:
        await _edit_or_send(message, text, markup)
        return
    await message.answer(text, reply_markup=markup)


async def show_debtors(message: Message, state: FSMContext, *, edit: bool = False) -> None:
    await state.set_state(TeamForm.menu)
    await state.update_data(place="debts", member_id=0, done=False)
    async with SessionLocal() as session:
        rows = await members_with_balance(session)
    buttons = [
        (member_id, _person_label(name, phone, balance))
        for member_id, name, phone, balance in rows
    ]
    text = "<b>Qarzlarim</b>\nHodimni tanlang."
    if not buttons:
        text = "<b>Qarzlarim</b>\nHali hodim yo'q. Avval Hodimlar bo'limidan qo'shing."
    markup = team_debtors_keyboard(buttons)
    if edit:
        await _edit_or_send(message, text, markup)
        return
    await message.answer(text, reply_markup=markup)


async def show_member_card(
    message: Message,
    state: FSMContext,
    member_id: int,
    *,
    note: str = "",
) -> None:
    await state.set_state(TeamForm.menu)
    await state.update_data(member_id=member_id, place="member", section="team", done=False)
    async with SessionLocal() as session:
        member = await session.get(TeamMember, member_id)
    if member is None:
        await message.answer("Hodim topilmadi.")
        await show_team_menu(message, state)
        return
    title = _person_label(member.name, member.phone or "")
    text = f"<b>{h(title)}</b>\nQarz qo'shish yoki pul berishni tanlang."
    if note:
        text = f"<b>{h(title)}</b>\n{h(note)}"
    await message.answer(text, reply_markup=member_action_keyboard(member_id))


async def show_member_debts(
    message: Message,
    state: FSMContext,
    member_id: int,
    *,
    back: str = "tm:debts",
    back_label: str = "⬅️ Qarzlarim",
) -> None:
    await state.set_state(TeamForm.menu)
    await state.update_data(member_id=member_id, place="debt_member", done=False)
    async with SessionLocal() as session:
        member = await session.get(TeamMember, member_id)
        debts = await member_debts(session, member_id)
        lines: list[str] = []
        buttons: list[tuple[int, str, str]] = []
        for debt in debts:
            left = debt_remaining(debt)
            opened = format_date(debt.opened_on)
            work = debt.work_for or "Buyurtmaga biriktirilmagan"
            lines.append(f"{opened}\n{h(work)}\nQoldiq: {money(left)}")
            buttons.append((debt.id, f"📅 {opened}", f"💸 Berish · {_short_money(left)}"))
        person = member.name if member is not None else "Hodim"
        phone = member.phone if member is not None else ""
    title = _person_label(person, phone or "")
    if not lines:
        await _edit_or_send(
            message,
            f"<b>{h(title)}</b>\nOchiq qarz yo'q. Pul berish orqali yozishingiz mumkin.",
            team_debt_keyboard(
                [],
                back=back,
                back_label=back_label,
                pay_member_id=member_id,
            ),
        )
        return
    await _edit_or_send(
        message,
        f"<b>{h(title)}</b>\nPul berish ochiq qarz bo'lmasa ham yoziladi.\n\n"
        + "\n\n".join(lines),
        team_debt_keyboard(
            buttons,
            back=back,
            back_label=back_label,
            pay_member_id=member_id,
        ),
    )


@menu_router.message(Command("team"))
@menu_router.message(F.text.in_(TEAM_TEXTS))
async def start_team(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_team_menu(message, state)


@menu_router.message(Command("mydebts"))
@menu_router.message(F.text.in_(MY_DEBT_TEXTS))
async def start_my_debts(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_debtors(message, state)


@form_router.message(TeamForm.menu)
async def team_menu_text(message: Message, state: FSMContext) -> None:
    await show_team_menu(message, state)


@form_router.message(TeamForm.new_name)
async def team_new_name(message: Message, state: FSMContext) -> None:
    name = message_text(message)
    if len(name) < 2 or len(name) > 200:
        await message.answer("Ismni 2 tadan 200 tagacha belgi bilan kiriting.")
        return
    await state.update_data(person_name=name, place="team_add")
    await state.set_state(TeamForm.new_phone)
    await message.answer("Hodimning telefon raqamini kiriting.", reply_markup=cancel_menu())


@form_router.message(TeamForm.new_phone)
async def team_new_phone(message: Message, state: FSMContext) -> None:
    phone = valid_phone(message_text(message))
    if phone is None:
        await message.answer("Telefon raqamida kamida 7 ta raqam bo'lsin.")
        return
    data = await state.get_data()
    name = str(data.get("person_name") or "")
    async with unit_of_work() as session:
        existing = await session.scalar(
            select(TeamMember).where(func.lower(TeamMember.name) == name.lower())
        )
        if existing is not None:
            existing.phone = phone
            person = existing.name
            created = False
        else:
            member = await get_or_create_member(session, name)
            member.phone = phone
            person = member.name
            created = True
    notice = "Hodim saqlandi." if created else "Bu hodim allaqachon bor. Telefon yangilandi."
    await message.answer(f"{h(notice)}\n{h(person)}\n{h(phone)}")
    await show_team_menu(message, state)


@form_router.message(TeamForm.debt_date)
async def team_debt_date(message: Message, state: FSMContext) -> None:
    ok, day = read_day(message_text(message), allow_empty=False)
    if not ok or day is None:
        await message.answer("Sanani tanlang yoki yozing.")
        return
    data = await state.get_data()
    debt_id = int(data.get("debt_id") or 0)
    member_id = int(data.get("member_id") or 0)
    if debt_id <= 0 or member_id <= 0:
        await show_debtors(message, state)
        return
    try:
        async with unit_of_work() as session:
            await set_team_debt_date(session, debt_id, day)
    except UserFacingError as exc:
        await message.answer(h(exc.user_message), reply_markup=cancel_menu())
        return
    await message.answer(f"Qarz sanasi: {format_date(day)}")
    await _reopen_member_debts(message, state, member_id, data)


@form_router.message(TeamForm.amount)
async def team_amount(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message_text(message))
    if amount is None:
        await message.answer("Summani musbat son bilan kiriting.")
        return
    await state.update_data(amount=str(amount), done=False, place="member_form")
    await remember_key(state)
    await state.set_state(TeamForm.attach)
    async with SessionLocal() as session:
        orders = await latest_orders(session)
    buttons = [
        (order.id, f"{order.order_number or '#' + str(order.id)} — {order.client_name}")
        for order in orders
    ]
    await message.answer("Buyurtmani tanlang.", reply_markup=team_order_keyboard(buttons))


@form_router.message(TeamForm.attach)
async def team_attach_text(message: Message) -> None:
    await message.answer("Buyurtmani tugmadan tanlang.")


async def _ask_cash_date(message: Message) -> None:
    day = today_local()
    await message.answer("Qaysi sana uchun ekanini tanlang yoki yozing.", reply_markup=cancel_menu())
    await message.answer("Sanani tugmadan tanlang.", reply_markup=month_calendar(day.year, day.month))


async def _show_services_on_date(message: Message, state: FSMContext, day) -> None:
    async with SessionLocal() as session:
        orders = await orders_on_date(session, day)
    if not orders:
        await message.answer("Bu sanada xizmat topilmadi. Boshqa sanani tanlang.")
        return
    buttons = []
    for order in orders:
        service = (order.service or "").split(",")[0].strip() or "Xizmat"
        buttons.append((order.id, f"{order.client_name} · {service}"))
    await state.update_data(cash_date=day.isoformat())
    await state.set_state(TeamForm.cash_order)
    await message.answer("Shu sanadagi xizmatni tanlang.", reply_markup=service_day_keyboard(buttons))


async def _save_cash(message: Message, state: FSMContext, order_id: int) -> None:
    async with user_lock(actor_id(message)):
        data = await state.get_data()
        if data.get("done"):
            await message.answer("Bu to'lov allaqachon saqlangan.")
            return
        member_id = int(data.get("member_id") or 0)
        amount = to_decimal(data.get("amount"))
        raw_day = str(data.get("cash_date") or "")
        if member_id <= 0 or amount <= 0 or not raw_day:
            await show_debtors(message, state)
            return
        await state.update_data(done=True)
        key = str(data.get("idempotency_key") or "")
        if not key:
            key = await remember_key(state)
        try:
            paid_on = date.fromisoformat(raw_day)
            async with unit_of_work() as session:
                created = await record_member_cash(
                    session,
                    member_id=member_id,
                    order_id=order_id,
                    amount=amount,
                    paid_at=as_moment(paid_on),
                    idempotency_key=key,
                )
        except UserFacingError as exc:
            await state.update_data(done=False)
            await message.answer(h(exc.user_message), reply_markup=cancel_menu())
            return
        except Exception:
            await state.update_data(done=False)
            raise
    prefix = "Pul yozildi." if created else "Bu to'lov avval saqlangan."
    await message.answer(f"<b>{h(prefix)}</b>\n{money(amount)}")
    await show_member_debts(message, state, member_id)


@form_router.message(TeamForm.cash_amount)
async def team_cash_amount(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message_text(message))
    if amount is None:
        await message.answer("Summani musbat son bilan kiriting.")
        return
    await state.update_data(amount=str(amount), place="cash", done=False)
    await remember_key(state)
    await state.set_state(TeamForm.cash_date)
    await _ask_cash_date(message)


@form_router.message(TeamForm.cash_date)
async def team_cash_date(message: Message, state: FSMContext) -> None:
    ok, day = read_day(message_text(message), allow_empty=False)
    if not ok or day is None:
        await message.answer("Sanani tanlang yoki yozing.")
        return
    await _show_services_on_date(message, state, day)


@form_router.callback_query(TeamForm.cash_date, F.data.startswith("cal:"))
async def team_cash_calendar(callback: CallbackQuery, state: FSMContext) -> None:
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
    await _show_services_on_date(message, state, day)


@form_router.message(TeamForm.cash_order)
async def team_cash_order_text(message: Message) -> None:
    await message.answer("Shu sanadagi xizmatni tugmadan tanlang.")


@form_router.message(TeamForm.pay_amount)
async def team_pay_amount(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message_text(message))
    if amount is None:
        await message.answer("Summani musbat son bilan kiriting.")
        return
    async with user_lock(actor_id(message)):
        if await state.get_state() != TeamForm.pay_amount.state:
            return
        data = await state.get_data()
        debt_id = int(data.get("debt_id") or 0)
        member_id = int(data.get("member_id") or 0)
        if debt_id <= 0:
            await show_team_menu(message, state)
            return
        if data.get("done"):
            await message.answer("Bu to'lov allaqachon saqlangan.")
            return
        await state.update_data(done=True)
        try:
            async with unit_of_work() as session:
                payment, debt, created = await pay_team_debt(
                    session,
                    debt_id=debt_id,
                    amount=amount,
                    paid_at=as_moment(today_local()),
                    idempotency_key=str(data["idempotency_key"]),
                )
                left = debt_remaining(debt)
                paid = payment.amount
        except UserFacingError as exc:
            await state.update_data(done=False)
            await message.answer(h(exc.user_message), reply_markup=cancel_menu())
            return
        except Exception:
            await state.update_data(done=False)
            raise
    if to_decimal(left) <= 0:
        prefix = "Qarz yopildi." if created else "Bu to'lov avval saqlangan."
        await message.answer(f"<b>{h(prefix)}</b>\n{money(paid)}")
    else:
        prefix = "Berildi." if created else "Bu to'lov avval saqlangan, qayta yozilmadi."
        await message.answer(f"<b>{h(prefix)}</b>\n{money(paid)}\nQoldiq: {money(left)}")
    await _reopen_member_debts(message, state, member_id, data)


async def _reopen_member_debts(
    message: Message,
    state: FSMContext,
    member_id: int,
    data: dict[str, object],
) -> None:
    if data.get("pay_back") == "give":
        await show_member_debts(
            message,
            state,
            member_id,
            back=f"tma:{member_id}",
            back_label="⬅️ Hodim",
        )
        await state.update_data(place="give")
        return
    await show_member_debts(message, state, member_id)


@form_router.callback_query(StateFilter(TeamForm), F.data.startswith("tm"))
async def team_callback(callback: CallbackQuery, state: FSMContext) -> None:
    message = await callback_message(callback)
    if message is None:
        await callback.answer()
        return
    data = callback.data or ""
    if data == "tm:menu":
        await callback.answer()
        await show_team_menu(message, state, edit=True)
        return
    if data == "tm:add":
        await state.set_state(TeamForm.new_name)
        await state.update_data(place="team_add")
        await callback.answer()
        await message.answer("Hodimning ism-familiyasini kiriting.", reply_markup=cancel_menu())
        return
    if data == "tm:debts":
        await callback.answer()
        await show_debtors(message, state, edit=True)
        return
    if data.startswith("tmds:"):
        raw = data.removeprefix("tmds:")
        if not raw.isdigit():
            await callback.answer()
            return
        current = await state.get_data()
        pay_back = "give" if current.get("place") == "give" else "debt_member"
        await state.update_data(debt_id=int(raw), place="pay", pay_back=pay_back)
        await state.set_state(TeamForm.debt_date)
        await callback.answer()
        await message.answer(
            "Qarz sanasini kiriting.",
            reply_markup=date_menu(),
        )
        return
    if data.startswith("tmd:"):
        raw = data.removeprefix("tmd:")
        if not raw.isdigit():
            await callback.answer()
            return
        await callback.answer()
        await show_member_debts(message, state, int(raw))
        return
    if data.startswith("tmp:"):
        raw = data.removeprefix("tmp:")
        if not raw.isdigit():
            await callback.answer()
            return
        current = await state.get_data()
        pay_back = "give" if current.get("place") == "give" else "debt_member"
        await state.update_data(debt_id=int(raw), done=False, place="pay", pay_back=pay_back)
        await remember_key(state)
        await state.set_state(TeamForm.pay_amount)
        await callback.answer()
        await message.answer("Pul summasini kiriting.", reply_markup=cancel_menu())
        return
    if data.startswith("tma:"):
        raw = data.removeprefix("tma:")
        if not raw.isdigit():
            await callback.answer()
            return
        await callback.answer()
        await show_member_card(message, state, int(raw))
        return
    if data.startswith("tmq:"):
        raw = data.removeprefix("tmq:")
        if not raw.isdigit():
            await callback.answer()
            return
        await state.update_data(member_id=int(raw), place="member_form")
        await state.set_state(TeamForm.amount)
        await callback.answer()
        await message.answer("Qarz summasini kiriting.", reply_markup=cancel_menu())
        return
    if data.startswith("tmc:"):
        raw = data.removeprefix("tmc:")
        if not raw.isdigit():
            await callback.answer()
            return
        await state.update_data(member_id=int(raw), place="cash", done=False)
        await state.set_state(TeamForm.cash_amount)
        await callback.answer()
        await message.answer("Pul summasini kiriting.", reply_markup=cancel_menu())
        return
    if data.startswith("tmx:"):
        raw = data.removeprefix("tmx:")
        if not raw.isdigit():
            await callback.answer()
            return
        await callback.answer()
        await _save_cash(message, state, int(raw))
        return
    if data.startswith("tmg:"):
        raw = data.removeprefix("tmg:")
        if not raw.isdigit():
            await callback.answer()
            return
        member_id = int(raw)
        await callback.answer()
        async with SessionLocal() as session:
            debts = await member_debts(session, member_id)
        if not debts:
            await show_member_card(message, state, member_id, note="Ochiq qarz yo'q.")
            return
        await show_member_debts(
            message,
            state,
            member_id,
            back=f"tma:{member_id}",
            back_label="⬅️ Hodim",
        )
        await state.update_data(place="give")
        return
    if data.startswith("tmo:"):
        await _attach_order(callback, state, message, data.removeprefix("tmo:"))
        return
    raw = data.removeprefix("tm:")
    if not raw.isdigit():
        await callback.answer()
        return
    await callback.answer()
    await show_member_card(message, state, int(raw))


async def _attach_order(
    callback: CallbackQuery,
    state: FSMContext,
    message: Message,
    raw: str,
) -> None:
    if not raw.isdigit():
        await callback.answer()
        return
    async with user_lock(actor_id(callback)):
        if await state.get_state() != TeamForm.attach.state:
            await callback.answer("Bu amal allaqachon yakunlangan.", show_alert=True)
            return
        data = await state.get_data()
        if data.get("done"):
            await callback.answer("Qarz allaqachon saqlangan.", show_alert=True)
            return
        await callback.answer()
        await state.update_data(done=True)
        order_id = int(raw)
        try:
            async with unit_of_work() as session:
                work_for = ""
                linked_id = None
                if order_id:
                    order = await session.get(Order, order_id)
                    if order is None:
                        raise UserFacingError("Buyurtma topilmadi.")
                    work_for = order_label(order)
                    linked_id = order.id
                debt, created = await create_team_debt(
                    session,
                    member_id=int(data["member_id"]),
                    amount=to_decimal(data.get("amount")),
                    order_id=linked_id,
                    work_for=work_for,
                    opened_on=today_local(),
                    idempotency_key=str(data["idempotency_key"]),
                )
                opened = format_date(debt.opened_on)
                amount = debt.amount
                linked = debt.work_for or "Buyurtmaga biriktirilmagan"
        except UserFacingError as exc:
            await state.update_data(done=False)
            await message.answer(h(exc.user_message), reply_markup=cancel_menu())
            return
        except Exception:
            await state.update_data(done=False)
            raise
    prefix = "Qarz saqlandi." if created else "Bu qarz avval saqlangan, qayta yozilmadi."
    await message.answer(
        f"<b>{h(prefix)}</b>\n"
        f"Sana: {h(opened)}\n"
        f"Buyurtma: {h(linked)}\n"
        f"Summa: {money(amount)}\n"
        "Pul hali berilmagan. Berish uchun Qarzlarimni oching.",
        reply_markup=main_menu(),
    )
    await show_team_menu(message, state)
