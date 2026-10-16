import logging
import os
import re

_URL_PASSWORD = re.compile(r"://([^:\s/@]+):([^@\s]+)@")
_SECRETS: list[str] = []


def remember_secrets() -> None:
    found: list[str] = []
    token = os.getenv("BOT_TOKEN", "").strip()
    url = os.getenv("DATABASE_URL", "").strip()
    if len(token) >= 8:
        found.append(token)
    if len(url) >= 8:
        found.append(url)
    _SECRETS[:] = found


def scrub(value: str) -> str:
    cleaned = _URL_PASSWORD.sub(r"://\1:***@", value)
    for secret in _SECRETS:
        cleaned = cleaned.replace(secret, "***")
    return cleaned


def safe_db_message(exc: BaseException) -> str:
    raw = str(exc).lower()
    if "password authentication failed" in raw:
        return (
            "PostgreSQL parolni rad etdi. .env dagi DATABASE_URL ni tekshiring. "
            "Parol va baza o'zgartirilmadi."
        )
    if "connection refused" in raw or "connect call failed" in raw:
        return (
            "PostgreSQL ga ulanib bo'lmadi. Server ishlayotganini va portni tekshiring. "
            "Sozlamalar o'zgartirilmadi."
        )
    if "does not exist" in raw and "database" in raw:
        return (
            "Ko'rsatilgan ma'lumotlar bazasi topilmadi. "
            "Baza qayta yaratilmadi va sozlamalar o'zgartirilmadi."
        )
    detail = scrub(f"{type(exc).__name__}: {exc}")
    return f"Ma'lumotlar bazasi amali bajarilmadi. {detail}"


class RedactFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return scrub(super().format(record))


def setup_logging() -> None:
    remember_secrets()
    handler = logging.StreamHandler()
    handler.setFormatter(
        RedactFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
