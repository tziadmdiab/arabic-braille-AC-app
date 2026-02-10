# -*- coding: utf-8 -*-
import re
import io
import hashlib
from datetime import datetime

import streamlit as st

# =========================
# App metadata
# =========================
APP_NAME = "محوّل عربي ↔ بريل"
APP_COMPANY = "أكاديمية الموهبة المشتركة"
APP_VERSION = "1.4.0"

# =========================
# Optional libraries
# =========================
try:
    from docx import Document
except Exception:
    Document = None

try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
except Exception:
    rl_canvas = None
    A4 = None
    pdfmetrics = None
    TTFont = None

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except Exception:
    arabic_reshaper = None
    get_display = None

try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    from PIL import Image
except Exception:
    Image = None

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None


# =========================
# Helpers
# =========================
TASHKEEL_RE = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0670\u0653-\u0655]")

def normalize_newlines(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")

def remove_tashkeel(text: str) -> str:
    return re.sub(TASHKEEL_RE, "", text or "")

def file_hash(b: bytes) -> str:
    return hashlib.sha256(b or b"").hexdigest()

# =========================
# Arabic <-> Braille maps
# =========================
NUM_SIGN = "⠼"

AR2BR = {
    "ا":"⠁","أ":"⠁","إ":"⠁","آ":"⠁",
    "ب":"⠃","ت":"⠞","ث":"⠹","ج":"⠚","ح":"⠱","خ":"⠭",
    "د":"⠙","ذ":"⠮","ر":"⠗","ز":"⠵","س":"⠎","ش":"⠩",
    "ص":"⠯","ض":"⠷","ط":"⠾","ظ":"⠿","ع":"⠫","غ":"⠣",
    "ف":"⠋","ق":"⠟","ك":"⠅","ل":"⠇","م":"⠍","ن":"⠝",
    "ه":"⠓","ة":"⠓","و":"⠺","ي":"⠊","ى":"⠊",

    "ء":"⠄",
    "ؤ":"⠺⠄",
    "ئ":"⠊⠄",

    " ":" ",
    "\n":"\n",
    "\t":"\t",

    "،":"⠂", ",":"⠂",
    ".":"⠲", "۔":"⠲",
    "؛":"⠆", ";":"⠆",
    ":":"⠒",
    "؟":"⠦", "?":"⠦",
    "!":"⠖",
    "-":"⠤","_":"⠤","ـ":"⠤",
    '"':"⠶",
    "“":"⠶","”":"⠶",
    "(":"⠶",")":"⠶",

    "«":"⠦⠦",
    "»":"⠴⠴",
}

DIGIT_TO_BR = {
    "1":"⠁","2":"⠃","3":"⠉","4":"⠙","5":"⠑",
    "6":"⠋","7":"⠛","8":"⠓","9":"⠊","0":"⠚",
}

ARABIC_DIGITS_TO_LATIN = {
    "٠":"0","١":"1","٢":"2","٣":"3","٤":"4",
    "٥":"5","٦":"6","٧":"7","٨":"8","٩":"9",
}
LATIN_TO_ARABIC_DIGITS = {
    "0":"٠","1":"١","2":"٢","3":"٣","4":"٤",
    "5":"٥","6":"٦","7":"٧","8":"٨","9":"٩",
}

BR2AR = {}
for k, v in AR2BR.items():
    if len(k) == 1 and v not in BR2AR:
        BR2AR[v] = k

BR_TO_DIGIT = {v: k for k, v in DIGIT_TO_BR.items()}

EXTRA_BR2AR = {
    "⠂":"،",
    "⠲":".",
    "⠆":"؛",
    "⠒":":",
    "⠦":"؟",
    "⠖":"!",
    "⠤":"-",
    "⠶":'"',
}

ALEF_FORMS = {"ا","أ","إ","آ"}

def normalize_digits_to_latin(text: str) -> str:
    return "".join(ARABIC_DIGITS_TO_LATIN.get(ch, ch) for ch in (text or ""))

# =========================
# Conversion
# =========================
def arabic_to_braille(text: str, keep_tashkeel: bool = False) -> str:
    text = normalize_newlines(text)
    if not keep_tashkeel:
        text = remove_tashkeel(text)
    text = normalize_digits_to_latin(text)

    out = []
    i = 0
    in_number = False

    while i < len(text):
        if i + 1 < len(text) and text[i] == "ل" and text[i+1] in ALEF_FORMS:
            in_number = False
            out.append(AR2BR.get("ل", "⍰"))
            out.append(AR2BR.get(text[i+1], "⍰"))
            i += 2
            continue

        ch = text[i]

        if ch.isdigit():
            if not in_number:
                out.append(NUM_SIGN)
                in_number = True
            out.append(DIGIT_TO_BR.get(ch, "⍰"))
            i += 1
            continue

        in_number = False
        out.append(AR2BR.get(ch, "⍰"))
        i += 1

    return "".join(out)

def braille_to_arabic(braille_text: str, arabic_digits: bool = True) -> str:
    braille_text = normalize_newlines(braille_text)
    out = []
    i = 0
    in_number = False

    while i < len(braille_text):
        if i + 1 < len(braille_text):
            two = braille_text[i:i+2]
            if two == "⠦⠦":
                out.append("«"); i += 2; in_number = False; continue
            if two == "⠴⠴":
                out.append("»"); i += 2; in_number = False; continue

        ch = braille_text[i]

        if ch == NUM_SIGN:
            in_number = True
            i += 1
            continue

        if ch in (" ", "\n", "\t"):
            in_number = False
            out.append(ch)
            i += 1
            continue

        if in_number:
            digit = BR_TO_DIGIT.get(ch)
            if digit is not None:
                out.append(LATIN_TO_ARABIC_DIGITS[digit] if arabic_digits else digit)
                i += 1
                continue
            in_number = False

        out.append(BR2AR.get(ch, EXTRA_BR2AR.get(ch, "؟")))
        i += 1

    return "".join(out)

# =========================
# PDF/TXT/OCR
# =========================
def pdf_text_with_pypdf(pdf_bytes: bytes) -> str:
    if PdfReader is None:
        raise RuntimeError("pypdf غير مثبت.")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for p in reader.pages:
        pages.append(p.extract_text() or "")
    return normalize_newlines("\n".join(pages)).strip()

def ocr_image_bytes(image_bytes: bytes, lang: str = "ara") -> str:
    if pytesseract is None or Image is None:
        raise RuntimeError("OCR غير متاح: تأكد من تثبيت pytesseract و Pillow و tesseract-ocr.")
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return normalize_newlines(pytesseract.image_to_string(img, lang=lang)).strip()

def pdf_ocr_with_pymupdf(pdf_bytes: bytes, lang: str = "ara", max_pages: int = 10) -> str:
    if fitz is None:
        raise RuntimeError("PyMuPDF غير مثبت.")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texts = []
    n = min(len(doc), max_pages)
    for i in range(n):
        page = doc[i]
        pix = page.get_pixmap(dpi=220)
        img_bytes = pix.tobytes("png")
        t = ocr_image_bytes(img_bytes, lang=lang)
        if t:
            texts.append(t)
    return "\n\n".join(texts).strip()

def extract_text_from_file(name: str, data: bytes, ocr_lang: str, pdf_pages: int) -> tuple[str, str]:
    name_l = (name or "").lower()

    if name_l.endswith(".txt"):
        try:
            t = normalize_newlines(data.decode("utf-8", errors="replace")).strip()
            return t, f"TXT ({len(t)} حرف)"
        except Exception as e:
            return "", f"TXT فشل: {e}"

    if name_l.endswith((".png", ".jpg", ".jpeg")):
        try:
            t = ocr_image_bytes(data, lang=ocr_lang)
            return t, f"صورة OCR ({len(t)} حرف)"
        except Exception as e:
            return "", f"OCR فشل: {e}"

    if name_l.endswith(".pdf"):
        # 1) try text
        try:
            t = pdf_text_with_pypdf(data)
            if t.strip():
                return t, f"PDF نصي ({len(t)} حرف)"
        except Exception:
            pass
        # 2) OCR
        try:
            t2 = pdf_ocr_with_pymupdf(data, lang=ocr_lang, max_pages=pdf_pages)
            if t2.strip():
                return t2, f"PDF OCR ({len(t2)} حرف)"
            return "", "PDF OCR: لم يرجع نصًا"
        except Exception as e:
            return "", f"PDF OCR فشل: {e}"

    return "", "نوع ملف غير مدعوم"

# =========================
# Export
# =========================
def export_to_word_bytes(text: str) -> bytes:
    if Document is None:
        raise RuntimeError("python-docx غير مثبت.")
    doc = Document()
    for line in normalize_newlines(text).split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

def _shape_arabic(text: str) -> str:
    if arabic_reshaper and get_display:
        return get_display(arabic_reshaper.reshape(text))
    return text

def export_to_pdf_bytes(text: str, assume_arabic: bool = True) -> bytes:
    if rl_canvas is None or A4 is None:
        raise RuntimeError("reportlab غير مثبت.")
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 50
    y = height - margin

    font_name = "Helvetica"
    if pdfmetrics and TTFont:
        for fp in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        ]:
            try:
                pdfmetrics.registerFont(TTFont("DejaVuSans", fp))
                font_name = "DejaVuSans"
                break
            except Exception:
                pass

    c.setFont(font_name, 12)
    for line in normalize_newlines(text).split("\n"):
        if y < margin:
            c.showPage()
            c.setFont(font_name, 12)
            y = height - margin
        draw_line = _shape_arabic(line) if assume_arabic else line
        c.drawString(margin, y, draw_line)
        y -= 18
    c.save()
    return buf.getvalue()

# =========================
# Streamlit UI
# =========================
st.set_page_config(page_title=APP_NAME, layout="wide")

# keys for widgets
IN_KEY = "in_text_area"
OUT_KEY = "out_text_area"

# defaults
st.session_state.setdefault(IN_KEY, "")
st.session_state.setdefault(OUT_KEY, "")
st.session_state.setdefault("last_upload_hash", "")

st.title(APP_NAME)
st.caption(f"الجهة: {APP_COMPANY} — الإصدار {APP_VERSION}")

with st.sidebar:
    st.header("الإعدادات")
    direction = st.radio("الاتجاه", ["عربي → بريل", "بريل → عربي"], index=0, key="dir_radio")
    keep_tashkeel = st.checkbox("عدم حذف التشكيل (قد يظهر ⍰ لبعض الحركات)", value=False, key="keep_tashkeel")
    arabic_digits_out = st.checkbox("عند (بريل → عربي) استخدم الأرقام العربية ٠١٢٣…", value=True, key="arabic_digits_out")

    st.divider()
    uploaded = st.file_uploader(
        "رفع ملف (TXT / PDF / صورة)",
        type=["txt", "pdf", "png", "jpg", "jpeg"],
        key="uploader_main",
    )

    st.subheader("خيارات PDF/OCR")
    ocr_lang = st.selectbox("لغة OCR", ["ara", "eng"], index=0, key="ocr_lang")
    pdf_pages = st.slider("عدد صفحات OCR للـ PDF الممسوح", 1, 30, 10, key="pdf_pages")
    auto_convert = st.checkbox("تحويل تلقائي بعد الرفع", value=True, key="auto_convert")

def do_convert(src: str) -> str:
    if direction == "عربي → بريل":
        return arabic_to_braille(src, keep_tashkeel=keep_tashkeel)
    return braille_to_arabic(src, arabic_digits=arabic_digits_out)

# ✅ استخراج تلقائي فور الرفع + تعبئة مربع النص مباشرة
if uploaded is not None:
    name = uploaded.name or ""
    data = uploaded.getvalue() or b""
    h = file_hash(data)

    # فقط إذا الملف جديد (عشان لا يعيد الاستخراج كل rerun)
    if h != st.session_state["last_upload_hash"]:
        text, note = extract_text_from_file(name, data, ocr_lang, pdf_pages)
        if text.strip():
            st.session_state[IN_KEY] = text
            if auto_convert:
                st.session_state[OUT_KEY] = do_convert(text)
            st.sidebar.success(f"تمت القراءة: {note}")
        else:
            st.sidebar.error(f"فشل استخراج النص: {note}")

        st.session_state["last_upload_hash"] = h

# ===== Main UI =====
col1, col2 = st.columns(2, gap="large")

with col1:
    st.subheader("النص الأصلي")
    st.text_area(
        label="النص الأصلي",
        key=IN_KEY,
        height=420,
        label_visibility="collapsed",
        placeholder="ارفع ملف ليتم إدخال النص هنا تلقائيًا… أو اكتب/الصق النص يدويًا",
    )

with col2:
    st.subheader("الناتج")
    st.text_area(
        label="الناتج",
        key=OUT_KEY,
        height=420,
        label_visibility="collapsed",
        placeholder="سيظهر الناتج هنا بعد التحويل",
    )

b1, b2, b3, b4 = st.columns([1, 1, 1, 1], gap="small")

with b1:
    if st.button("تحويل الآن", use_container_width=True, key="btn_convert"):
        st.session_state[OUT_KEY] = do_convert(st.session_state[IN_KEY])

with b2:
    if st.button("تبديل (Swap)", use_container_width=True, key="btn_swap"):
        st.session_state[IN_KEY], st.session_state[OUT_KEY] = st.session_state[OUT_KEY], st.session_state[IN_KEY]

with b3:
    if st.button("مسح الكل", use_container_width=True, key="btn_clear"):
        st.session_state[IN_KEY] = ""
        st.session_state[OUT_KEY] = ""

with b4:
    now = datetime.now().strftime("%Y%m%d-%H%M%S")
    st.download_button(
        "تحميل TXT",
        data=(st.session_state[OUT_KEY] or "").encode("utf-8"),
        file_name=f"output-{now}.txt",
        mime="text/plain; charset=utf-8",
        use_container_width=True,
        key="btn_download_txt",
    )

st.divider()

e1, e2 = st.columns(2)

with e1:
    try:
        if Document is None:
            raise RuntimeError("python-docx غير مثبت.")
        word_bytes = export_to_word_bytes(st.session_state[OUT_KEY])
        st.download_button(
            "تصدير Word (.docx)",
            data=word_bytes,
            file_name=f"output-{now}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="btn_word",
        )
    except Exception as e:
        st.info(f"Word غير متاح: {e}")

with e2:
    try:
        assume_arabic = (direction == "بريل → عربي")
        pdf_bytes = export_to_pdf_bytes(st.session_state[OUT_KEY], assume_arabic=assume_arabic)
        st.download_button(
            "تصدير PDF (.pdf)",
            data=pdf_bytes,
            file_name=f"output-{now}.pdf",
            mime="application/pdf",
            key="btn_pdf",
        )
    except Exception as e:
        st.error(f"فشل تصدير PDF: {e}")

st.caption("ملاحظة: إن كان PDF ممسوحًا، سيتم OCR تلقائيًا (إذا كانت الحزم مثبتة على الخادم).")
