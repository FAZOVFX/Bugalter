from contextlib import asynccontextmanager
from datetime import date
from uuid import uuid4

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.database import SessionLocal
from app.formatting import parse_date, split_text, today_local
from app.texts import NO_DATE_TEXTS, NO_NOTE_TEXTS, TODAY_TEXTS


def message_text(message: Message) -> str:
    return (message.text or "").strip()


def blank_note(value: str) -> str:
    if value in NO_NOTE_TEXTS:
        return ""
    return value.strip()


def read_day(value: str, *, allow_empty: bool) -> tuple[bool, date | None]:
    if value in TODAY_TEXTS:
        return True, today_local()
    if allow_empty and value in NO_DATE_TEXTS:
        return True, None
    parsed = parse_date(value)
    if parsed is None:
        return False, None
    return True, parsed


def valid_phone(value: str) -> str | None:
    cleaned = value.strip()
    digits = "".join(character for character in cleaned if character.isdigit())
    if len(digits) < 7 or len(cleaned) > 40:
        return None
    return cleaned


async def send_text(message: Message, text: str, reply_markup=None) -> None:
    parts = split_text(text)
    for index, part in enumerate(parts):
        markup = reply_markup if index == len(parts) - 1 else None
        await message.answer(part, reply_markup=markup)


async def callback_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    if isinstance(message, Message):
        return message
    return None


@asynccontextmanager
async def unit_of_work():
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
            session.expunge_all()
        except Exception:
            await session.rollback()
            raise


async def remember_key(state: FSMContext) -> str:
    data = await state.get_data()
    key = data.get("idempotency_key")
    if isinstance(key, str) and key:
        return key
    key = uuid4().hex
    await state.update_data(idempotency_key=key)
    return key
