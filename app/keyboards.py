import calendar
from datetime import date

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.formatting import MONTHS, money, today_local
from app.texts import (
    ADD_EXPENSE,
    ADD_TEAM,
    CANCEL,
    DEBTORS,
    MY_DEBTS,
    EXPENSE_CATEGORIES,
    HELP,
    METHODS,
    NEW_ORDER,
    NO_DATE,
    NO_NOTE,
    NO_PREPAY,
    NO_WORK,
    ORDER_LIST,
    OTHER_SERVICE,
    REPORTS,
    SAVE,
    SERVICE_CHOICES,
    WEDDING_CHOICES,
    SERVICE_CODES,
    SERVICE_DONE,
    SERVICE_OTHER,
    TODAY,
)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=NEW_ORDER), KeyboardButton(text=ORDER_LIST)],
            [KeyboardButton(text=DEBTORS), KeyboardButton(text=MY_DEBTS)],
            [KeyboardButton(text=ADD_EXPENSE), KeyboardButton(text=ADD_TEAM)],
            [KeyboardButton(text=REPORTS), KeyboardButton(text=HELP)],
        ],
        resize_keyboard=True,
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL)]],
        resize_keyboard=True,
    )


def choice_menu(options: tuple[str, ...], *, extra: tuple[str, ...] = ()) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    row: list[KeyboardButton] = []
    for option in options:
        row.append(KeyboardButton(text=option))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    for item in extra:
        rows.append([KeyboardButton(text=item)])
    rows.append([KeyboardButton(text=CANCEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def _button_price(amount: str) -> str:
    return money(amount).removesuffix(" so'm")


def service_keyboard(items: list[dict[str, str]]) -> InlineKeyboardMarkup:
    amounts = {item["code"]: item["amount"] for item in items}
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code, label in SERVICE_CHOICES:
        if code == SERVICE_OTHER:
            continue
        title = label
        if code in amounts:
            title = f"{label} · {_button_price(amounts[code])}"
        row.append(InlineKeyboardButton(text=title[:64], callback_data=f"svc:{code}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    for item in items:
        if item["code"] in SERVICE_CODES:
            continue
        title = f"{item['label']} · {_button_price(item['amount'])}"
        rows.append(
            [InlineKeyboardButton(text=title[:64], callback_data=f"svc:{item['code']}")]
        )
    rows.append([InlineKeyboardButton(text=OTHER_SERVICE, callback_data=f"svc:{SERVICE_OTHER}")])
    rows.append([InlineKeyboardButton(text=SERVICE_DONE, callback_data="svc:done")])
    rows.append([InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def team_menu_keyboard(members: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=name[:64], callback_data=f"tm:{member_id}")]
        for member_id, name in members
    ]
    rows.append([InlineKeyboardButton(text="➕ Hodim qo'shish", callback_data="tm:add")])
    rows.append([InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def team_order_keyboard(orders: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label[:64], callback_data=f"tmo:{order_id}")]
        for order_id, label in orders
    ]
    rows.append([InlineKeyboardButton(text=NO_WORK, callback_data="tmo:0")])
    rows.append([InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def team_debtors_keyboard(members: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label[:64], callback_data=f"tmd:{member_id}")]
        for member_id, label in members
    ]
    rows.append([InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def team_debt_keyboard(
    debts: list[tuple[int, str, str]],
    *,
    back: str = "tm:debts",
    back_label: str = "⬅️ Qarzlarim",
    pay_member_id: int | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if pay_member_id:
        rows.append(
            [InlineKeyboardButton(text="💵 Pul berish", callback_data=f"tmc:{pay_member_id}")]
        )
    for debt_id, date_label, pay_label in debts:
        rows.append(
            [InlineKeyboardButton(text=date_label[:64], callback_data=f"tmds:{debt_id}")]
        )
        rows.append(
            [InlineKeyboardButton(text=pay_label[:64], callback_data=f"tmp:{debt_id}")]
        )
    rows.append([InlineKeyboardButton(text=back_label, callback_data=back)])
    rows.append([InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wedding_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code, label in WEDDING_CHOICES:
        row.append(InlineKeyboardButton(text=label, callback_data=f"toy:{code}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _shift_month(year: int, month: int, step: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + step
    return index // 12, index % 12 + 1


def month_calendar(year: int, month: int) -> InlineKeyboardMarkup:
    previous_year, previous_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, 1)
    title = f"{MONTHS[month].capitalize()} {year}"
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="◀️",
                callback_data=f"cal:m:{previous_year:04d}-{previous_month:02d}",
            ),
            InlineKeyboardButton(text=title, callback_data="noop"),
            InlineKeyboardButton(
                text="▶️",
                callback_data=f"cal:m:{next_year:04d}-{next_month:02d}",
            ),
        ]
    ]
    week: list[InlineKeyboardButton] = []
    for day in calendar.Calendar(firstweekday=0).itermonthdays(year, month):
        if day == 0:
            week.append(InlineKeyboardButton(text="·", callback_data="noop"))
        else:
            stamp = date(year, month, day).isoformat()
            week.append(InlineKeyboardButton(text=str(day), callback_data=f"cal:d:{stamp}"))
        if len(week) == 7:
            rows.append(week)
            week = []
    rows.append([InlineKeyboardButton(text=TODAY, callback_data="cal:d:today")])
    rows.append([InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def service_day_keyboard(orders: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label[:64], callback_data=f"tmx:{order_id}")]
        for order_id, label in orders
    ]
    rows.append([InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def event_check_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ To'liq olindi", callback_data=f"evt:full:{order_id}")],
            [InlineKeyboardButton(text="◐ Yarim olindi", callback_data=f"evt:half:{order_id}")],
            [InlineKeyboardButton(text="💵 Summa yozish", callback_data=f"evt:ask:{order_id}")],
            [InlineKeyboardButton(text="⏳ Hali olinmadi", callback_data=f"evt:none:{order_id}")],
        ]
    )


def expense_menu() -> ReplyKeyboardMarkup:
    return choice_menu(EXPENSE_CATEGORIES)


def method_menu() -> ReplyKeyboardMarkup:
    return choice_menu(METHODS)


def prepaid_menu() -> ReplyKeyboardMarkup:
    return choice_menu((), extra=(NO_PREPAY,))


def date_menu(*, allow_empty: bool = False) -> ReplyKeyboardMarkup:
    extra = (NO_DATE,) if allow_empty else ()
    return choice_menu((TODAY,), extra=extra)


def work_menu() -> ReplyKeyboardMarkup:
    return choice_menu((), extra=(NO_WORK,))


def note_menu() -> ReplyKeyboardMarkup:
    return choice_menu((), extra=(NO_NOTE,))


def choice_inline(
    items: list[tuple[int, str]],
    prefix: str,
    *,
    back: str | None = None,
    back_label: str = "⬅️ Ortga",
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label[:64], callback_data=f"{prefix}:{item_id}")]
        for item_id, label in items
    ]
    if back is not None:
        rows.append([InlineKeyboardButton(text=back_label, callback_data=back)])
    rows.append([InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_list_keyboard(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📄 PDF", callback_data="lst:pdf")]
    ]
    rows.extend(
        [[InlineKeyboardButton(text=label[:64], callback_data=f"lst:{item_id}")] for item_id, label in items]
    )
    rows.append([InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_card_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💵 Pul qo'shish", callback_data=f"lst:pay:{order_id}")],
            [InlineKeyboardButton(text="📅 Qarz sanasi", callback_data=f"lst:due:{order_id}")],
            [InlineKeyboardButton(text="✅ To'liq yopish", callback_data=f"lst:close:{order_id}")],
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"lst:del:{order_id}")],
            [InlineKeyboardButton(text="📄 PDF", callback_data=f"lst:doc:{order_id}")],
            [InlineKeyboardButton(text="⬅️ Buyurtmalar", callback_data="lst:list")],
            [InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")],
        ]
    )


def order_confirm_keyboard(order_id: int, action: str, *, back: str) -> InlineKeyboardMarkup:
    if action == "close":
        yes_text = "✅ To'liq yopish"
        yes_data = f"lst:closeok:{order_id}" if back == "order_card" else f"dbt:closeok:{order_id}"
    else:
        yes_text = "🗑 Ha, o'chirilsin"
        yes_data = f"lst:delok:{order_id}" if back == "order_card" else f"dbt:delok:{order_id}"
    back_data = f"lst:card:{order_id}" if back == "order_card" else f"dbt:{order_id}"
    back_text = "⬅️ Mijoz" if back == "order_card" else "⬅️ Qarzdor"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=yes_text, callback_data=yes_data)],
            [InlineKeyboardButton(text=back_text, callback_data=back_data)],
            [InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")],
        ]
    )


def member_action_keyboard(member_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Qarz qo'shish", callback_data=f"tmq:{member_id}")],
            [InlineKeyboardButton(text="💵 Pul berish", callback_data=f"tmg:{member_id}")],
            [InlineKeyboardButton(text="⬅️ Hodimlar", callback_data="tm:menu")],
            [InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")],
        ]
    )


def debtor_card_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💵 Pul qo'shish", callback_data=f"dbt:pay:{order_id}")],
            [InlineKeyboardButton(text="📅 Qarz sanasi", callback_data=f"dbt:due:{order_id}")],
            [InlineKeyboardButton(text="✅ To'liq yopish", callback_data=f"dbt:close:{order_id}")],
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"dbt:del:{order_id}")],
            [InlineKeyboardButton(text="⬅️ Qarzdorlar", callback_data="dbt:list")],
            [InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")],
        ]
    )


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=SAVE, callback_data=f"save:{action}")],
            [InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")],
        ]
    )


def order_choice_keyboard(orders: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label[:60], callback_data=f"pick:{order_id}")]
        for order_id, label in orders
    ]
    rows.append([InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def report_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Kunlik", callback_data="rep:day"),
                InlineKeyboardButton(text="🗓 Oylik", callback_data="rep:month"),
                InlineKeyboardButton(text="📗 Excel", callback_data="rep:excel"),
                InlineKeyboardButton(text="📈 Statistika", callback_data="rep:stats"),
            ]
        ]
    )


def stats_scope_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗓 Oylik", callback_data="stat:month"),
                InlineKeyboardButton(text="📆 Yillik", callback_data="stat:year"),
            ],
            [InlineKeyboardButton(text="⬅️ Ortga", callback_data="rep:menu")],
        ]
    )


def excel_scope_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Bugun", callback_data="xlscope:day"),
                InlineKeyboardButton(text="🗓 Oy tanlash", callback_data="xlscope:month"),
            ],
            [InlineKeyboardButton(text="⬅️ Ortga", callback_data="rep:menu")],
        ]
    )


def year_keyboard(prefix: str, center: int) -> InlineKeyboardMarkup:
    years = [year for year in (center - 1, center, center + 1) if 2020 <= year <= 2100]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=str(year), callback_data=f"{prefix}:{year}")
                for year in years
            ],
            [
                InlineKeyboardButton(text="«", callback_data=f"{prefix}y:{center - 3}"),
                InlineKeyboardButton(text="»", callback_data=f"{prefix}y:{center + 3}"),
            ],
            [InlineKeyboardButton(text="⬅️ Ortga", callback_data="rep:stats")],
        ]
    )


def month_keyboard(prefix: str, year: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for month in range(1, 13):
        row.append(
            InlineKeyboardButton(
                text=MONTHS[month][:3].capitalize(),
                callback_data=f"{prefix}:{year}:{month}",
            )
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    rows.append(
        [
            InlineKeyboardButton(text="«", callback_data=f"{prefix}y:{year - 1}"),
            InlineKeyboardButton(text=str(year), callback_data="noop"),
            InlineKeyboardButton(text="»", callback_data=f"{prefix}y:{year + 1}"),
        ]
    )
    rows.append([InlineKeyboardButton(text=CANCEL, callback_data="save:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def current_year() -> int:
    return today_local().year
