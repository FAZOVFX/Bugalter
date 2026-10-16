from aiogram import Router

from app.handlers import common, expenses, orders, payments, reports_bot, team
from app.handlers.access import AdminOnlyMiddleware

router = Router()
router.message.middleware(AdminOnlyMiddleware())
router.callback_query.middleware(AdminOnlyMiddleware())
router.include_router(common.router)
router.include_router(orders.menu_router)
router.include_router(payments.menu_router)
router.include_router(expenses.menu_router)
router.include_router(team.menu_router)
router.include_router(reports_bot.menu_router)
router.include_router(orders.form_router)
router.include_router(payments.form_router)
router.include_router(expenses.form_router)
router.include_router(team.form_router)
router.include_router(common.fallback_router)
router.error.register(common.on_error)
