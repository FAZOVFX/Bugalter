import re
import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.pdfgen import canvas as pdf_canvas

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.formatting import format_date, money, today_local, to_decimal
from app.reports import OrderLine

NAVY = colors.HexColor("#0E4D6C")
GOLD = colors.HexColor("#C4A35A")
HEADER = colors.HexColor("#145A7A")
ZEBRA = colors.HexColor("#F4F7FB")
TOTAL = colors.HexColor("#E5F2E9")
INK = colors.HexColor("#1D2430")
LINE = colors.HexColor("#D5DDE5")
_PICTO = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F\U0000200D]+"
)


def _plain(value: str) -> str:
    cleaned = _PICTO.sub("", value)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _fonts() -> tuple[str, str]:
    if "Fazo" in pdfmetrics.getRegisteredFontNames():
        return "Fazo", "Fazo-Bold"
    regular = Path(r"C:\Windows\Fonts\arial.ttf")
    bold = Path(r"C:\Windows\Fonts\arialbd.ttf")
    if not regular.exists():
        return "Helvetica", "Helvetica-Bold"
    pdfmetrics.registerFont(TTFont("Fazo", str(regular)))
    pdfmetrics.registerFont(TTFont("Fazo-Bold", str(bold if bold.exists() else regular)))
    return "Fazo", "Fazo-Bold"


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    safe = escape(_plain(text) or "-").replace("\n", "<br/>")
    return Paragraph(safe, style)


def write_orders_pdf(lines: list[OrderLine]) -> Path:
    regular, bold = _fonts()
    handle = tempfile.NamedTemporaryFile(prefix="fazo-orders-", suffix=".pdf", delete=False)
    path = Path(handle.name)
    handle.close()
    try:
        _build(path, lines, regular, bold)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _build(path: Path, lines: list[OrderLine], regular: str, bold: str) -> None:
    page = landscape(A4)
    document = SimpleDocTemplate(
        str(path),
        pagesize=page,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=22 * mm,
        bottomMargin=12 * mm,
        title="FAZO CREATIVE GROUP",
        author="FAZO CREATIVE GROUP",
    )
    title = ParagraphStyle(
        "fazo-title",
        fontName=bold,
        fontSize=12,
        leading=15,
        textColor=NAVY,
        alignment=TA_LEFT,
    )
    label = ParagraphStyle(
        "fazo-label",
        fontName=regular,
        fontSize=8,
        leading=10,
        textColor=INK,
    )
    label_right = ParagraphStyle(
        "fazo-money",
        parent=label,
        alignment=TA_RIGHT,
    )
    head = ParagraphStyle(
        "fazo-head",
        fontName=bold,
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )
    head_right = ParagraphStyle("fazo-head-right", parent=head, alignment=TA_RIGHT)
    total_style = ParagraphStyle(
        "fazo-total",
        fontName=bold,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#143D28"),
        alignment=TA_RIGHT,
    )
    total_left = ParagraphStyle("fazo-total-left", parent=total_style, alignment=TA_LEFT)

    story = [
        Paragraph("Buyurtmalar ro'yxati", title),
        Paragraph(escape(format_date(today_local())), label),
        Spacer(1, 4 * mm),
    ]
    header = [
        _paragraph("Raqam", head),
        _paragraph("Mijoz", head),
        _paragraph("Telefon", head),
        _paragraph("Xizmatlar", head),
        _paragraph("Jami", head_right),
        _paragraph("Berilgan", head_right),
        _paragraph("Qolgan", head_right),
    ]
    data = [header]
    for line in lines:
        data.append(
            [
                _paragraph(line.number, label),
                _paragraph(line.client_name, label),
                _paragraph(line.phone or "-", label),
                _paragraph(line.service or "-", label),
                _paragraph(money(line.total_price), label_right),
                _paragraph(money(line.paid), label_right),
                _paragraph(money(line.debt), label_right),
            ]
        )
    agreed = to_decimal(sum((line.total_price for line in lines), Decimal("0")))
    paid = to_decimal(sum((line.paid for line in lines), Decimal("0")))
    left = to_decimal(sum((line.debt for line in lines), Decimal("0")))
    data.append(
        [
            _paragraph(f"{len(lines)} ta", total_left),
            _paragraph("Jami", total_left),
            "",
            "",
            _paragraph(money(agreed), total_style),
            _paragraph(money(paid), total_style),
            _paragraph(money(left), total_style),
        ]
    )
    widths = [28 * mm, 42 * mm, 34 * mm, 78 * mm, 30 * mm, 30 * mm, 30 * mm]
    table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, -1), (-1, -1), TOTAL),
        ("FONTNAME", (0, 0), (-1, -1), regular),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("SPAN", (1, -1), (3, -1)),
    ]
    for row in range(1, len(data) - 1):
        if row % 2 == 0:
            style.append(("BACKGROUND", (0, row), (-1, row), ZEBRA))
    table.setStyle(TableStyle(style))
    story.append(table)

    def paint(canvas, _doc) -> None:
        canvas.saveState()
        width, height = page
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - 16 * mm, width, 16 * mm, fill=1, stroke=0)
        canvas.setFillColor(GOLD)
        canvas.rect(0, height - 17.2 * mm, width, 1.2 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(bold, 13)
        canvas.drawString(12 * mm, height - 10.5 * mm, "FAZO CREATIVE GROUP")
        canvas.restoreState()

    document.build(story, onFirstPage=paint, onLaterPages=paint)


@dataclass(frozen=True)
class ClientPage:
    number: str
    client_name: str
    phone: str
    service: str
    total_price: Decimal
    paid: Decimal
    debt: Decimal
    event_date: date | None
    due_date: date | None
    notes: str
    status: str


def write_client_pdf(page: ClientPage) -> Path:
    regular, bold = _fonts()
    handle = tempfile.NamedTemporaryFile(prefix="fazo-client-", suffix=".pdf", delete=False)
    path = Path(handle.name)
    handle.close()
    try:
        _draw_client(path, page, regular, bold)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _service_rows(service: str) -> list[tuple[str, str]]:
    text = _plain(service)
    if not text:
        return [("Ko'rsatilmagan", "")]
    rows: list[tuple[str, str]] = []
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        if "—" in item:
            name, price = item.split("—", 1)
            rows.append((name.strip(), price.strip()))
        elif " - " in item:
            name, price = item.split(" - ", 1)
            rows.append((name.strip(), price.strip()))
        else:
            rows.append((item, ""))
    return rows or [("Ko'rsatilmagan", "")]


def _wrap(drawing, text: str, font: str, size: float, width: float) -> list[str]:
    words = _plain(text).split()
    if not words:
        return ["-"]
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if drawing.stringWidth(trial, font, size) <= width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def _draw_client(path: Path, page: ClientPage, regular: str, bold: str) -> None:
    drawing = pdf_canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    drawing.setTitle("FAZO CREATIVE GROUP")
    drawing.setAuthor("FAZO CREATIVE GROUP")

    drawing.setFillColor(NAVY)
    drawing.rect(0, height - 34 * mm, width, 34 * mm, fill=1, stroke=0)
    drawing.setFillColor(GOLD)
    drawing.rect(0, height - 36 * mm, width, 2 * mm, fill=1, stroke=0)
    drawing.setFillColor(colors.white)
    drawing.setFont(bold, 18)
    drawing.drawString(16 * mm, height - 16 * mm, "FAZO CREATIVE GROUP")
    drawing.setFont(regular, 10)
    drawing.drawString(16 * mm, height - 24 * mm, "Buyurtma varaqasi")
    drawing.drawRightString(width - 16 * mm, height - 24 * mm, format_date(today_local()))

    drawing.setFillColor(GOLD)
    drawing.rect(0, 0, 5 * mm, height - 36 * mm, fill=1, stroke=0)

    left = 16 * mm
    right = width - 16 * mm
    name = _plain(page.client_name) or "Mijoz"
    name_size = 22
    while name_size > 14 and drawing.stringWidth(name, bold, name_size) > right - left:
        name_size -= 1
    drawing.setFillColor(NAVY)
    drawing.setFont(bold, name_size)
    drawing.drawString(left, height - 50 * mm, name)
    drawing.setFillColor(INK)
    drawing.setFont(regular, 12)
    drawing.drawString(left, height - 58 * mm, _plain(page.phone) or "Telefon ko'rsatilmagan")
    drawing.setFont(bold, 11)
    drawing.drawString(left, height - 65 * mm, _plain(page.number) or "-")

    drawing.setStrokeColor(GOLD)
    drawing.setLineWidth(1)
    drawing.line(left, height - 70 * mm, right, height - 70 * mm)
    drawing.setFillColor(NAVY)
    drawing.setFont(bold, 11)
    drawing.drawString(left, height - 78 * mm, "XIZMATLAR")

    services = _service_rows(page.service)
    top = height - 86 * mm
    bottom_panel = 78 * mm
    slot = top - (bottom_panel + 8 * mm)
    row_height = min(16 * mm, slot / len(services))
    y = top
    for name_text, price_text in services:
        if y - 6 * mm < bottom_panel:
            break
        drawing.setFillColor(INK)
        drawing.setFont(regular, 11)
        label_lines = _wrap(drawing, name_text, regular, 11, right - left - 55 * mm)
        drawing.drawString(left, y, label_lines[0])
        if price_text:
            drawing.setFont(bold, 11)
            drawing.drawRightString(right, y, _plain(price_text))
        y -= 5 * mm
        drawing.setStrokeColor(LINE)
        drawing.setLineWidth(0.4)
        drawing.line(left, y, right, y)
        y -= max(4 * mm, row_height - 5 * mm)

    panel_top = 74 * mm
    drawing.setFillColor(colors.HexColor("#F7F4EE"))
    drawing.roundRect(left, 16 * mm, right - left, panel_top - 16 * mm, 4 * mm, fill=1, stroke=0)
    columns = [
        ("JAMI", money(page.total_price)),
        ("BERILGAN", money(page.paid)),
        ("QOLGAN", money(page.debt)),
    ]
    column_width = (right - left) / 3
    for index, (caption, value) in enumerate(columns):
        x = left + index * column_width + 4 * mm
        drawing.setFillColor(GOLD)
        drawing.setFont(bold, 8)
        drawing.drawString(x, 64 * mm, caption)
        drawing.setFillColor(NAVY)
        value_size = 12
        while value_size > 8 and drawing.stringWidth(value, bold, value_size) > column_width - 8 * mm:
            value_size -= 1
        drawing.setFont(bold, value_size)
        drawing.drawString(x, 56 * mm, value)

    meta = [
        ("Tadbir", format_date(page.event_date) if page.event_date else "Ko'rsatilmagan"),
        ("Qarz sanasi", format_date(page.due_date) if page.due_date else "Belgilanmagan"),
        ("Holat", page.status or "-"),
    ]
    drawing.setFont(regular, 9)
    for index, (caption, value) in enumerate(meta):
        x = left + index * column_width + 4 * mm
        drawing.setFillColor(colors.HexColor("#5C6770"))
        drawing.setFont(regular, 8)
        drawing.drawString(x, 46 * mm, caption)
        drawing.setFillColor(INK)
        drawing.setFont(bold, 9)
        drawing.drawString(x, 41 * mm, _plain(value)[:28])

    note = _plain(page.notes)
    drawing.setFillColor(colors.HexColor("#5C6770"))
    drawing.setFont(regular, 8)
    drawing.drawString(left + 4 * mm, 32 * mm, "IZOH")
    drawing.setFillColor(INK)
    drawing.setFont(regular, 9)
    note_lines = _wrap(drawing, note or "-", regular, 9, right - left - 8 * mm)[:2]
    note_y = 27 * mm
    for line in note_lines:
        drawing.drawString(left + 4 * mm, note_y, line)
        note_y -= 4 * mm

    drawing.setFillColor(NAVY)
    drawing.rect(0, 0, width, 10 * mm, fill=1, stroke=0)
    drawing.setFillColor(colors.white)
    drawing.setFont(regular, 8)
    drawing.drawString(left, 4 * mm, "FAZO CREATIVE GROUP")
    drawing.drawRightString(right, 4 * mm, _plain(page.number))
    drawing.save()
