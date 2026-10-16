AP = "\u2018"

NEW_ORDER = "➕ Yangi buyurtma"
ORDER_LIST = f"📋 Buyurtmalar ro{AP}yxati"
ADD_PAYMENT = f"💵 To{AP}lov kiritish"
DEBTORS = "📕 Qarzdorlar"
MY_DEBTS = "📒 Qarzlarim"
ADD_EXPENSE = "🧾 Xarajat kiritish"
ADD_TEAM = "👥 Hodimlar"
REPORTS = "📊 Hisobot"
DAILY = "Kunlik hisobot"
MONTHLY = "Oylik hisobot"
EXCEL = "Excel hisobot"
STATS = "Statistika"
HELP = "ℹ️ Yordam"
CANCEL = "❌ Bekor qilish"
TODAY = "📅 Bugun"
NO_NOTE = "⏭️ Izohsiz"
NO_PREPAY = "0️⃣ Oldindan to'lov yo'q"
NO_DATE = "🚫 Sana yo'q"
NO_WORK = "➖ Buyurtmaga biriktirilmagan"
SAVE = "✅ Saqlash"

OTHER_SERVICE = "✨ Boshqa xizmat"
OTHER_EXPENSE = "📌 Boshqa xarajat"
OTHER_METHOD = "🔄 Boshqa"
SERVICE_OTHER = "boshqa"
SERVICE_DONE = "✅ Davom etish"

SERVICE_CHOICES = (
    ("foto", "📸 Foto xizmati"),
    ("video", "🎥 Video xizmati"),
    ("karnay", "🎺 Karnay-surnay"),
    ("kartej", "🖼 Kartej"),
    ("rasmzona", "🌅 Rasmzona"),
    ("sanatkor", "🎤 San'atkor"),
    ("davra", "🎙 Davra rais"),
    (SERVICE_OTHER, OTHER_SERVICE),
)
WEDDING_CHOICES = (
    ("qiz", "💍 Qiz to'yi"),
    ("sunnat", "🎊 Sunnat to'y"),
    ("nahor", "🍽 Nahor oshi"),
    ("foto", "📸 Fotosurati"),
    ("yoshlar", "🎉 Yoshlar to'yi"),
    ("beshik", "👶 Beshik to'yi"),
    ("boshqa", "➕ Boshqa"),
)
WEDDING_LABELS = {code: label for code, label in WEDDING_CHOICES}

SERVICE_CODES = {code for code, _label in SERVICE_CHOICES}
SERVICE_LABELS = {code: label for code, label in SERVICE_CHOICES}

EXPENSE_CATEGORIES = (
    "🚗 Transport",
    "🏠 Ijara",
    "🎬 Texnika",
    "📣 Reklama",
    OTHER_EXPENSE,
)

METHODS = (
    "💵 Naqd",
    "💳 Karta",
    f"🏦 O{AP}tkazma",
    OTHER_METHOD,
)

CANCEL_TEXTS = {CANCEL, "Bekor qilish"}
TODAY_TEXTS = {TODAY, "Bugun"}
NO_NOTE_TEXTS = {NO_NOTE, "Izohsiz", "-", "—"}
NO_PREPAY_TEXTS = {NO_PREPAY, "Oldindan to'lov yo'q"}
NO_DATE_TEXTS = {NO_DATE, "Sana yo'q", "-", "—"}
NO_WORK_TEXTS = {NO_WORK, "Buyurtmaga biriktirilmagan"}

LEGACY_NEW_ORDER = "➕ Buyurtma"
LEGACY_PAYMENT = "💵 To'lov"
LEGACY_EXPENSE = "🧾 Xarajat"
LEGACY_TEAM = "👥 Jamoa haqi"
LEGACY_REPORT = "📊 Hisobot"
LEGACY_DEBTORS = "📕 Qarzdorlar"
LEGACY_EXCEL = "📤 Excel"

NEW_ORDER_TEXTS = {NEW_ORDER, "Yangi buyurtma", LEGACY_NEW_ORDER}
ORDER_LIST_TEXTS = {ORDER_LIST, f"Buyurtmalar ro{AP}yxati"}
PAYMENT_TEXTS = {ADD_PAYMENT, f"To{AP}lov kiritish", LEGACY_PAYMENT}
EXPENSE_TEXTS = {ADD_EXPENSE, "Xarajat kiritish", LEGACY_EXPENSE}
TEAM_TEXTS = {
    ADD_TEAM,
    "Hodimlar",
    "👥 Jamoa haqini kiritish",
    "Jamoa haqini kiritish",
    LEGACY_TEAM,
}
DEBTOR_TEXTS = {DEBTORS, "Qarzdorlar", LEGACY_DEBTORS}
MY_DEBT_TEXTS = {MY_DEBTS, "Qarzlarim"}
EXCEL_TEXTS = {EXCEL, LEGACY_EXCEL}
MONTHLY_TEXTS = {MONTHLY}
REPORT_TEXTS = {REPORTS, "Hisobot", LEGACY_REPORT}
HELP_TEXTS = {HELP, "Yordam"}
MENU_TEXTS = {
    NEW_ORDER,
    ORDER_LIST,
    DEBTORS,
    MY_DEBTS,
    ADD_EXPENSE,
    ADD_TEAM,
    REPORTS,
    HELP,
    DAILY,
    MONTHLY,
    EXCEL,
    STATS,
    LEGACY_NEW_ORDER,
    LEGACY_PAYMENT,
    LEGACY_EXPENSE,
    "👥 Jamoa haqini kiritish",
    LEGACY_TEAM,
    LEGACY_REPORT,
    LEGACY_DEBTORS,
    LEGACY_EXCEL,
}
