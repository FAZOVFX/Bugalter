from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.handlers.expenses import show_expense_menu
from app.handlers.orders import show_order_card, show_order_list
from app.handlers.reports_bot import show_debtor_card, show_debtor_list
from app.handlers.team import show_debtors, show_member_card, show_member_debts, show_team_menu
from app.keyboards import main_menu

_PARENT = {
    "main": "main",
    "orders": "main",
    "order_card": "orders",
    "order": "main",
    "team": "main",
    "member": "team",
    "team_add": "team",
    "member_form": "member",
    "debts": "main",
    "debt_member": "debts",
    "give": "member",
    "pay": "debt_member",
    "debtors": "main",
    "debtor": "debtors",
    "payment": "debtor",
    "due": "debtor",
    "order_close": "order_card",
    "order_delete": "order_card",
    "expense": "main",
    "expense_form": "expense",
    "cash": "debt_member",
    "event_pay": "order_card",
}


async def return_to_section(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    place = str(data.get("place") or "main")
    if place == "pay":
        parent = str(data.get("pay_back") or "debt_member")
    elif place in {"payment", "due", "order_close", "order_delete"}:
        parent = str(data.get("card_back") or _PARENT.get(place, "main"))
    else:
        parent = _PARENT.get(place, "main")
    member_id = int(data.get("member_id") or 0)
    order_id = int(data.get("order_id") or data.get("due_order_id") or 0)
    await _open(message, state, parent, member_id, order_id)


async def _open(
    message: Message,
    state: FSMContext,
    place: str,
    member_id: int,
    order_id: int,
) -> None:
    if place == "orders":
        await show_order_list(message, state)
        return
    if place == "order_card" and order_id:
        await show_order_card(message, state, order_id)
        return
    if place == "team":
        await show_team_menu(message, state)
        return
    if place == "member" and member_id:
        await show_member_card(message, state, member_id)
        return
    if place == "debts":
        await show_debtors(message, state)
        return
    if place == "debt_member" and member_id:
        await show_member_debts(message, state, member_id)
        return
    if place == "give" and member_id:
        await show_member_debts(
            message,
            state,
            member_id,
            back=f"tma:{member_id}",
            back_label="⬅️ Hodim",
        )
        await state.update_data(place="give")
        return
    if place == "debtors":
        await show_debtor_list(message, state)
        return
    if place == "debtor" and order_id:
        await state.clear()
        await state.update_data(place="debtor", order_id=order_id)
        await show_debtor_card(message, order_id)
        return
    if place == "expense":
        await show_expense_menu(message, state)
        return
    await state.clear()
    await message.answer("Kerakli bo'limni menyudan tanlang.", reply_markup=main_menu())
