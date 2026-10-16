from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import Date, and_, cast, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Expense, Order, Payment, TeamMember, TeamPayment
from app.formatting import (
    MONTHS,
    TZ_NAME,
    debt_of,
    format_date,
    local_date,
    money,
    month_bounds,
    to_decimal,
)

PeriodKind = Literal["daily", "monthly", "yearly"]


@dataclass(frozen=True)
class Period:
    kind: PeriodKind
    start: date
    end: date
    label: str


@dataclass(frozen=True)
class FlowFigures:
    new_orders: int
    order_value: Decimal
    received: Decimal
    expenses: Decimal
    team_paid: Decimal
    outstanding_debt: Decimal
    debtor_count: int

    @property
    def outgoing(self) -> Decimal:
        return to_decimal(self.expenses + self.team_paid)

    @property
    def net(self) -> Decimal:
        return to_decimal(self.received - self.outgoing)


@dataclass(frozen=True)
class OrderLine:
    number: str
    client_name: str
    phone: str
    service: str
    total_price: Decimal
    paid: Decimal
    debt: Decimal
    event_date: date | None
    created_on: date | None
    status: str
    notes: str


@dataclass(frozen=True)
class PaymentLine:
    payment_id: int
    order_number: str
    client_name: str
    amount: Decimal
    method: str
    note: str
    paid_on: date | None


@dataclass(frozen=True)
class ExpenseLine:
    expense_id: int
    category: str
    amount: Decimal
    description: str
    spent_on: date | None


@dataclass(frozen=True)
class TeamLine:
    payment_id: int
    person_name: str
    amount: Decimal
    work_for: str
    note: str
    paid_on: date | None


@dataclass(frozen=True)
class ClientMonth:
    number: str
    client_name: str
    phone: str
    service: str
    created_on: date | None
    event_date: date | None
    total_price: Decimal
    paid_in_period: Decimal
    paid_before: Decimal
    paid_after: Decimal
    paid_total: Decimal
    debt: Decimal


@dataclass(frozen=True)
class OverallStats:
    orders: int
    order_value: Decimal
    received: Decimal
    expenses: Decimal
    team_paid: Decimal
    outstanding_debt: Decimal
    debtor_count: int
    month_label: str
    month_received: Decimal
    month_expenses: Decimal
    month_team: Decimal

    @property
    def net(self) -> Decimal:
        return to_decimal(self.received - self.expenses - self.team_paid)

    @property
    def month_net(self) -> Decimal:
        return to_decimal(self.month_received - self.month_expenses - self.month_team)


@dataclass(frozen=True)
class ExcelData:
    period: Period
    figures: FlowFigures
    orders: list[OrderLine]
    payments: list[PaymentLine]
    debtors: list[OrderLine]
    expenses: list[ExpenseLine]
    team: list[TeamLine]


def daily_period(day: date) -> Period:
    return Period(
        kind="daily",
        start=day,
        end=day + timedelta(days=1),
        label=format_date(day),
    )


def monthly_period(year: int, month: int) -> Period:
    start, end = month_bounds(year, month)
    return Period(kind="monthly", start=start, end=end, label=f"{MONTHS[month]} {year}")


def yearly_period(year: int) -> Period:
    return Period(
        kind="yearly",
        start=date(year, 1, 1),
        end=date(year + 1, 1, 1),
        label=str(year),
    )


def _local_day(column):
    return cast(func.timezone(TZ_NAME, column), Date)


def _during(column, start: date, end: date):
    local = _local_day(column)
    return and_(local >= start, local < end)


def _order_line(order: Order, paid: Decimal) -> OrderLine:
    return OrderLine(
        number=order.order_number or f"#{order.id}",
        client_name=order.client_name,
        phone=order.phone or "",
        service=order.service or "",
        total_price=to_decimal(order.total_price),
        paid=to_decimal(paid),
        debt=debt_of(order.total_price, paid),
        event_date=order.event_date,
        created_on=local_date(order.created_at),
        status=order.status or "",
        notes=order.notes or "",
    )


def _paid_subquery():
    return (
        select(
            Payment.order_id.label("order_id"),
            func.sum(Payment.amount).label("paid"),
        )
        .group_by(Payment.order_id)
        .subquery()
    )


async def _sum_between(session: AsyncSession, amount_column, time_column, period: Period) -> Decimal:
    value = await session.scalar(
        select(func.coalesce(func.sum(amount_column), 0)).where(
            _during(time_column, period.start, period.end)
        )
    )
    return to_decimal(value)


async def outstanding(session: AsyncSession) -> tuple[Decimal, int]:
    paid_sub = _paid_subquery()
    paid_value = func.coalesce(paid_sub.c.paid, 0)
    debt_expr = Order.total_price - paid_value
    row = (
        await session.execute(
            select(func.coalesce(func.sum(debt_expr), 0), func.count(Order.id))
            .select_from(Order)
            .outerjoin(paid_sub, paid_sub.c.order_id == Order.id)
            .where(debt_expr > 0)
        )
    ).one()
    return to_decimal(row[0]), int(row[1] or 0)


async def paid_map(session: AsyncSession, order_ids: list[int]) -> dict[int, Decimal]:
    if not order_ids:
        return {}
    rows = (
        await session.execute(
            select(Payment.order_id, func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.order_id.in_(order_ids))
            .group_by(Payment.order_id)
        )
    ).all()
    return {int(order_id): to_decimal(paid) for order_id, paid in rows}


async def figures_for(session: AsyncSession, period: Period) -> FlowFigures:
    row = (
        await session.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_price), 0),
            ).where(_during(Order.created_at, period.start, period.end))
        )
    ).one()
    debt, debtors = await outstanding(session)
    return FlowFigures(
        new_orders=int(row[0] or 0),
        order_value=to_decimal(row[1]),
        received=await _sum_between(session, Payment.amount, Payment.paid_at, period),
        expenses=await _sum_between(session, Expense.amount, Expense.spent_at, period),
        team_paid=await _sum_between(session, TeamPayment.amount, TeamPayment.paid_at, period),
        outstanding_debt=debt,
        debtor_count=debtors,
    )


async def orders_in_period(session: AsyncSession, period: Period) -> list[OrderLine]:
    orders = (
        await session.scalars(
            select(Order)
            .where(_during(Order.created_at, period.start, period.end))
            .order_by(Order.id)
        )
    ).all()
    paid = await paid_map(session, [order.id for order in orders])
    return [_order_line(order, paid.get(order.id, Decimal("0"))) for order in orders]


async def recent_orders(session: AsyncSession, limit: int = 20) -> tuple[list[OrderLine], int]:
    total = int(await session.scalar(select(func.count(Order.id))) or 0)
    orders = (
        await session.scalars(select(Order).order_by(Order.id.desc()).limit(limit))
    ).all()
    paid = await paid_map(session, [order.id for order in orders])
    lines = [_order_line(order, paid.get(order.id, Decimal("0"))) for order in orders]
    return lines, total


async def debtors(session: AsyncSession) -> list[OrderLine]:
    paid_sub = _paid_subquery()
    paid_value = func.coalesce(paid_sub.c.paid, 0)
    rows = (
        await session.execute(
            select(Order, paid_value)
            .outerjoin(paid_sub, paid_sub.c.order_id == Order.id)
            .where(Order.total_price > paid_value)
            .order_by(Order.id.desc())
        )
    ).all()
    return [_order_line(order, to_decimal(paid)) for order, paid in rows]


async def all_order_lines(session: AsyncSession) -> list[OrderLine]:
    paid_sub = _paid_subquery()
    paid_value = func.coalesce(paid_sub.c.paid, 0)
    rows = (
        await session.execute(
            select(Order, paid_value)
            .outerjoin(paid_sub, paid_sub.c.order_id == Order.id)
            .order_by(Order.id.desc())
        )
    ).all()
    return [_order_line(order, to_decimal(paid)) for order, paid in rows]


async def listed_orders(
    session: AsyncSession,
    *,
    debts_only: bool,
    limit: int = 40,
) -> tuple[list[tuple[int, str]], int]:
    paid_sub = _paid_subquery()
    paid_value = func.coalesce(paid_sub.c.paid, 0)
    statement = (
        select(Order, paid_value)
        .outerjoin(paid_sub, paid_sub.c.order_id == Order.id)
        .order_by(Order.id.desc())
    )
    if debts_only:
        statement = statement.where(Order.total_price > paid_value)
    rows = (await session.execute(statement)).all()
    buttons: list[tuple[int, str]] = []
    for order, paid in rows[:limit]:
        number = order.order_number or f"#{order.id}"
        if debts_only:
            left = money(debt_of(order.total_price, paid)).removesuffix(" so'm")
            label = f"{order.client_name} · {left}"
        else:
            label = f"{number} · {order.client_name}"
        buttons.append((order.id, label))
    return buttons, len(rows)


async def payments_in_period(session: AsyncSession, period: Period) -> list[PaymentLine]:
    rows = (
        await session.execute(
            select(Payment, Order)
            .join(Order, Order.id == Payment.order_id)
            .where(_during(Payment.paid_at, period.start, period.end))
            .order_by(Payment.paid_at, Payment.id)
        )
    ).all()
    return [
        PaymentLine(
            payment_id=payment.id,
            order_number=order.order_number or f"#{order.id}",
            client_name=order.client_name,
            amount=to_decimal(payment.amount),
            method=payment.method or "",
            note=payment.note or "",
            paid_on=local_date(payment.paid_at),
        )
        for payment, order in rows
    ]


async def expenses_in_period(session: AsyncSession, period: Period) -> list[ExpenseLine]:
    rows = (
        await session.scalars(
            select(Expense)
            .where(_during(Expense.spent_at, period.start, period.end))
            .order_by(Expense.spent_at, Expense.id)
        )
    ).all()
    return [
        ExpenseLine(
            expense_id=expense.id,
            category=expense.category,
            amount=to_decimal(expense.amount),
            description=expense.description or "",
            spent_on=local_date(expense.spent_at),
        )
        for expense in rows
    ]


async def team_in_period(session: AsyncSession, period: Period) -> list[TeamLine]:
    rows = (
        await session.execute(
            select(TeamPayment, TeamMember, Order)
            .join(TeamMember, TeamMember.id == TeamPayment.member_id)
            .outerjoin(Order, Order.id == TeamPayment.order_id)
            .where(_during(TeamPayment.paid_at, period.start, period.end))
            .order_by(TeamPayment.paid_at, TeamPayment.id)
        )
    ).all()
    lines: list[TeamLine] = []
    for payment, member, order in rows:
        work = payment.work_for or ""
        if not work and order is not None:
            work = order.order_number or order.client_name
        lines.append(
            TeamLine(
                payment_id=payment.id,
                person_name=member.name,
                amount=to_decimal(payment.amount),
                work_for=work,
                note=payment.note or "",
                paid_on=local_date(payment.paid_at),
            )
        )
    return lines


async def monthly_clients(session: AsyncSession, year: int, month: int) -> list[ClientMonth]:
    period = monthly_period(year, month)
    created_ids = select(Order.id).where(_during(Order.created_at, period.start, period.end))
    paid_ids = select(Payment.order_id).where(_during(Payment.paid_at, period.start, period.end))
    id_rows = (await session.execute(union(created_ids, paid_ids))).all()
    ids = [int(row[0]) for row in id_rows if row[0] is not None]
    if not ids:
        return []

    orders = (
        await session.scalars(select(Order).where(Order.id.in_(ids)).order_by(Order.id))
    ).all()
    aggregates = (
        await session.execute(
            select(
                Payment.order_id,
                func.coalesce(
                    func.sum(Payment.amount).filter(
                        _during(Payment.paid_at, period.start, period.end)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(Payment.amount).filter(_local_day(Payment.paid_at) < period.start),
                    0,
                ),
                func.coalesce(func.sum(Payment.amount), 0),
            )
            .where(Payment.order_id.in_(ids))
            .group_by(Payment.order_id)
        )
    ).all()
    by_order = {
        int(order_id): (to_decimal(in_period), to_decimal(before), to_decimal(total))
        for order_id, in_period, before, total in aggregates
    }
    clients: list[ClientMonth] = []
    for order in orders:
        paid_in, paid_before, paid_total = by_order.get(
            order.id,
            (Decimal("0"), Decimal("0"), Decimal("0")),
        )
        paid_after = to_decimal(paid_total - paid_in - paid_before)
        clients.append(
            ClientMonth(
                number=order.order_number or f"#{order.id}",
                client_name=order.client_name,
                phone=order.phone or "",
                service=order.service or "",
                created_on=local_date(order.created_at),
                event_date=order.event_date,
                total_price=to_decimal(order.total_price),
                paid_in_period=paid_in,
                paid_before=paid_before,
                paid_after=paid_after,
                paid_total=paid_total,
                debt=debt_of(order.total_price, paid_total),
            )
        )
    return clients


async def overall_stats(session: AsyncSession, *, year: int, month: int) -> OverallStats:
    order_row = (
        await session.execute(
            select(func.count(Order.id), func.coalesce(func.sum(Order.total_price), 0))
        )
    ).one()
    received = to_decimal(await session.scalar(select(func.coalesce(func.sum(Payment.amount), 0))))
    expenses = to_decimal(await session.scalar(select(func.coalesce(func.sum(Expense.amount), 0))))
    team_paid = to_decimal(
        await session.scalar(select(func.coalesce(func.sum(TeamPayment.amount), 0)))
    )
    debt, debtors_count = await outstanding(session)
    month = monthly_period(year, month)
    return OverallStats(
        orders=int(order_row[0] or 0),
        order_value=to_decimal(order_row[1]),
        received=received,
        expenses=expenses,
        team_paid=team_paid,
        outstanding_debt=debt,
        debtor_count=debtors_count,
        month_label=month.label,
        month_received=await _sum_between(session, Payment.amount, Payment.paid_at, month),
        month_expenses=await _sum_between(session, Expense.amount, Expense.spent_at, month),
        month_team=await _sum_between(session, TeamPayment.amount, TeamPayment.paid_at, month),
    )


async def excel_data(session: AsyncSession, period: Period) -> ExcelData:
    return ExcelData(
        period=period,
        figures=await figures_for(session, period),
        orders=await orders_in_period(session, period),
        payments=await payments_in_period(session, period),
        debtors=await debtors(session),
        expenses=await expenses_in_period(session, period),
        team=await team_in_period(session, period),
    )
