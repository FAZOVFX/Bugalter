from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Expense, Order, Payment, TeamDebt, TeamMember, TeamPayment
from app.formatting import (
    as_moment,
    debt_of,
    like_pattern,
    money,
    now_local,
    quantize_money,
    status_for,
    today_local,
    to_decimal,
)

class UserFacingError(Exception):
    def __init__(self, message: str) -> None:
        self.user_message = message
        super().__init__(message)


def order_label(order: Order) -> str:
    number = order.order_number or f"#{order.id}"
    return f"{number} — {order.client_name}"


async def paid_sum(session: AsyncSession, order_id: int) -> Decimal:
    value = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.order_id == order_id)
    )
    return to_decimal(value)


async def refresh_order_balance(session: AsyncSession, order: Order) -> Decimal:
    paid = await paid_sum(session, order.id)
    order.paid_amount = paid
    order.status = status_for(order.total_price, paid)
    return paid


async def find_by_key(session: AsyncSession, model: type, key: str):
    column = model.idempotency_key
    return await session.scalar(select(model).where(column == key))


async def search_orders(session: AsyncSession, query: str) -> list[Order]:
    cleaned = query.strip()
    if not cleaned:
        return []

    exact = await session.scalar(
        select(Order).where(func.lower(Order.order_number) == cleaned.lower())
    )
    if exact is not None:
        return [exact]

    if cleaned.isdigit():
        by_id = await session.get(Order, int(cleaned))
        if by_id is not None:
            return [by_id]

    found = (
        await session.scalars(
            select(Order)
            .where(Order.client_name.ilike(like_pattern(cleaned), escape="\\"))
            .order_by(Order.id.desc())
            .limit(11)
        )
    ).all()
    return list(found)


async def create_order(
    session: AsyncSession,
    *,
    client_name: str,
    phone: str,
    service: str,
    total_price: Decimal,
    prepaid: Decimal,
    event_date: date | None,
    notes: str,
    idempotency_key: str,
) -> tuple[Order, bool]:
    existing = await find_by_key(session, Order, idempotency_key)
    if existing is not None:
        return existing, False

    if prepaid > total_price:
        raise UserFacingError("Oldindan to'lov kelishilgan narxdan katta bo'lishi mumkin emas.")

    order = Order(
        client_name=client_name,
        phone=phone,
        service=service,
        total_price=total_price,
        paid_amount=Decimal("0.00"),
        status="Yangi",
        event_date=event_date,
        notes=notes,
        idempotency_key=idempotency_key,
    )
    try:
        async with session.begin_nested():
            session.add(order)
            await session.flush()
    except IntegrityError:
        existing = await find_by_key(session, Order, idempotency_key)
        if existing is not None:
            return existing, False
        raise

    order.order_number = f"FCG-{order.id:05d}"
    if prepaid > 0:
        session.add(
            Payment(
                order_id=order.id,
                amount=prepaid,
                paid_at=now_local(),
                method="Oldindan",
                note="Oldindan to'lov",
                idempotency_key=f"{idempotency_key}:prepaid",
            )
        )
        await session.flush()
    await refresh_order_balance(session, order)
    return order, True


async def add_payment(
    session: AsyncSession,
    *,
    order_id: int,
    amount: Decimal,
    method: str,
    note: str,
    paid_at: datetime,
    idempotency_key: str,
) -> tuple[Payment, Order, bool]:
    existing = await find_by_key(session, Payment, idempotency_key)
    if existing is not None:
        order = await session.get(Order, existing.order_id)
        if order is None:
            raise UserFacingError("To'lovga bog'langan buyurtma topilmadi.")
        return existing, order, False

    order = await session.get(Order, order_id, with_for_update=True)
    if order is None:
        raise UserFacingError("Buyurtma topilmadi. Qaytadan boshlang.")

    paid = await paid_sum(session, order.id)
    remaining = debt_of(order.total_price, paid)
    if remaining <= 0:
        raise UserFacingError("Bu buyurtmaning qarzi yo'q. To'lov qabul qilinmadi.")
    if amount > remaining:
        raise UserFacingError(
            f"Qolgan qarz {money(remaining)}. "
            "Shu summadan katta to'lov qabul qilinmaydi."
        )

    payment = Payment(
        order_id=order.id,
        amount=amount,
        paid_at=paid_at,
        method=method,
        note=note,
        idempotency_key=idempotency_key,
    )
    try:
        async with session.begin_nested():
            session.add(payment)
            await session.flush()
    except IntegrityError:
        existing = await find_by_key(session, Payment, idempotency_key)
        if existing is not None:
            order = await session.get(Order, existing.order_id)
            if order is None:
                raise UserFacingError("To'lovga bog'langan buyurtma topilmadi.")
            return existing, order, False
        raise
    await refresh_order_balance(session, order)
    return payment, order, True


async def settle_order(
    session: AsyncSession,
    *,
    order_id: int,
    paid_at: datetime,
    idempotency_key: str,
) -> tuple[Payment, Order, bool]:
    order = await session.get(Order, order_id)
    if order is None:
        raise UserFacingError("Buyurtma topilmadi.")
    remaining = debt_of(order.total_price, await paid_sum(session, order.id))
    if remaining <= 0:
        raise UserFacingError("Bu mijoz allaqachon to'liq yopilgan.")
    return await add_payment(
        session,
        order_id=order.id,
        amount=remaining,
        method="Naqd",
        note="To'liq to'lov",
        paid_at=paid_at,
        idempotency_key=idempotency_key,
    )


async def delete_order(session: AsyncSession, order_id: int) -> str:
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None:
        raise UserFacingError("Buyurtma topilmadi.")
    client = order.client_name
    await session.execute(delete(Payment).where(Payment.order_id == order.id))
    await session.execute(
        update(TeamPayment)
        .where(TeamPayment.order_id == order.id)
        .values(order_id=None)
    )
    await session.execute(
        update(TeamDebt).where(TeamDebt.order_id == order.id).values(order_id=None)
    )
    await session.delete(order)
    await session.flush()
    return client


async def add_expense(
    session: AsyncSession,
    *,
    category: str,
    amount: Decimal,
    description: str,
    spent_at: datetime,
    idempotency_key: str,
) -> tuple[Expense, bool]:
    existing = await find_by_key(session, Expense, idempotency_key)
    if existing is not None:
        return existing, False
    expense = Expense(
        category=category,
        amount=amount,
        description=description,
        spent_at=spent_at,
        idempotency_key=idempotency_key,
    )
    try:
        async with session.begin_nested():
            session.add(expense)
            await session.flush()
    except IntegrityError:
        existing = await find_by_key(session, Expense, idempotency_key)
        if existing is not None:
            return existing, False
        raise
    return expense, True


async def get_or_create_member(session: AsyncSession, name: str) -> TeamMember:
    existing = await session.scalar(
        select(TeamMember).where(func.lower(TeamMember.name) == name.lower())
    )
    if existing is not None:
        return existing
    member = TeamMember(name=name, role="Xodim", active=True)
    try:
        async with session.begin_nested():
            session.add(member)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(TeamMember).where(func.lower(TeamMember.name) == name.lower())
        )
        if existing is not None:
            return existing
        raise
    return member


async def resolve_work(
    session: AsyncSession,
    text_value: str,
) -> tuple[str, int | None]:
    cleaned = text_value.strip()
    if not cleaned:
        return "", None
    matches = await search_orders(session, cleaned)
    exact = None
    lowered = cleaned.lower()
    for order in matches:
        number = (order.order_number or "").lower()
        if number == lowered or (cleaned.isdigit() and order.id == int(cleaned)):
            exact = order
            break
    if exact is None and len(matches) == 1 and lowered == matches[0].client_name.lower():
        exact = matches[0]
    if exact is None:
        return cleaned, None
    label = order_label(exact)
    return label, exact.id


async def add_team_payment(
    session: AsyncSession,
    *,
    person_name: str,
    amount: Decimal,
    work_for: str,
    order_id: int | None,
    note: str,
    paid_at: datetime,
    idempotency_key: str,
) -> tuple[TeamPayment, TeamMember, bool]:
    existing = await find_by_key(session, TeamPayment, idempotency_key)
    if existing is not None:
        member = await session.get(TeamMember, existing.member_id)
        if member is None:
            raise UserFacingError("Jamoa a'zosi topilmadi.")
        return existing, member, False

    member = await get_or_create_member(session, person_name)
    if order_id is not None:
        order = await session.get(Order, order_id)
        if order is None:
            order_id = None
    payment = TeamPayment(
        member_id=member.id,
        order_id=order_id,
        amount=amount,
        paid_at=paid_at,
        note=note,
        work_for=work_for,
        idempotency_key=idempotency_key,
    )
    try:
        async with session.begin_nested():
            session.add(payment)
            await session.flush()
    except IntegrityError:
        existing = await find_by_key(session, TeamPayment, idempotency_key)
        if existing is not None:
            member = await session.get(TeamMember, existing.member_id)
            if member is None:
                raise UserFacingError("Jamoa a'zosi topilmadi.")
            return existing, member, False
        raise
    return payment, member, True


def moment_on(day: date) -> datetime:
    return as_moment(day)


async def latest_orders(session: AsyncSession, limit: int = 20) -> list[Order]:
    found = await session.scalars(select(Order).order_by(Order.id.desc()).limit(limit))
    return list(found)


async def active_members(session: AsyncSession) -> list[TeamMember]:
    found = await session.scalars(
        select(TeamMember).where(TeamMember.active.is_(True)).order_by(TeamMember.name)
    )
    return list(found)


def debt_remaining(debt: TeamDebt) -> Decimal:
    return debt_of(debt.amount, debt.paid_amount)


async def create_team_debt(
    session: AsyncSession,
    *,
    member_id: int,
    amount: Decimal,
    order_id: int | None,
    work_for: str,
    opened_on: date,
    idempotency_key: str,
) -> tuple[TeamDebt, bool]:
    existing = await find_by_key(session, TeamDebt, idempotency_key)
    if existing is not None:
        return existing, False
    member = await session.get(TeamMember, member_id)
    if member is None:
        raise UserFacingError("Hodim topilmadi.")
    if order_id is not None and await session.get(Order, order_id) is None:
        raise UserFacingError("Buyurtma topilmadi.")
    debt = TeamDebt(
        member_id=member_id,
        order_id=order_id,
        amount=amount,
        paid_amount=Decimal("0.00"),
        opened_on=opened_on,
        work_for=work_for,
        note="",
        idempotency_key=idempotency_key,
    )
    try:
        async with session.begin_nested():
            session.add(debt)
            await session.flush()
    except IntegrityError:
        existing = await find_by_key(session, TeamDebt, idempotency_key)
        if existing is not None:
            return existing, False
        raise
    return debt, True


async def orders_on_date(session: AsyncSession, day: date) -> list[Order]:
    found = await session.scalars(
        select(Order).where(Order.event_date == day).order_by(Order.id.desc())
    )
    return list(found)


async def record_member_cash(
    session: AsyncSession,
    *,
    member_id: int,
    order_id: int,
    amount: Decimal,
    paid_at: datetime,
    idempotency_key: str,
) -> bool:
    member = await session.get(TeamMember, member_id)
    if member is None:
        raise UserFacingError("Hodim topilmadi.")
    order = await session.get(Order, order_id)
    if order is None:
        raise UserFacingError("Bu sanadagi xizmat topilmadi.")
    leftover = to_decimal(amount)
    if leftover <= 0:
        raise UserFacingError("Summani musbat son bilan kiriting.")
    created_any = False
    debts = [
        debt
        for debt in await member_debts(session, member_id)
        if debt.order_id == order.id
    ]
    for debt in debts:
        if leftover <= 0:
            break
        room = debt_remaining(debt)
        take = min(leftover, room)
        if take <= 0:
            continue
        _, _, created = await pay_team_debt(
            session,
            debt_id=debt.id,
            amount=take,
            paid_at=paid_at,
            idempotency_key=f"{idempotency_key}:d{debt.id}",
        )
        leftover -= take
        created_any = created_any or created
    if leftover > 0:
        _, _, created = await add_team_payment(
            session,
            person_name=member.name,
            amount=leftover,
            work_for=order_label(order),
            order_id=order.id,
            note="Xizmat kuni",
            paid_at=paid_at,
            idempotency_key=f"{idempotency_key}:cash",
        )
        created_any = created_any or created
    return created_any


async def mark_event_checked(session: AsyncSession, order_id: int) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise UserFacingError("Buyurtma topilmadi.")
    order.event_checked_on = today_local()
    return order


async def collect_event_share(
    session: AsyncSession,
    *,
    order_id: int,
    mode: str,
    paid_at: datetime,
    idempotency_key: str,
) -> tuple[Payment | None, Order, bool]:
    order = await session.get(Order, order_id)
    if order is None:
        raise UserFacingError("Buyurtma topilmadi.")
    if mode == "none":
        await mark_event_checked(session, order.id)
        return None, order, True
    remaining = debt_of(order.total_price, await paid_sum(session, order.id))
    if remaining <= 0:
        await mark_event_checked(session, order.id)
        raise UserFacingError("Bu xizmat bo'yicha qarz yo'q.")
    if mode == "full":
        amount = remaining
        note = "To'liq to'lov"
    elif mode == "half":
        amount = quantize_money(remaining / Decimal("2"))
        if amount <= 0:
            amount = remaining
        note = "Yarim to'lov"
    else:
        raise UserFacingError("To'lov turi noto'g'ri.")
    payment, updated, created = await add_payment(
        session,
        order_id=order.id,
        amount=amount,
        method="Naqd",
        note=note,
        paid_at=paid_at,
        idempotency_key=idempotency_key,
    )
    await mark_event_checked(session, updated.id)
    return payment, updated, created


async def member_debts(session: AsyncSession, member_id: int) -> list[TeamDebt]:
    remaining = TeamDebt.amount - TeamDebt.paid_amount
    found = await session.scalars(
        select(TeamDebt)
        .where(TeamDebt.member_id == member_id, remaining > 0)
        .order_by(TeamDebt.opened_on, TeamDebt.id)
    )
    return list(found)


async def members_with_balance(
    session: AsyncSession,
) -> list[tuple[int, str, str, Decimal]]:
    members = await active_members(session)
    rows: list[tuple[int, str, str, Decimal]] = []
    for member in members:
        debts = await member_debts(session, member.id)
        balance = Decimal("0.00")
        for debt in debts:
            balance += debt_remaining(debt)
        rows.append((member.id, member.name, member.phone or "", to_decimal(balance)))
    return rows


async def set_team_debt_date(session: AsyncSession, debt_id: int, day: date) -> TeamDebt:
    debt = await session.get(TeamDebt, debt_id)
    if debt is None:
        raise UserFacingError("Qarz topilmadi.")
    if debt_remaining(debt) <= 0:
        raise UserFacingError("Bu qarz yopilgan.")
    debt.opened_on = day
    return debt


async def set_payment_due(session: AsyncSession, order_id: int, day: date) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise UserFacingError("Buyurtma topilmadi.")
    order.payment_due_date = day
    order.reminder_sent_on = None
    return order


async def debtor_members(session: AsyncSession) -> list[tuple[int, str, Decimal]]:
    remaining = func.sum(TeamDebt.amount - TeamDebt.paid_amount)
    rows = await session.execute(
        select(TeamMember.id, TeamMember.name, remaining)
        .join(TeamDebt, TeamDebt.member_id == TeamMember.id)
        .group_by(TeamMember.id, TeamMember.name)
        .having(remaining > 0)
        .order_by(TeamMember.name)
    )
    return [(int(row[0]), str(row[1]), to_decimal(row[2])) for row in rows.all()]


async def pay_team_debt(
    session: AsyncSession,
    *,
    debt_id: int,
    amount: Decimal,
    paid_at: datetime,
    idempotency_key: str,
) -> tuple[TeamPayment, TeamDebt, bool]:
    existing = await find_by_key(session, TeamPayment, idempotency_key)
    if existing is not None:
        debt = await session.get(TeamDebt, existing.debt_id) if existing.debt_id else None
        if debt is None:
            raise UserFacingError("Qarz topilmadi.")
        return existing, debt, False

    debt = await session.get(TeamDebt, debt_id, with_for_update=True)
    if debt is None:
        raise UserFacingError("Qarz topilmadi.")
    remaining = debt_remaining(debt)
    if remaining <= 0:
        raise UserFacingError("Bu qarz yopilgan.")
    if amount > remaining:
        raise UserFacingError(
            f"Qolgan qarz {money(remaining)}. Shu summadan katta berib bo'lmaydi."
        )
    member = await session.get(TeamMember, debt.member_id)
    if member is None:
        raise UserFacingError("Hodim topilmadi.")
    payment = TeamPayment(
        member_id=debt.member_id,
        order_id=debt.order_id,
        amount=amount,
        paid_at=paid_at,
        note="Qarzdan berildi",
        work_for=debt.work_for,
        debt_id=debt.id,
        idempotency_key=idempotency_key,
    )
    try:
        async with session.begin_nested():
            session.add(payment)
            debt.paid_amount = to_decimal(debt.paid_amount) + amount
            await session.flush()
    except IntegrityError:
        existing = await find_by_key(session, TeamPayment, idempotency_key)
        if existing is not None:
            current = await session.get(TeamDebt, debt_id)
            if current is None:
                raise UserFacingError("Qarz topilmadi.")
            return existing, current, False
        raise
    return payment, debt, True
