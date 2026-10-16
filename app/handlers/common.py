import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message

from app.handlers.access import denied_text, is_admin
from app.handlers.navigation import return_to_section
from app.handlers.support import callback_message, send_text
from app.handlers.views import help_text
from app.keyboards import main_menu
from app.texts import CANCEL_TEXTS, HELP_TEXTS

router = Router()
fallback_router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if not is_admin(user.id if user else None):
        await message.answer(denied_text())
        return
    await message.answer(
        "<b>FAZO CREATIVE GROUP</b>\n\n"
        "Hisob-kitob tayyor. Kerakli bo'limni menyudan tanlang.\n"
        "Yordam: /help",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
@router.message(F.text.in_(HELP_TEXTS))
async def help_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_text(message, help_text(), reply_markup=main_menu())


@router.message(Command("id"))
async def show_id(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    await message.answer(f"Telegram ID: <code>{user.id}</code>")


@router.message(Command("cancel"))
@router.message(F.text.in_(CANCEL_TEXTS))
async def cancel(message: Message, state: FSMContext) -> None:
    await return_to_section(message, state)


@router.callback_query(F.data == "save:cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    message = await callback_message(callback)
    if message is None:
        return
    await return_to_section(message, state)


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@fallback_router.message(F.text)
async def unknown(message: Message) -> None:
    await message.answer("Menyudan bo'limni tanlang yoki /help ni bosing.", reply_markup=main_menu())


@fallback_router.callback_query()
async def unknown_callback(callback: CallbackQuery) -> None:
    await callback.answer("Tugma eskirgan. /start ni bosing.", show_alert=True)


async def on_error(event: ErrorEvent) -> None:
    error = event.exception
    logger.error(
        "Ishlov berishda xatolik: %s",
        type(error).__name__,
        exc_info=(type(error), error, error.__traceback__),
    )
    update = event.update
    message = update.message
    if message is None and update.callback_query is not None:
        maybe = update.callback_query.message
        message = maybe if isinstance(maybe, Message) else None
    if message is None:
        return
    try:
        await message.answer(
            "Xatolik yuz berdi. Yozuv saqlanmagan bo'lishi mumkin. "
            "/cancel yoki /start ni bosing."
        )
    except Exception:
        logger.error("Xato haqida xabar yuborilmadi", exc_info=True)
