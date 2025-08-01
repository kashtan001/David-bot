# telegram_document_bot.py — Полный корректный код бота с авто-сбросом на /start
# -----------------------------------------------------------------------------
# Генератор PDF-документов Intesa Sanpaolo:
#   /contratto — кредитный договор
#   /garanzia  — письмо о гарантийном взносе
#   /carta     — письмо о выпуске карты
# -----------------------------------------------------------------------------
# Зависимости:
#   pip install python-telegram-bot==20.* reportlab
# -----------------------------------------------------------------------------
import logging
import os
from io import BytesIO
from decimal import Decimal, ROUND_HALF_UP

from telegram import Update, InputFile, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, ConversationHandler, MessageHandler, ContextTypes, filters,
)

from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

# ---------------------- Настройки ------------------------------------------
TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
DEFAULT_TAN = 7.86
DEFAULT_TAEG = 8.30
GARANZIA_COST = 180.0
CARTA_COST = 120.0
LOGO_PATH = "image1.jpg"      # логотип 3.2×3.2 см (по шаблону)
SIGNATURE_PATH = "image2.png"      # подпись 4×2 см

logging.basicConfig(format="%(asctime)s — %(levelname)s — %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------ Состояния Conversation -------------------------------
CHOOSING_DOC, ASK_NAME, ASK_AMOUNT, ASK_DURATION, ASK_TAN, ASK_TAEG = range(6)

# ---------------------- Утилиты -------------------------------------------
def money(val: float) -> str:
    """Формат суммы: € 0.00"""
    return f"€ {Decimal(val).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def monthly_payment(amount: float, months: int, annual_rate: float) -> float:
    """Аннуитетный расчёт ежемесячного платежа"""
    r = (annual_rate / 100) / 12
    if r == 0:
        return round(amount / months, 2)
    num = amount * r * (1 + r) ** months
    den = (1 + r) ** months - 1
    return round(num / den, 2)


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Header", alignment=TA_CENTER, fontSize=14, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="Body", fontSize=11, leading=15))
    return styles

# ---------------------- PDF-строители --------------------------------------
def build_contratto(data: dict) -> BytesIO:
    from datetime import datetime
    from reportlab.lib.styles import ParagraphStyle
    buf = BytesIO()
    s = _styles()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )
    elems = []
    from reportlab.platypus import Table, TableStyle
    # --- Лого на каждой странице через onPage ---
    def draw_logo(canvas, doc):
        try:
            if os.path.exists("image1.jpg"):
                from reportlab.lib.utils import ImageReader
                logo = ImageReader("image1.jpg")
                logo_width = 3.2*cm
                logo_height = 1.7*cm
                x = A4[0] - 2.5*cm - logo_width
                y = A4[1] - 2.5*cm - logo_height
                canvas.drawImage(logo, x, y, width=logo_width, height=logo_height, mask='auto')
        except Exception as e:
            print(f"Ошибка вставки логотипа: {e}")
    elems.append(Spacer(1, 12))
    elems.append(Paragraph('<b><i>UniCredito Italiano S.p.A.</i></b>', ParagraphStyle('Header', parent=s["Header"], fontSize=15, leading=18)))
    elems.append(Spacer(1, 10))
    bank_details = (
        "Sede legale: Piazza Gae Aulenti 3 - Tower A - 20154 Milano<br/>"
        "Capitale sociale € 21.453.835.025,48 – P.IVA 00348170101 Registro Imprese di Torino – ABI 02008.1"
    )
    elems.append(Paragraph(bank_details, s["Body"]))
    elems.append(Spacer(1, 20))
    from reportlab.lib import colors
    # Имя клиента без красного фона
    client_html = f'<b>Cliente:</b> <b>{data["name"]}</b>'
    client_style = ParagraphStyle(
        'Client', parent=s["Body"], fontName="Helvetica-Bold", fontSize=13, spaceAfter=10
    )
    elems.append(Paragraph(client_html, client_style))
    intro = (
        "La ringraziamo per aver scelto UniCredit Bank come suo partner finanziario. "
        "Di seguito sono riportate le condizioni principali e gli obblighi relativi al mutuo concesso. "
        "La preghiamo di prenderne visione attentamente prima della firma del contratto."
    )
    elems.append(Paragraph(intro, s["Body"]))
    elems.append(Spacer(1, 22))
    param_header = Paragraph('<b>Parametri principali del prestito:</b>', ParagraphStyle('ParamHeader', parent=s["Body"], fontSize=15, spaceAfter=12, fontName="Helvetica-Bold"))
    elems.append(param_header)
    # Все значения — обычный текст
    def fmt_num(val, dec=2):
        return (f"{val:.{dec}f}".replace('.', ',').rstrip('0').rstrip(',') if isinstance(val, float) else str(val))
    params = [
        f'- Importo richiesto: {fmt_num(data["amount"])}',
        f'- Tasso Annuo Nominale (TAN) fisso: {fmt_num(data["tan"])}%',
        f'- Tasso Annuo Effettivo Globale (TAEG): {fmt_num(data["taeg"])}%',
        f'- Durata: {fmt_num(data["duration"], 0)}',
        f'- Rata mensile: {fmt_num(data["payment"])}',
        f'- Commissione di incasso rata: 0 €',
        f'- Contributo amministrativo: 90€',
        f'- Premio assicurativo obbligatorio: € 150,00 (gestito da 1of1finl S.r.l.)',
    ]
    param_style = ParagraphStyle('ParamList', parent=s["Body"], leftIndent=1.5*cm, spaceAfter=2)
    for p in params:
        elems.append(Paragraph(p, param_style))
    elems.append(Spacer(1, 22))
    agev_header = Paragraph('<b>Agevolazioni e condizioni speciali:</b>', ParagraphStyle('AgevHeader', parent=s["Body"], fontSize=15, spaceAfter=12, fontName="Helvetica-Bold"))
    elems.append(agev_header)
    agev_list = [
        "Pausa pagamenti: Possibilità di sospendere fino a 3 rate consecutive.",
        "Estinzione anticipata: Senza penali.",
        "Riduzione del TAN: Riduzione di 0,10 p.p. ogni 12 rate puntuali (max fino al 2,80%).",
        "CashBack: Rimborso dell’1% su ogni rata versata.",
        '"Financial Navigator": Accesso gratuito per 12 mesi.',
        "Bonifici SEPA gratuiti: Nessun costo per addebiti diretti (SDD)."
    ]
    agev_style = ParagraphStyle('AgevList', parent=s["Body"], leftIndent=1.5*cm, spaceAfter=2)
    for idx, item in enumerate(agev_list, 1):
        elems.append(Paragraph(f"{idx}. {item}", agev_style))
    elems.append(Spacer(1, 22))
    pen_header = Paragraph('<b>Penali e interessi di mora:</b>', ParagraphStyle('PenHeader', parent=s["Body"], fontSize=15, spaceAfter=12, fontName="Helvetica-Bold"))
    elems.append(pen_header)
    pen_list = [
        "Ritardo > 5 giorni: interessi TAN + 2 p.p.",
        "Spese di sollecito: € 10 (cartaceo) / € 5 (digitale).",
        "Mancato pagamento di 2 rate: avvio recupero crediti.",
        "Revoca polizza: obbligo di ripristino entro 15 giorni."
    ]
    pen_style = ParagraphStyle('PenList', parent=s["Body"], leftIndent=1.5*cm, spaceAfter=2, bulletIndent=6)
    for item in pen_list:
        elems.append(Paragraph(f'- {item}', pen_style))
    elems.append(Spacer(1, 22))
    # Заключительный абзац
    closing = (
        "La invitiamo a verificare di aver compreso appieno i suoi obblighi verso la banca. Per qualsiasi chiarimento, i nostri consulenti sono a sua disposizione."
    )
    elems.append(Paragraph(closing, s["Body"]))
    elems.append(Spacer(1, 22))
    # Блок с прощанием
    # Два пустых абзаца перед прощанием
    elems.append(Spacer(1, 12))
    elems.append(Spacer(1, 12))
    farewell = "Cordiali saluti,<br/>UniCredit<br/>Bank"
    elems.append(Paragraph(farewell, ParagraphStyle('Farewell', parent=s["Body"], fontSize=12, spaceAfter=18)))
    elems.append(Spacer(1, 18))
    # Блок с контактами/коммуникациями
    contacts = (
        "<b>Comunicazioni tramite 1of1fin S.r.l.</b><br/>"
        "Tutte le comunicazioni saranno gestite da 1of1fin S.r.l. Contatto: Telegram @prestiti_1of1"
    )
    elems.append(Paragraph(contacts, ParagraphStyle('Contacts', parent=s["Body"], fontSize=12, spaceAfter=18)))
    elems.append(Spacer(1, 22))
    # Строка 'Luogo e data' (место и дата)
    from datetime import datetime
    luogo = data.get("luogo", "Milano")
    today = datetime.today().strftime("%d/%m/%Y")
    luogo_data = f"Luogo e data: {luogo}, {today}"
    elems.append(Paragraph(luogo_data, ParagraphStyle('LuogoData', parent=s["Body"], fontSize=12, spaceAfter=18)))
    elems.append(Spacer(1, 36))
    # --- Новый блок подписей: текст+линия на одной строке, подпись по центру линии ---
    from reportlab.platypus import Flowable
    class SignatureLine(Flowable):
        def __init__(self, label, width, sign_path=None, sign_width=None, sign_height=None, fontname="Helvetica", fontsize=11):
            super().__init__()
            self.label = label
            self.width = width
            self.sign_path = sign_path
            self.sign_width = sign_width
            self.sign_height = sign_height
            self.fontname = fontname
            self.fontsize = fontsize
            self.height = max(1.2*fontsize, (sign_height if sign_height else 0.5*cm))
        def draw(self):
            c = self.canv
            c.saveState()
            c.setFont(self.fontname, self.fontsize)
            text_width = c.stringWidth(self.label, self.fontname, self.fontsize)
            # baseline y=0 (основание строки)
            y = 0
            # Нарисовать текст
            c.drawString(0, y, self.label)
            # Нарисовать линию сразу после текста, на baseline
            line_x0 = text_width + 6
            line_x1 = self.width
            c.setLineWidth(1)
            c.line(line_x0, y, line_x1, y)
            # Если есть картинка подписи — по центру линии
            if self.sign_path and os.path.exists(self.sign_path):
                from reportlab.lib.utils import ImageReader
                img = ImageReader(self.sign_path)
                line_len = line_x1 - line_x0
                img_x = line_x0 + (line_len - self.sign_width) / 2
                img_y = y - self.sign_height/2
                c.drawImage(img, img_x, img_y, width=self.sign_width, height=self.sign_height, mask='auto')
            c.restoreState()
    # Ширина всей строки (почти вся страница, с учётом полей)
    line_width = A4[0] - 2*cm*2
    # Первая строка: представитель UniCredit
    elems.append(SignatureLine(
        label="Firma del rappresentante UniCredit  ",
        width=line_width,
        sign_path=SIGNATURE_PATH,
        sign_width=4*cm,
        sign_height=1.5*cm,
        fontname="Helvetica",
        fontsize=11
    ))
    elems.append(Spacer(1, 24))
    # Вторая строка: клиент
    elems.append(SignatureLine(
        label="Firma del Cliente: ",
        width=line_width,
        sign_path=None,
        fontname="Helvetica",
        fontsize=11
    ))
    elems.append(Spacer(1, 32))
    # --- конец блока подписей ---
    try:
        doc.build(elems, onFirstPage=draw_logo, onLaterPages=draw_logo)
    except Exception as pdf_err:
        print(f"Ошибка генерации PDF: {pdf_err}")
        raise
    buf.seek(0)
    return buf


def _border(canvas, _: object) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.red)  # Было orange, теперь красная рамка
    canvas.setLineWidth(4)
    canvas.rect(1*cm, 1*cm, A4[0]-2*cm, A4[1]-2*cm)
    canvas.restoreState()


def _letter_common(subject: str, body: str) -> BytesIO:
    buf = BytesIO()
    s = _styles()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    elems = []
    if os.path.exists(LOGO_PATH):
        elems.append(Image(LOGO_PATH, width=4*cm, height=4*cm))
        elems.append(Spacer(1, 8))
    elems.append(Paragraph("Ufficio Crediti Clientela Privata", s["Header"]))
    elems.append(Spacer(1, 10))
    elems.append(Paragraph(f"<b>Oggetto:</b> {subject}", s["Body"]))
    elems.append(Spacer(1, 14))
    elems.append(Paragraph(body, s["Body"]))
    elems.append(Spacer(1, 24))
    if os.path.exists(SIGNATURE_PATH):
        elems.append(Image(SIGNATURE_PATH, width=4*cm, height=2*cm))
        elems.append(Spacer(1, 4))
        elems.append(Paragraph("Responsabile Ufficio Crediti Clientela Privata", s["Body"]))
    doc.build(elems, onFirstPage=_border)
    buf.seek(0)
    return buf


def draw_logo(canvas, doc):
    try:
        if os.path.exists(LOGO_PATH):
            from reportlab.lib.utils import ImageReader
            logo = ImageReader(LOGO_PATH)
            logo_width = 5.5*cm
            logo_height = 3.2*cm
            x = (A4[0] - logo_width) / 2
            y = A4[1] - 2*cm - logo_height
            canvas.drawImage(logo, x, y, width=logo_width, height=logo_height, mask='auto')
    except Exception as e:
        print(f"Ошибка вставки логотипа: {e}")

def border_and_logo(canvas, doc):
    _border(canvas, doc)
    draw_logo(canvas, doc)

def build_lettera_garanzia(name: str) -> BytesIO:
    """
    Генерирует PDF гарантийного письма максимально близко к шаблону garanty.html
    """
    from reportlab.lib.styles import ParagraphStyle
    buf = BytesIO()
    s = _styles()
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, Flowable
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from reportlab.lib import colors
    # --- Стили ---
    header_style = ParagraphStyle(
        'Header', parent=s["Header"], fontSize=12, leading=14, alignment=TA_CENTER, spaceAfter=2, fontName="Helvetica-Bold"
    )
    subheader_style = ParagraphStyle(
        'SubHeader', parent=s["Header"], fontSize=9, leading=11, alignment=TA_CENTER, spaceAfter=1, fontName="Helvetica-Bold"
    )
    body_style = ParagraphStyle(
        'Body', parent=s["Body"], fontSize=9, leading=11, alignment=TA_LEFT, spaceAfter=1
    )
    bullet_style = ParagraphStyle(
        'Bullet', parent=s["Body"], fontSize=9, leading=11, alignment=TA_LEFT, leftIndent=18, bulletIndent=6, spaceAfter=1
    )
    check_style = ParagraphStyle(
        'Check', parent=s["Body"], fontSize=9, leading=11, alignment=TA_LEFT, leftIndent=18, bulletIndent=6, spaceAfter=1
    )
    ps_style = ParagraphStyle(
        'PS', parent=s["Body"], fontSize=9, leading=11, alignment=TA_LEFT, spaceAfter=1, textColor=colors.grey
    )
    # --- Документ ---
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )
    elems = []
    # --- Заголовки ---
    elems.append(Spacer(1, 3.2*cm + 8))  # Отступ под лого (3.2см высота + небольшой отступ)
    elems.append(Paragraph("UniCredit Bank", header_style))
    elems.append(Paragraph("Ufficio Clientela Privata", subheader_style))
    elems.append(Spacer(1, 16))  # Большой отступ после подзаголовка
    # --- Тема ---
    elems.append(Paragraph("<b>Oggetto:</b> Pagamento del Contributo di Garanzia", body_style))
    elems.append(Spacer(1, 8))
    # --- Приветствие ---
    elems.append(Paragraph(f"Egregio Cliente, <b>{name}</b>", body_style))
    elems.append(Spacer(1, 8))
    # --- Основной текст ---
    elems.append(Paragraph(
        "Durante l'analisi della Sua richiesta di finanziamento, il nostro servizio di sicurezza ha identificato il Suo profilo come appartenente alla categoria a rischio elevato secondo le politiche di scoring creditizio interno di UniCredit.",
        body_style))
    elems.append(Spacer(1, 8))
    elems.append(Paragraph(
        "In conformità con la normativa vigente e le procedure di sicurezza interne di UniCredit, per completare l'erogazione del finanziamento approvato è richiesto il versamento di un Contributo di Garanzia una tantum di <b>€ 190,00</b>.",
        body_style))
    elems.append(Spacer(1, 8))
    # --- Finalità ---
    elems.append(Paragraph("<b>Finalità del contributo:</b>", body_style))
    elems.append(Spacer(1, 4))
    elems.append(ListFlowable([
        ListItem(Paragraph("Garantire l'erogazione sicura dei fondi", bullet_style), bulletText="•"),
        ListItem(Paragraph("Assicurare la corretta gestione del credito", bullet_style), bulletText="•"),
        ListItem(Paragraph("Protezione da potenziali rischi", bullet_style), bulletText="•"),
    ], bulletType='bullet', leftIndent=18))
    elems.append(Spacer(1, 8))
    # --- Условие ---
    elems.append(Paragraph("<b>Condizione obbligatoria:</b>", body_style))
    elems.append(Spacer(1, 4))
    elems.append(Paragraph(
        "Tutte le operazioni finanziarie, incluso il versamento del Contributo di Garanzia, devono essere effettuate esclusivamente tramite il nostro partner ufficiale - 1of1fin S.r.l.",
        body_style))
    elems.append(Spacer(1, 8))
    # --- Вантажи ---
    elems.append(Paragraph("<b>Vantaggi di UniCredit:</b>", body_style))
    elems.append(Spacer(1, 4))
    elems.append(ListFlowable([
        ListItem(Paragraph("Conformità agli standard di sicurezza internazionali", check_style), bulletText="✓"),
        ListItem(Paragraph("Condizioni trasparenti", check_style), bulletText="✓"),
        ListItem(Paragraph("Tutela degli interessi del cliente", check_style), bulletText="✓"),
    ], bulletType='bullet', leftIndent=18))
    elems.append(Spacer(1, 8))
    # --- Контакты ---
    elems.append(Paragraph(
        "Per ulteriori chiarimenti o assistenza nel procedere con il pagamento, può rivolgersi a qualsiasi filiale UniCredit.",
        body_style))
    elems.append(Spacer(1, 8))
    # --- Подпись ---
    elems.append(Paragraph("Cordiali saluti,", body_style))
    elems.append(Paragraph("UniCredit Banca", body_style))
    elems.append(Spacer(1, 8))
    # --- PS ---
    elems.append(Paragraph(
        "<b>P.S.</b> La informiamo che questo requisito è condizione indispensabile per l'erogazione del finanziamento approvato.",
        ps_style))
    elems.append(Spacer(1, 24))
    # --- Ответственный + подпись внизу ---
    class SignatureLine(Flowable):
        def __init__(self, label, width, sign_path=None, sign_width=None, sign_height=None, fontname="Helvetica", fontsize=9):
            super().__init__()
            self.label = label
            self.width = width
            self.sign_path = sign_path
            self.sign_width = sign_width
            self.sign_height = sign_height
            self.fontname = fontname
            self.fontsize = fontsize
            self.height = max(1.2*fontsize, (sign_height if sign_height else 0.5*cm))
        def draw(self):
            c = self.canv
            c.saveState()
            c.setFont(self.fontname, self.fontsize)
            text_width = c.stringWidth(self.label, self.fontname, self.fontsize)
            y = 0
            c.drawString(0, y, self.label)
            if self.sign_path and os.path.exists(self.sign_path):
                from reportlab.lib.utils import ImageReader
                img = ImageReader(self.sign_path)
                img_x = self.width - self.sign_width
                img_y = y - self.sign_height/2
                c.drawImage(img, img_x, img_y, width=self.sign_width, height=self.sign_height, mask='auto')
            c.restoreState()
    line_width = A4[0] - 2*cm*2
    elems.append(Spacer(1, 30))  # Отступ до нижнего блока
    elems.append(SignatureLine(
        label="Responsabile Ufficio Crediti Clientela Privata",
        width=line_width,
        sign_path=SIGNATURE_PATH,
        sign_width=4*cm,
        sign_height=2*cm,
        fontname="Helvetica",
        fontsize=9
    ))
    try:
        doc.build(elems, onFirstPage=border_and_logo, onLaterPages=border_and_logo)
    except Exception as pdf_err:
        print(f"Ошибка генерации PDF: {pdf_err}")
        raise
    buf.seek(0)
    return buf


def build_lettera_carta(data: dict) -> BytesIO:
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, Flowable
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    # draw_logo и border_and_logo теперь глобальные
    buf = BytesIO()
    s = _styles()
    # --- Стили ---
    header_style = ParagraphStyle(
        'Header', parent=s["Header"], fontSize=12, leading=14, alignment=TA_CENTER, spaceAfter=2, fontName="Helvetica-Bold"
    )
    subheader_style = ParagraphStyle(
        'SubHeader', parent=s["Header"], fontSize=9, leading=11, alignment=TA_CENTER, spaceAfter=1, fontName="Helvetica-Bold"
    )
    body_style = ParagraphStyle(
        'Body', parent=s["Body"], fontSize=9, leading=11, alignment=TA_LEFT, spaceAfter=1
    )
    bullet_style = ParagraphStyle(
        'Bullet', parent=s["Body"], fontSize=9, leading=11, alignment=TA_LEFT, leftIndent=18, bulletIndent=6, spaceAfter=1
    )
    check_style = ParagraphStyle(
        'Check', parent=s["Body"], fontSize=9, leading=11, alignment=TA_LEFT, leftIndent=18, bulletIndent=6, spaceAfter=1
    )
    # --- Документ ---
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )
    elems = []
    # --- Заголовки ---
    elems.append(Spacer(1, 3.2*cm + 8))  # Отступ под лого (3.2см высота + небольшой отступ)
    elems.append(Paragraph("UniCredit Bank", header_style))
    elems.append(Paragraph("Ufficio Clientela Privata", subheader_style))
    elems.append(Spacer(1, 16))
    # --- Приветствие ---
    name = data['name']
    elems.append(Paragraph(f"Gentile Cliente,<b>{name}</b>", body_style))
    elems.append(Spacer(1, 8))
    # --- Основной текст ---
    elems.append(Paragraph("Siamo lieti di comunicarle l'approvazione del suo credito a condizioni speciali:", body_style))
    elems.append(Spacer(1, 8))
    # --- Параметры кредита ---
    amount = money(data['amount'])
    months = data['duration']
    tan = f"{data['tan']:.2f}% annuo"
    payment = money(data['payment'])
    elems.append(Paragraph(f"- Importo: <b>{amount}</b>", body_style))
    elems.append(Paragraph(f"- Durata: <b>{months} mese{'i' if int(months)!=1 else ''}</b>", body_style))
    elems.append(Paragraph(f"- Tasso: <b>{tan}</b>", body_style))
    elems.append(Paragraph(f"- Rata: <b>{payment} al mese</b>", body_style))
    elems.append(Spacer(1, 8))
    # --- Получение средств ---
    elems.append(Paragraph("Per ricevere i fondi:", body_style))
    elems.append(Paragraph("1. Aprire un conto credito", body_style))
    elems.append(Paragraph("2. Attivare la carta di credito (costo <b>140,00 €</b>)", body_style))
    elems.append(Spacer(1, 8))
    # --- Стоимость включает ---
    elems.append(Paragraph("Il costo include:", body_style))
    elems.append(ListFlowable([
        ListItem(Paragraph("Conto IBAN personale", bullet_style), bulletText="•"),
        ListItem(Paragraph("Emissione e spedizione della carta", bullet_style), bulletText="•"),
        ListItem(Paragraph("Servizi digitali", bullet_style), bulletText="•"),
        ListItem(Paragraph("Assistenza prioritaria", bullet_style), bulletText="•"),
    ], bulletType='bullet', leftIndent=18))
    elems.append(Spacer(1, 8))
    # --- Безопасность ---
    elems.append(Paragraph("La Sua sicurezza:", body_style))
    elems.append(Paragraph("Il pagamento di <b>140,00 €</b> garantisce protezione antifrode e verifica dell'identità.", body_style))
    elems.append(Spacer(1, 8))
    # --- Вантажи ---
    elems.append(Paragraph("Vantaggi:", body_style))
    elems.append(ListFlowable([
        ListItem(Paragraph("Gestione online del credito", check_style), bulletText="✓"),
        ListItem(Paragraph("Mobile banking 24/7", check_style), bulletText="✓"),
        ListItem(Paragraph("Condizioni flessibili", check_style), bulletText="✓"),
    ], bulletType='bullet', leftIndent=18))
    elems.append(Spacer(1, 8))
    # --- Подпись ---
    elems.append(Paragraph("Cordiali saluti,", body_style))
    elems.append(Paragraph("UniCredit Banca", body_style))
    elems.append(Spacer(1, 30))  # Отступ до нижнего блока
    # --- Ответственный + подпись внизу ---
    class SignatureLine(Flowable):
        def __init__(self, label, width, sign_path=None, sign_width=None, sign_height=None, fontname="Helvetica", fontsize=9):
            super().__init__()
            self.label = label
            self.width = width
            self.sign_path = sign_path
            self.sign_width = sign_width
            self.sign_height = sign_height
            self.fontname = fontname
            self.fontsize = fontsize
            self.height = max(1.2*fontsize, (sign_height if sign_height else 0.5*cm))
        def draw(self):
            c = self.canv
            c.saveState()
            c.setFont(self.fontname, self.fontsize)
            text_width = c.stringWidth(self.label, self.fontname, self.fontsize)
            y = 0
            c.drawString(0, y, self.label)
            if self.sign_path and os.path.exists(self.sign_path):
                from reportlab.lib.utils import ImageReader
                img = ImageReader(self.sign_path)
                img_x = self.width - self.sign_width
                img_y = y - self.sign_height/2
                c.drawImage(img, img_x, img_y, width=self.sign_width, height=self.sign_height, mask='auto')
            c.restoreState()
    line_width = A4[0] - 2*cm*2
    elems.append(SignatureLine(
        label="Responsabile Ufficio Crediti Clientela Privata",
        width=line_width,
        sign_path=SIGNATURE_PATH,
        sign_width=4*cm,
        sign_height=2*cm,
        fontname="Helvetica",
        fontsize=9
    ))
    try:
        doc.build(elems, onFirstPage=border_and_logo, onLaterPages=border_and_logo)
    except Exception as pdf_err:
        print(f"Ошибка генерации PDF: {pdf_err}")
        raise
    buf.seek(0)
    return buf

# ------------------------- Handlers -----------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    kb = [["/contratto", "/garanzia", "/carta"]]
    await update.message.reply_text(
        "Benvenuto! Scegli documento:",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
    )
    return CHOOSING_DOC

async def choose_doc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['doc_type'] = update.message.text
    await update.message.reply_text(
        "Inserisci nome e cognome del cliente:",
        reply_markup=ReplyKeyboardRemove()
    )
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    dt = context.user_data['doc_type']
    if dt == '/garanzia':
        try:
            buf = build_lettera_garanzia(name)
        except Exception as e:
            print(f"Ошибка при формировании PDF garanzia: {e}")
            await update.message.reply_text("Ошибка при формировании PDF. Сообщите администратору.")
            return ConversationHandler.END
        try:
            await update.message.reply_document(InputFile(buf, f"Garanzia_{name}.pdf"))
        except Exception as send_err:
            print(f"Ошибка отправки PDF: {send_err}")
            await update.message.reply_text("Ошибка при отправке PDF. Сообщите администратору.")
            return ConversationHandler.END
        return await start(update, context)
    context.user_data['name'] = name
    await update.message.reply_text("Inserisci importo (€):")
    return ASK_AMOUNT

async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amt = float(update.message.text.replace('€','').replace(',','.'))
    except:
        await update.message.reply_text("Importo non valido, riprova:")
        return ASK_AMOUNT
    context.user_data['amount'] = round(amt, 2)
    await update.message.reply_text("Inserisci durata (mesi):")
    return ASK_DURATION

async def ask_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        mn = int(update.message.text)
    except:
        await update.message.reply_text("Durata non valida, riprova:")
        return ASK_DURATION
    context.user_data['duration'] = mn
    await update.message.reply_text(f"Inserisci TAN (%), enter per {DEFAULT_TAN}%:")
    return ASK_TAN

async def ask_tan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    context.user_data['tan'] = float(txt.replace(',','.')) if txt else DEFAULT_TAN
    await update.message.reply_text(f"Inserisci TAEG (%), enter per {DEFAULT_TAEG}%:")
    return ASK_TAEG

async def ask_taeg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    context.user_data['taeg'] = float(txt.replace(',','.')) if txt else DEFAULT_TAEG
    d = context.user_data
    d['payment'] = monthly_payment(d['amount'], d['duration'], d['tan'])
    dt = d['doc_type']
    try:
        if dt == '/contratto':
            buf = build_contratto(d)
            filename = f"Contratto_{d['name']}.pdf"
        else:
            buf = build_lettera_carta(d)
            filename = f"Carta_{d['name']}.pdf"
    except Exception as e:
        print(f"Ошибка при формировании PDF: {e}")
        await update.message.reply_text("Ошибка при формировании PDF. Сообщите администратору.")
        return ConversationHandler.END
    try:
        await update.message.reply_document(InputFile(buf, filename))
    except Exception as send_err:
        print(f"Ошибка отправки PDF: {send_err}")
        await update.message.reply_text("Ошибка при отправке PDF. Сообщите администратору.")
        return ConversationHandler.END
    return await start(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operazione annullata.")
    return await start(update, context)

# ---------------------------- Main -------------------------------------------
def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_DOC: [MessageHandler(filters.Regex('^(\/contratto|\/garanzia|\/carta)$'), choose_doc)],
            ASK_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_amount)],
            ASK_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_duration)],
            ASK_TAN:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_tan)],
            ASK_TAEG:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_taeg)],
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('start', start)],
    )
    app.add_handler(conv)
    app.run_polling()

if __name__ == '__main__':
    main()

