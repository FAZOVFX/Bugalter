from html import escape
from typing import Literal, Never

from app.database import Order
from app.formatting import debt_of, format_date, money
from app.reports import ClientMonth, FlowFigures, OrderLine, OverallStats
from app.texts import AP

StatsScope = Literal["monthly", "yearly"]


def h(value: object) -> str:
    return escape("" if value is None else str(value))


def daily_text(figures: FlowFigures, label: str) -> str:
    return (
        f"<b>Kunlik hisobot — {h(label)}</b>\n\n"
        f"Yangi buyurtmalar: {figures.new_orders}\n"
        f"Buyurtmalar qiymati (kassaga tushgan pul emas): {money(figures.order_value)}\n"
        f"Bugun tushgan to{AP}lovlar: {money(figures.received)}\n"
        f"Bugungi xarajatlar: {money(figures.expenses)}\n"
        f"Jamoaga berilgan: {money(figures.team_paid)}\n"
        f"Jami chiqim (xarajat + jamoa): {money(figures.outgoing)}\n"
        f"Kunlik pul oqimi (tushum − chiqim): {money(figures.net)}\n"
        f"Hozirgi umumiy qarzdorlik: {money(figures.outstanding_debt)}\n"
        f"Qarzdorlar soni: {figures.debtor_count}"
    )


def monthly_text(
    figures: FlowFigures,
    clients: list[ClientMonth],
    label: str,
) -> str:
    lines = [
        f"<b>Oylik hisobot — {h(label)}</b>\n",
        f"Shu oy yaratilgan buyurtmalar: {figures.new_orders}",
        f"Shu oy kelishilgan qiymat (kassa emas): {money(figures.order_value)}",
        f"Shu oy tushgan to{AP}lovlar: {money(figures.received)}",
        f"Shu oy xarajatlari: {money(figures.expenses)}",
        f"Jamoaga berilgan: {money(figures.team_paid)}",
        f"Jami chiqim: {money(figures.outgoing)}",
        f"Oy pul oqimi: {money(figures.net)}",
        f"Hozirgi umumiy qarzdorlik: {money(figures.outstanding_debt)}",
        "",
        "Quyida faqat shu oyda buyurtmasi yoki to'lovi bo'lgan mijozlar.",
    ]
    if not clients:
        lines.append("\nShu oyda buyurtma yoki to'lov bo'lmagan.")
    for client in clients:
        after = ""
        if client.paid_after > 0:
            after = f"\nKeyingi oylarda to{AP}langan: {money(client.paid_after)}"
        lines.append(
            "\n"
            f"<b>{h(client.number)} — {h(client.client_name)}</b>\n"
            f"Telefon: {h(client.phone) or '-'}\n"
            f"Xizmat: {h(client.service)}\n"
            f"Buyurtma sanasi: {format_date(client.created_on)}\n"
            f"Tadbir sanasi: {format_date(client.event_date)}\n"
            f"Kelishilgan narx: {money(client.total_price)}\n"
            f"Shu oy to{AP}langan: {money(client.paid_in_period)}\n"
            f"Oldingi oylarda to{AP}langan: {money(client.paid_before)}\n"
            f"Jami to{AP}lov: {money(client.paid_total)}\n"
            f"Qolgan qarz: {money(client.debt)}"
            f"{after}"
        )
    lines.append(
        "\nKelishilgan narx kassadagi pul emas. "
        f"Shu oy xarajati: {money(figures.expenses)}. "
        f"Jamoa haqi alohida: {money(figures.team_paid)}."
    )
    return "\n".join(lines)


def period_stats_text(figures: FlowFigures, label: str, scope: StatsScope) -> str:
    match scope:
        case "monthly":
            title = "Oylik statistika"
            created = "Shu oy yaratilgan buyurtmalar"
            agreed = "Shu oy kelishilgan qiymat (kassa emas)"
            received = f"Shu oy tushgan to{AP}lovlar"
            spent = "Shu oy xarajatlari"
            flow = "Oy pul oqimi"
        case "yearly":
            title = "Yillik statistika"
            created = "Shu yil yaratilgan buyurtmalar"
            agreed = "Shu yil kelishilgan qiymat (kassa emas)"
            received = f"Shu yil tushgan to{AP}lovlar"
            spent = "Shu yil xarajatlari"
            flow = "Yil pul oqimi"
        case _ as unexpected:
            never: Never = unexpected
            raise RuntimeError(f"Noma'lum statistika: {never}")
    return (
        f"<b>{title} — {h(label)}</b>\n\n"
        f"{created}: {figures.new_orders}\n"
        f"{agreed}: {money(figures.order_value)}\n"
        f"{received}: {money(figures.received)}\n"
        f"{spent}: {money(figures.expenses)}\n"
        f"Jamoaga berilgan: {money(figures.team_paid)}\n"
        f"Jami chiqim (xarajat + jamoa): {money(figures.outgoing)}\n"
        f"{flow}: {money(figures.net)}\n"
        f"Hozirgi umumiy qarzdorlik: {money(figures.outstanding_debt)}\n"
        f"Qarzdorlar soni: {figures.debtor_count}"
    )


def stats_text(stats: OverallStats) -> str:
    return (
        "<b>Statistika</b>\n\n"
        f"Buyurtmalar: {stats.orders}\n"
        f"Kelishilgan jami qiymat: {money(stats.order_value)}\n"
        f"Jami tushum: {money(stats.received)}\n"
        f"Jami xarajat: {money(stats.expenses)}\n"
        f"Jami jamoa haqi: {money(stats.team_paid)}\n"
        f"Sof pul oqimi: {money(stats.net)}\n"
        f"Ochiq qarz: {money(stats.outstanding_debt)}\n"
        f"Qarzdorlar: {stats.debtor_count}\n\n"
        f"<b>Joriy oy — {h(stats.month_label)}</b>\n"
        f"Tushum: {money(stats.month_received)}\n"
        f"Xarajat: {money(stats.month_expenses)}\n"
        f"Jamoa haqi: {money(stats.month_team)}\n"
        f"Oy pul oqimi: {money(stats.month_net)}"
    )


def saved_order_text(order: Order, *, created: bool) -> str:
    prefix = (
        "Buyurtma saqlandi."
        if created
        else "Bu buyurtma avval saqlandi, qayta yozilmadi."
    )
    return (
        f"<b>{h(prefix)}</b>\n"
        f"Raqami: <code>{h(order.order_number)}</code>\n"
        f"To'y: {h(order.client_name)}\n"
        f"Telefon: {h(order.phone) or '-'}\n"
        f"Xizmat: {h(order.service)}\n"
        f"Kelishilgan narx: {money(order.total_price)}\n"
        f"Jami to{AP}langan: {money(order.paid_amount)}\n"
        f"Qolgan qarz: {money(debt_of(order.total_price, order.paid_amount))}\n"
        f"Tadbir sanasi: {format_date(order.event_date)}\n"
        f"Izoh: {h(order.notes) or '-'}"
    )


def client_card_text(order: Order, paid: object) -> str:
    paid_amount = debt_of(paid, 0)
    remaining = debt_of(order.total_price, paid_amount)
    due = format_date(order.payment_due_date) if order.payment_due_date else "Belgilanmagan"
    return (
        f"<b>{h(order.order_number or order.id)} — {h(order.client_name)}</b>\n"
        f"Telefon: {h(order.phone) or '-'}\n"
        f"Xizmatlar: {h(order.service) or '-'}\n"
        f"Jami: {money(order.total_price)}\n"
        f"Berilgan: {money(paid_amount)}\n"
        f"Qolgan: {money(remaining)}\n"
        f"Holat: {h(order.status)}\n"
        f"Tadbir sanasi: {format_date(order.event_date)}\n"
        f"Qarz berish sanasi: {due}\n"
        f"Izoh: {h(order.notes) or '-'}"
    )


def order_line_text(line: OrderLine) -> str:
    return (
        f"<b>{h(line.number)} — {h(line.client_name)}</b>\n"
        f"Telefon: {h(line.phone) or '-'}\n"
        f"Xizmat: {h(line.service)}\n"
        f"Umumiy narx: {money(line.total_price)}\n"
        f"Jami to{AP}langan: {money(line.paid)}\n"
        f"Qolgan qarz: {money(line.debt)}\n"
        f"Tadbir sanasi: {format_date(line.event_date)}\n"
        f"Buyurtma sanasi: {format_date(line.created_on)}\n"
        f"Holat: {h(line.status)}"
    )


def orders_text(lines: list[OrderLine], total: int) -> str:
    if total == 0:
        return "Hali buyurtma yo'q."
    body = "\n\n".join(order_line_text(line) for line in lines)
    extra = ""
    if total > len(lines):
        extra = f"\n\nKo'rsatildi: {len(lines)} / {total}. To'liq ro'yxat Excel hisobotda."
    return f"<b>Buyurtmalar</b>\n\n{body}{extra}"


def debtors_text(lines: list[OrderLine]) -> str:
    if not lines:
        return "Hozircha qarzi bor mijoz yo'q."
    total = debt_of(
        sum((line.debt for line in lines), start=0),
        0,
    )
    body = "\n\n".join(order_line_text(line) for line in lines)
    return (
        f"<b>Qarzdorlar</b>\n\n{body}\n\n"
        f"Jami qolgan qarz: {money(total)}"
    )


def help_text() -> str:
    return (
        "<b>FAZO CREATIVE GROUP</b>\n\n"
        "Bot faqat administrator uchun.\n"
        "Har bir forma oxirida Saqlash tugmasi bor. "
        "Tugma ikki marta bosilsa, yozuv takrorlanmaydi.\n"
        "Istalgan bosqichda Bekor qilish yoki /cancel.\n\n"
        f"<b>{h('Yangi buyurtma')}</b> — to'y turi, tadbir sanasi, telefon, "
        "har bir xizmatning haqqi, oldindan to'lov va izoh.\n"
        f"<b>Buyurtmalar ro{AP}yxati</b> — har bir mijoz alohida tugma. "
        "Kartada pul qo'shish, qarz sanasi, to'liq yopish va o'chirish bor. "
        "Ro'yxatdagi PDF barcha buyurtmani yig'adi. Mijoz kartasidagi PDF esa "
        "shu mijoz uchun to'liq A4 varaqa.\n"
        "<b>Qarzdorlar</b> — qarzi bor mijozlar. Shu yerda pul qo'shiladi "
        "va qolgan qarzni berish sanasi belgilanadi. Shu kuni bot eslatma yuboradi.\n"
        "<b>Qarzlarim</b> — hodim qarzi. Hodim tanlanadi, sana belgilanadi, "
        "pul berilsa qarz yopiladi.\n"
        "<b>Xarajat kiritish</b> — transport, ijara, texnika va boshqalar.\n"
        "<b>Hodimlar</b> — ism va telefon saqlanadi. Hodim tanlanganda "
        "qarz qo'shish yoki pul berish chiqadi. Qarz buyurtmaga yoziladi. "
        "Berilgan pul xarajat bilan birga chiqimga kiradi, lekin ikki marta ayirilmaydi.\n"
        "Bekor qilish oldingi bo'limni ochadi.\n"
        "Qarz sanasi kelganda bot ogohlantiradi. Xizmat kuni esa nima bo'lganini "
        "va pul olinganini so'raydi.\n"
        "<b>Hisobot</b> — kunlik, oylik, Excel va statistika bitta bo'limda.\n"
        "Statistikada oylik yoki yillik davr tanlanadi.\n\n"
        "Buyurtma qiymati kassaga tushgan pul hisoblanmaydi. "
        "Qarz = kelishilgan narx − jami to'lovlar.\n\n"
        "/start — menyu\n"
        "/help — shu yordam\n"
        "/id — Telegram ID\n"
        "/cancel — bekor qilish"
    )
