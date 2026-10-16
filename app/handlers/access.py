import os

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


def is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    raw = os.getenv("ADMIN_ID", "").strip()
    return raw.isdigit() and int(raw) == user_id


def _public_command(event: TelegramObject) -> bool:
    if not isinstance(event, Message) or not event.text:
        return False
    command = event.text.split(maxsplit=1)[0].split("@", maxsplit=1)[0]
    return command in {"/start", "/id"}


class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = getattr(event, "from_user", None)
        user_id = user.id if user is not None else None
        if _public_command(event) or is_admin(user_id):
            return await handler(event, data)
        if isinstance(event, Message):
            await event.answer("Bu bot faqat administrator uchun.")
        elif isinstance(event, CallbackQuery):
            await event.answer("Ruxsat yo'q.", show_alert=True)
        return None


def denied_text() -> str:
    return "Bu bot faqat administrator uchun."


def actor_id(event: Message | CallbackQuery) -> int:
    user = event.from_user
    if user is None:
        return 0
    return user.id
