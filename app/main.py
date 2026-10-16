import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.database import close_db
from app.handlers import router
from app.logsafe import safe_db_message, setup_logging
from app.migrate import migrate_schema
from app.reminders import reminder_loop


async def main() -> None:
    setup_logging()
    token = os.getenv("BOT_TOKEN", "").strip()
    admin_raw = os.getenv("ADMIN_ID", "").strip()
    database_url = os.getenv("DATABASE_URL", "").strip()

    if not token or not admin_raw or not database_url:
        raise RuntimeError(
            ".env faylida BOT_TOKEN, ADMIN_ID va DATABASE_URL bo'lishi kerak."
        )
    if not admin_raw.isdigit():
        raise RuntimeError("ADMIN_ID faqat raqamlardan iborat bo'lishi kerak.")

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)

    try:
        await migrate_schema()
        await bot.delete_webhook(drop_pending_updates=False)
        me = await bot.get_me()
        logging.info("Bot ulandi: @%s", me.username)
        logging.info("PostgreSQL tayyor. Polling boshlandi.")
        reminders = asyncio.create_task(reminder_loop(bot))
        try:
            await dispatcher.start_polling(bot)
        finally:
            reminders.cancel()
            await asyncio.gather(reminders, return_exceptions=True)
    except Exception as exc:
        logging.exception("Bot ishga tushmadi: %s", safe_db_message(exc))
        raise RuntimeError(safe_db_message(exc)) from None
    finally:
        await bot.session.close()
        await close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot to'xtatildi.")
    except RuntimeError as exc:
        logging.error("%s", exc)
        raise SystemExit(1) from None
