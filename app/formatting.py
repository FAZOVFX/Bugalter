import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tashkent")
TZ_NAME = "Asia/Tashkent"
MONEY_QUANT = Decimal("0.01")
MAX_MONEY = Decimal("999999999999.99")

MONTHS = (
    "",
    "yanvar",
    "fevral",
    "mart",
    "aprel",
    "may",
    "iyun",
    "iyul",
    "avgust",
    "sentabr",
    "oktabr",
    "noyabr",
    "dekabr",
)


def now_local() -> datetime:
    return datetime.now(TZ)


def today_local() -> date:
    return now_local().date()


def as_moment(day: date) -> datetime:
    current = now_local()
    if day == current.date():
        return current
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=TZ)


def local_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(TZ).date()


def format_date(value: date | datetime | None) -> str:
    if value is None:
        return "Ko'rsatilmagan"
    if isinstance(value, datetime):
        value = local_date(value)
    if value is None:
        return "Ko'rsatilmagan"
    return value.strftime("%d.%m.%Y")


def parse_date(value: str) -> date | None:
    raw = " ".join(value.strip().split())
    if not raw:
        return None
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    parts = re.split(r"[.\-/\s]+", raw)
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    if len(parts[0]) == 4:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    else:
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
    if year < 100:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def previous_month(day: date) -> tuple[int, int]:
    first = day.replace(day=1)
    prev = first - timedelta(days=1)
    return prev.year, prev.month


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return quantize_money(Decimal(str(value)))


_CURRENCY_WORDS = ("so'm", "som", "sum", "сум")
_MONEY_TEXT = re.compile(r"\d+(?:[.,]\d+)*")


def _join_groups(raw: str, separator: str) -> str | None:
    parts = raw.split(separator)
    if len(parts) < 2 or not parts[0].isdigit() or not 1 <= len(parts[0]) <= 3:
        return None
    for part in parts[1:]:
        if len(part) != 3 or not part.isdigit():
            return None
    return "".join(parts)


def _normalize_money(raw: str) -> str | None:
    has_dot = "." in raw
    has_comma = "," in raw
    if has_dot and has_comma:
        if raw.rfind(".") > raw.rfind(","):
            head, tail = raw.rsplit(".", 1)
            whole = _join_groups(head, ",")
        else:
            head, tail = raw.rsplit(",", 1)
            whole = _join_groups(head, ".")
        if whole is None or not tail.isdigit() or not 1 <= len(tail) <= 2:
            return None
        return f"{whole}.{tail}"
    if raw.count(".") > 1:
        return _join_groups(raw, ".")
    if raw.count(",") > 1:
        return _join_groups(raw, ",")
    if has_dot or has_comma:
        separator = "." if has_dot else ","
        head, tail = raw.split(separator, 1)
        if not head.isdigit() or not tail.isdigit():
            return None
        if len(tail) == 3:
            return head + tail
        if len(tail) <= 2:
            return f"{head}.{tail}"
        return None
    return raw


def parse_amount(value: str, *, allow_zero: bool = False) -> Decimal | None:
    raw = value.strip().lower()
    raw = raw.replace("'", "").replace("\u2018", "").replace("\u2019", "").replace("`", "")
    raw = "".join(character for character in raw if not character.isspace())
    for word in _CURRENCY_WORDS:
        raw = raw.replace(word, "")
    if not raw or _MONEY_TEXT.fullmatch(raw) is None:
        return None
    normalized = _normalize_money(raw)
    if normalized is None:
        return None
    try:
        amount = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None
    if amount > MAX_MONEY or amount < 0:
        return None
    if amount == 0 and not allow_zero:
        return None
    rounded = quantize_money(amount)
    if rounded != amount:
        return None
    return rounded


def money(value: object) -> str:
    amount = to_decimal(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount == amount.to_integral_value():
        text = f"{amount:,.0f}"
    else:
        text = f"{amount:,.2f}"
    return f"{sign}{text.replace(',', ' ')} so'm"


def debt_of(total: object, paid: object) -> Decimal:
    return quantize_money(to_decimal(total) - to_decimal(paid))


def status_for(total: object, paid: object) -> str:
    total_amount = to_decimal(total)
    paid_amount = to_decimal(paid)
    if paid_amount <= 0:
        return "Yangi"
    if paid_amount < total_amount:
        return "Qisman to'langan"
    return "Yopilgan"


def split_text(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(block) > limit:
            parts.append(block[:limit])
            block = block[limit:]
        current = block
    if current:
        parts.append(current)
    return parts or [text[:limit]]


def like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
