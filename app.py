# -*- coding: utf-8 -*-
import re
import io
import unicodedata
from datetime import datetime
from collections import Counter, defaultdict

import streamlit as st

# =========================
# App metadata
# =========================
APP_NAME = "محوّل عربي ↔ بريل"
APP_COMPANY = "أكاديمية الموهبة المشتركة"
APP_VERSION = "1.3.1"

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
# 1) Text helpers
# =========================
TASHKEEL_RE = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0670\u0653-\u0655]")

def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")

def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFKC", text)

def remove_tashkeel(text: str) -> str:
    return re.sub(TASHKEEL_RE, "", text)

def clean_text_pipeline(text: str, keep_tashkeel: bool) -> str:
    text = normalize_newlines(text)
    text = normalize_unicode(text)
    if not keep_tashkeel:
        text = remove_tashkeel(text)
    return text

# =========================
# 2) Arabic <-> Braille maps
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
    return "".join(ARABIC_DIGITS_TO_LATIN.get(ch, ch) for ch in text)

# =========================
# 3) Conversion engine
# =========================
def arabic_to_braille(text: str, keep_tashkeel: bool = False) -> str:
    text = clean_text_pipeline(text, keep_tashkeel=keep_tashkeel)
    text = normalize_digits_to_latin(text)

    out = []
    i = 0
    in_number = False

    while i < len(text):
        if i + 1 < len(text) and text[i] == "ل" and text[i+1] in ALEF_FORMS:
            in_number = False
            out.append(AR2BR.get("ل", "ل"))
            out.append(AR2BR.get(text[i+1], text[i+1]))
            i += 2
            continue

        ch = text[i]

        if ch.isdigit():
            if not in_number:
                out.append(NUM_SIGN)
                in_number = True
            out.append(DIGIT_TO_BR.get(ch, ch))
            i += 1
            continue

        in_number = False
        out.append(AR2BR.get(ch, ch))  # مرّر غير المدعوم كما هو
        i += 1

    return "".join(out)

def braille_to_arabic(braille_text: str, arabic_digits: bool = True) -> str:
    braille_text = clean_text_pipeline(braille_text, keep_tashkeel=True)
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

        out.append(BR2AR.get(ch, EXTRA_BR2AR.get(ch, ch)))  # مرّر غير المدعوم كما هو
        i += 1

    return "".join(out)

# =========================
# 4) Unsupported symbols report
# =========================
def build_unsupported_report_ar_to_br(text: str) -> dict:
    counts = Counter()
    examples = defaultdict(list)
    for idx, ch in enumerate(text):
        if ch.isdigit():
            continue
        if ch in AR2BR:
            continue
        counts[ch] += 1
        if len(examples[ch]) < 3:
            start = max(0, idx - 10)
            end = min(len(text), idx + 11)
            examples[ch].append(text[start:end].replace("\n", "⏎"))
    return {"counts": counts, "examples": examples}

def render_report_ui(report: dict, title: str):
    counts: Counter = report["counts"]
    examples: dict = report["examples"]
    st.subheader(title)
    if not counts:
        st.success("✅ لا توجد رموز غير مدعومة.")
        return
    st.warning(f"⚠️ تم العثور على {len(counts)} رمز/حرف غير مدعوم (سيبقى كما هو ولن يتحول إلى ؟).")
    rows = []
    for ch, cnt in counts.most_common(50):
        name = unicodedata.name(ch, "UNKNOWN")
        rows.append((ch, cnt, name))
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.markdown("**أمثلة سياقية:**")
    for ch, cnt in counts.most_common(12):
        st.write(f"- **{ch}** (×{cnt})")
        for ex in examples[ch]:
            st.code(ex, language="text")

# =========================
# 5) File reading helpers (TXT/PDF/IMG)
# =========================
def pdf_text_with_pypdf(pdf_bytes: bytes) -> str:
    if PdfReader is None:
        return ""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for p in reader.pages:
        pages.append(p.extract_text() or "")
    return normalize_newlines("\n".join(pages)).strip()

def ocr_image_bytes(image_bytes: bytes, lang: str = "ara") -> str:
    if pytesseract is None or Image is None:
        raise RuntimeError("OCR غير متاح. تأكد من pytesseract و Pillow ووجود tesseract في packages.txt.")
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return normalize_newlines(pytesseract.image_to_string(img, lang=lang)).strip()

def pdf_ocr_with_pymupdf(pdf_bytes: bytes, lang: str = "ara", max_pages: int = 10) -> str:
    if fitz is None:
        raise RuntimeError("PDF ممسوح: PyMuPDF غير مثبت.")
    if pytesseract is None or Image is None:
        raise RuntimeError("OCR غير متاح (pytesseract/Pillow).")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texts = []
    n = min(len(doc), max_pages)
    for i in range(n):
        page = doc[i]
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        t = ocr_image_bytes(img_bytes, lang=lang)
        if t:
            texts.append(t)
    return "\n\n".join(texts).strip()

def read_uploaded_to_text(uploaded, ocr_lang: str, ocr_pages: int) -> tuple[str, str]:
    """returns (text, note)"""
    if uploaded is None:
        return "", "لا يوجد ملف."
    name = (uploaded.name or "").lower()
    data = uploaded.getvalue()

    if name.endswith(".txt"):
        return normalize_newlines(data.decode("utf-8", errors="replace")), "TXT"

    if name.endswith((".png", ".jpg", ".jpeg")):
        t = ocr_image_bytes(data, lang=ocr_lang)
        return t, f"OCR صورة ({ocr_lang})"

    if name.endswith(".pdf"):
        t = ""
        try:
            t = pdf_text_with_pypdf(data)
        except Exception:
            t = ""
        if t:
            return t, "PDF نصي"
        ocr_t = pdf_ocr_with_pymupdf(data, lang=ocr_lang, max_pages=ocr_pages)
        return ocr_t, f"PDF ممسوح → OCR ({ocr_lang}) صفحات:{ocr_pages}"

    return "", "نوع ملف غير مدعوم."

# =========================
# 6) Export helpers
# =========================
def export_to_word_bytes(text: str) -> bytes:
    if Document is None:
        raise RuntimeError("تصدير Word غير متاح.")
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
        raise RuntimeError("تصدير PDF غير متاح.")
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
# 7) Streamlit UI
# =========================
st.set_page_config(page_title=APP_NAME, layout="wide")

if "in_text" not in st.session_state:
    st.session_state.in_text = ""
if "out_text" not in st.session_state:
    st.session_state.out_text = ""
if "last_file_name" not in st.session_state:
    st.session_state.last_file_name = ""
if "last_file_bytes" not in st.session_state:
    st.session_state.last_file_bytes = b""

st.title(APP_NAME)
st.caption(f"الجهة: {APP_COMPANY} — الإصدار {APP_VERSION}")

with st.sidebar:
    st.header("الإعدادات")
    direction = st.radio("الاتجاه", ["عربي → بريل", "بريل → عربي"], index=0, key="dir_radio")
    keep_tashkeel = st.checkbox("عدم حذف التشكيل", value=False, key="keep_tashkeel")
    arabic_digits_out = st.checkbox("أرقام عربية عند (بريل → عربي)", value=True, key="arabic_digits_out")

    st.divider()
    st.subheader("رفع ملف")
    uploaded = st.file_uploader("ارفع TXT أو PDF أو صورة", type=["txt", "pdf", "png", "jpg", "jpeg"], key="uploader_main")

    st.subheader("OCR")
    ocr_lang = st.selectbox("لغة OCR", ["ara", "eng"], index=0, key="ocr_lang")
    pdf_ocr_pages = st.slider("صفحات OCR لـ PDF الممسوح", 1, 30, 10, key="pdf_ocr_pages")

    st.divider()
    auto_convert = st.checkbox("تحويل تلقائي بعد الإدراج", value=True, key="auto_convert")
    show_report = st.checkbox("إظهار تقرير الرموز غير المدعومة", value=True, key="show_report")

    st.divider()
    st.subheader("التصدير")
    want_word = st.checkbox("زر Word", value=True, key="want_word")
    want_pdf = st.checkbox("زر PDF", value=True, key="want_pdf")

def do_convert(src: str) -> str:
    if direction == "عربي → بريل":
        return arabic_to_braille(src, keep_tashkeel=keep_tashkeel)
    return braille_to_arabic(src, arabic_digits=arabic_digits_out)

# ---- تخزين الملف في session_state فورًا عند رفعه (لتفادي ضياعه مع rerun)
if uploaded is not None:
    st.session_state.last_file_name = uploaded.name or ""
    st.session_state.last_file_bytes = uploaded.getvalue()

# ---- زر إدراج محتوى الملف داخل مربع النص (الحل النهائي لمشكلتك)
with st.sidebar:
    if st.session_state.last_file_bytes:
        if st.button("📥 إدراج محتوى الملف في مربع النص", use_container_width=True, key="btn_insert_file"):
            # ننشئ UploadedFile وهمي عبر bytes/name (نقرأ مباشرة)
            class _F:
                def __init__(self, name, b):
                    self.name = name
                    self._b = b
                def getvalue(self):
                    return self._b

            f = _F(st.session_state.last_file_name, st.session_state.last_file_bytes)
            try:
                text, note = read_uploaded_to_text(f, ocr_lang=ocr_lang, ocr_pages=pdf_ocr_pages)
                st.session_state.in_text = text or ""
                st.success(f"✅ تم الإدراج: {note}")
                if auto_convert:
                    st.session_state.out_text = do_convert(st.session_state.in_text)
            except Exception as e:
                st.error(str(e))
    else:
        st.info("ارفع ملفًا أولاً ثم اضغط زر الإدراج.")

# ===== Main UI =====
col1, col2 = st.columns(2, gap="large")

with col1:
    st.subheader("النص الأصلي")
    st.session_state.in_text = st.text_area(
        label="النص الأصلي",
        value=st.session_state.in_text,
        height=420,
        key="in_text_area",
        label_visibility="collapsed",
    )

with col2:
    st.subheader("الناتج")
    st.session_state.out_text = st.text_area(
        label="الناتج",
        value=st.session_state.out_text,
        height=420,
        key="out_text_area",
        label_visibility="collapsed",
    )

b1, b2, b3, b4 = st.columns([1, 1, 1, 1], gap="small")

with b1:
    if st.button("تحويل الآن", use_container_width=True, key="btn_convert"):
        st.session_state.out_text = do_convert(st.session_state.in_text)

with b2:
    if st.button("تبديل (Swap)", use_container_width=True, key="btn_swap"):
        st.session_state.in_text, st.session_state.out_text = st.session_state.out_text, st.session_state.in_text

with b3:
    if st.button("مسح الكل", use_container_width=True, key="btn_clear"):
        st.session_state.in_text = ""
        st.session_state.out_text = ""

with b4:
    now = datetime.now().strftime("%Y%m%d-%H%M%S")
    st.download_button(
        "تحميل الناتج TXT",
        data=st.session_state.out_text.encode("utf-8"),
        file_name=f"output-{now}.txt",
        mime="text/plain; charset=utf-8",
        use_container_width=True,
        key="btn_download_txt",
    )

st.divider()

e1, e2 = st.columns(2)

with e1:
    if want_word:
        if Document is None:
            st.warning("Word غير متاح (python-docx غير مثبت).")
        else:
            try:
                word_bytes = export_to_word_bytes(st.session_state.out_text)
                st.download_button(
                    "تصدير Word (.docx)",
                    data=word_bytes,
                    file_name=f"output-{now}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key="btn_word",
                )
            except Exception as e:
                st.error(f"فشل تصدير Word: {e}")

with e2:
    if want_pdf:
        assume_arabic = (direction == "بريل → عربي")
        try:
            pdf_bytes = export_to_pdf_bytes(st.session_state.out_text, assume_arabic=assume_arabic)
            st.download_button(
                "تصدير PDF (.pdf)",
                data=pdf_bytes,
                file_name=f"output-{now}.pdf",
                mime="application/pdf",
                key="btn_pdf",
            )
        except Exception as e:
            st.error(f"فشل تصدير PDF: {e}")

# ===== Report =====
if st.session_state.get("show_report", True):
    st.divider()
    if direction == "عربي → بريل":
        rpt = build_unsupported_report_ar_to_br(
            clean_text_pipeline(st.session_state.in_text, keep_tashkeel=keep_tashkeel)
        )
        render_report_ui(rpt, "تقرير: رموز غير مدعومة (عربي → بريل)")

st.caption("ملاحظة: التحويل تعليمي وقد لا يطابق معيار بريل العربي حرفيًا في جميع حالات الاختصارات والترقيم.")
