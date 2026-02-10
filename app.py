# -*- coding: utf-8 -*-
import re
import io
from typing import Tuple

import streamlit as st

# Optional: PDF text extraction / OCR
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None


# =========================
# Text utilities
# =========================
TASHKEEL_RE = re.compile(r'[\u0617-\u061A\u064B-\u0652\u0670\u0653-\u0655]')

def remove_tashkeel(text: str) -> str:
    return re.sub(TASHKEEL_RE, '', text)

def normalize_newlines(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n')

ARABIC_DIGITS_TO_LATIN = {
    '٠':'0','١':'1','٢':'2','٣':'3','٤':'4',
    '٥':'5','٦':'6','٧':'7','٨':'8','٩':'9',
}
LATIN_TO_ARABIC_DIGITS = {v:k for k,v in ARABIC_DIGITS_TO_LATIN.items()}

def normalize_digits_to_latin(text: str) -> str:
    return ''.join(ARABIC_DIGITS_TO_LATIN.get(ch, ch) for ch in text)

# =========================
# Arabic <-> Braille tables
# =========================
NUM_SIGN = '⠼'

AR2BR_LETTERS = {
    'ا':'⠁','أ':'⠁','إ':'⠁','آ':'⠁',
    'ب':'⠃','ت':'⠞','ث':'⠹','ج':'⠚','ح':'⠱','خ':'⠭',
    'د':'⠙','ذ':'⠮','ر':'⠗','ز':'⠵','س':'⠎','ش':'⠩',
    'ص':'⠯','ض':'⠷','ط':'⠾','ظ':'⠿','ع':'⠫','غ':'⠣',
    'ف':'⠋','ق':'⠟','ك':'⠅','ل':'⠇','م':'⠍','ن':'⠝',
    'ه':'⠓','ة':'⠓','و':'⠺','ي':'⠊','ى':'⠊',
    'ء':'⠄','ؤ':'⠺⠄','ئ':'⠊⠄',
}

AR2BR_PUNCT = {
    ' ':' ',
    '\n':'\n',
    '\t':'\t',
    '،':'⠂', ',':'⠂',
    '.':'⠲', '۔':'⠲',
    '؛':'⠆', ';':'⠆',
    ':':'⠒',
    '؟':'⠦', '?':'⠦',
    '!':'⠖',
    '«':'⠦',
    '»':'⠴',
    '“':'⠦','”':'⠴',
    '"':'⠶',
    '(':'⠶',')':'⠶',
    '-':'⠤','_':'⠤',
    'ـ':'⠤',
    '…':'⠄⠄⠄',
}

AR2BR = {**AR2BR_LETTERS, **AR2BR_PUNCT}

DIGIT_TO_BR = {
    '1':'⠁','2':'⠃','3':'⠉','4':'⠙','5':'⠑',
    '6':'⠋','7':'⠛','8':'⠓','9':'⠊','0':'⠚',
}

ALEF_FORMS = {'ا', 'أ', 'إ', 'آ'}

BR2AR_LETTERS = {v: k for k, v in AR2BR_LETTERS.items()}
EXTRA_BR2AR = {
    '⠂': '،',
    '⠲': '.',
    '⠆': '؛',
    '⠒': ':',
    '⠖': '!',
    '⠤': '-',
    '⠶': '"',
    '⠦': '«',
    '⠴': '»',
}
BR_TO_DIGIT = {v: k for k, v in DIGIT_TO_BR.items()}

def unknown_policy_apply(ch: str, policy: str) -> str:
    if policy == "pass":
        return ch
    if policy == "drop":
        return ""
    return "⍰"

def arabic_to_braille(text: str, keep_tashkeel: bool = False, unknown_policy: str = "qmark") -> str:
    text = normalize_newlines(text)
    if not keep_tashkeel:
        text = remove_tashkeel(text)
    text = normalize_digits_to_latin(text)

    out = []
    i = 0
    in_number = False

    while i < len(text):
        # lam-alef
        if i + 1 < len(text) and text[i] == 'ل' and text[i+1] in ALEF_FORMS:
            in_number = False
            out.append(AR2BR.get('ل', unknown_policy_apply('ل', unknown_policy)))
            out.append(AR2BR.get(text[i+1], unknown_policy_apply(text[i+1], unknown_policy)))
            i += 2
            continue

        ch = text[i]

        if ch.isdigit():
            if not in_number:
                out.append(NUM_SIGN)
                in_number = True
            out.append(DIGIT_TO_BR.get(ch, unknown_policy_apply(ch, unknown_policy)))
            i += 1
            continue

        in_number = False

        if ch in AR2BR:
            out.append(AR2BR[ch])
        else:
            out.append(unknown_policy_apply(ch, unknown_policy))
        i += 1

    return ''.join(out)

def braille_to_arabic(braille_text: str, arabic_digits: bool = False, unknown_policy: str = "qmark") -> str:
    braille_text = normalize_newlines(braille_text)

    def unknown_out(cell: str) -> str:
        if unknown_policy == "pass":
            return cell
        if unknown_policy == "drop":
            return ""
        return "⍰"

    out = []
    i = 0
    in_number = False

    while i < len(braille_text):
        ch = braille_text[i]

        if ch == NUM_SIGN:
            in_number = True
            i += 1
            continue

        if ch in [' ', '\n', '\t']:
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
            continue

        out.append(BR2AR_LETTERS.get(ch, EXTRA_BR2AR.get(ch, unknown_out(ch))))
        i += 1

    return ''.join(out)


# =========================
# PDF helpers
# =========================
def _parse_page_range(user_text: str, page_count: int) -> Tuple[int, int]:
    t = (user_text or "").strip().lower()
    if t in ("", "all", "*"):
        return (0, page_count)
    if "-" in t:
        a, b = t.split("-", 1)
        s = max(1, int(a.strip()))
        e = min(page_count, int(b.strip()))
        if e < s:
            e = s
        return (s - 1, e)
    p = max(1, int(t))
    p = min(page_count, p)
    return (p - 1, p)

def pdf_extract_text_range(pdf_bytes: bytes, start0: int, end0: int) -> str:
    if fitz is None:
        raise RuntimeError("PyMuPDF غير مثبت.")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    parts = []
    for pno in range(start0, end0):
        page = doc.load_page(pno)
        t = page.get_text("text") or ""
        if t.strip():
            parts.append(t)
    doc.close()
    return normalize_newlines("\n".join(parts)).strip()

def _preprocess_for_ocr(img: "Image.Image") -> "Image.Image":
    img = ImageOps.grayscale(img)
    img = ImageOps.autocontrast(img)
    img = img.point(lambda p: 255 if p > 160 else 0)
    img = img.resize((img.width * 2, img.height * 2))
    return img

def pdf_ocr_to_text_range(pdf_bytes: bytes, start0: int, end0: int, lang: str, dpi: int, psm: int) -> str:
    if fitz is None:
        raise RuntimeError("PyMuPDF غير مثبت.")
    if pytesseract is None:
        raise RuntimeError("pytesseract غير مثبت.")
    if Image is None:
        raise RuntimeError("Pillow غير مثبت.")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    parts = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    config = f"--oem 3 --psm {psm}"

    for pno in range(start0, end0):
        page = doc.load_page(pno)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        img = _preprocess_for_ocr(img)
        text = pytesseract.image_to_string(img, lang=lang, config=config)
        if text.strip():
            parts.append(text)

    doc.close()
    return normalize_newlines("\n".join(parts)).strip()


# =========================
# UI (Streamlit)
# =========================
st.set_page_config(page_title="نرى معًا ونقرأ", page_icon="🔤", layout="wide")

st.title("🔤 نرى معًا ونقرأ")
st.caption("محوّل عربي ↔ بريل + قراءة PDF (نصّي/OCR) — نسخة ويب")

colL, colR = st.columns([1, 1], gap="large")

with st.sidebar:
    st.subheader("الإعدادات")

    direction = st.radio("الاتجاه", ["عربي → بريل", "بريل → عربي"], index=0)

    keep_tashkeel = st.checkbox("عدم حذف التشكيل (عربي → بريل)", value=False)
    arabic_digits_out = st.checkbox("أرقام عربية ٠١٢٣… (بريل → عربي)", value=True)

    st.markdown("---")
    st.write("المجهول:")
    unknown_ar2br = st.radio("عربي → بريل", ["⍰", "تمرير", "حذف"], index=0, horizontal=True)
    unknown_br2ar = st.radio("بريل → عربي", ["⍰", "تمرير", "حذف"], index=0, horizontal=True)

    st.markdown("---")
    st.subheader("PDF / OCR")
    st.write("📌 ملاحظة: OCR يعمل فقط إذا كان Tesseract مثبتًا على الجهاز الخادم.")
    ocr_mode = st.radio("طريقة القراءة", ["تلقائي", "نص مباشر", "OCR"], index=0)
    page_range_txt = st.text_input("الصفحات (all أو 1-3 أو 2)", value="all")
    ocr_lang = st.text_input("لغة OCR", value="ara+eng")
    ocr_dpi = st.slider("DPI", 150, 600, 300, 10)
    ocr_psm = st.slider("PSM", 3, 13, 6, 1)

def map_unknown(ui_value: str) -> str:
    return "qmark" if ui_value == "⍰" else ("pass" if ui_value == "تمرير" else "drop")

unknown_policy_ar2br = map_unknown(unknown_ar2br)
unknown_policy_br2ar = map_unknown(unknown_br2ar)

# ---- File uploads ----
with st.sidebar:
    st.subheader("رفع ملفات")
    txt_file = st.file_uploader("TXT", type=["txt"])
    pdf_file = st.file_uploader("PDF", type=["pdf"])

def load_txt_bytes(file) -> str:
    data = file.read()
    # try utf-8 then fallback
    try:
        return normalize_newlines(data.decode("utf-8"))
    except Exception:
        return normalize_newlines(data.decode("utf-8", errors="replace"))

def load_pdf_bytes_to_text(file) -> Tuple[str, str]:
    if fitz is None:
        return "", "PyMuPDF غير مثبت على الخادم."
    pdf_bytes = file.read()
    # page count
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_count = doc.page_count
    doc.close()

    try:
        s0, e0 = _parse_page_range(page_range_txt, page_count)
    except Exception:
        return "", "صيغة الصفحات غير صحيحة."

    if ocr_mode == "نص مباشر":
        try:
            t = pdf_extract_text_range(pdf_bytes, s0, e0)
            return t, "PDF نصّي (استخراج مباشر)"
        except Exception as e:
            return "", f"فشل استخراج النص: {e}"

    if ocr_mode == "OCR":
        try:
            t = pdf_ocr_to_text_range(pdf_bytes, s0, e0, ocr_lang, int(ocr_dpi), int(ocr_psm))
            return t, f"OCR (lang={ocr_lang}, dpi={ocr_dpi}, psm={ocr_psm})"
        except Exception as e:
            return "", f"فشل OCR: {e}"

    # auto
    try:
        direct = pdf_extract_text_range(pdf_bytes, s0, e0)
    except Exception:
        direct = ""

    if len(direct) >= 60:
        return direct, "PDF نصّي (تلقائي: استخراج مباشر)"

    try:
        t = pdf_ocr_to_text_range(pdf_bytes, s0, e0, ocr_lang, int(ocr_dpi), int(ocr_psm))
        return t, "PDF صورة/سكان (تلقائي: OCR)"
    except Exception as e:
        return "", f"تلقائي: فشل OCR ({e})"

# ---- Session state ----
if "in_text" not in st.session_state:
    st.session_state.in_text = ""
if "out_text" not in st.session_state:
    st.session_state.out_text = ""

# Load files if uploaded
if txt_file is not None:
    st.session_state.in_text = load_txt_bytes(txt_file)

if pdf_file is not None:
    extracted, note = load_pdf_bytes_to_text(pdf_file)
    if extracted:
        st.session_state.in_text = extracted
        st.sidebar.success(f"تم فتح PDF — {note}")
    else:
        st.sidebar.warning(f"PDF: {note}")

with colL:
    st.subheader("النص الأصلي")
    st.session_state.in_text = st.text_area("", st.session_state.in_text, height=420)

with colR:
    st.subheader("الناتج")
    st.session_state.out_text = st.text_area("", st.session_state.out_text, height=420)

# Actions row
c1, c2, c3, c4, c5 = st.columns([1,1,1,1,1])
with c1:
    if st.button("تحويل ✅", use_container_width=True):
        src = st.session_state.in_text
        if direction == "عربي → بريل":
            st.session_state.out_text = arabic_to_braille(
                src,
                keep_tashkeel=keep_tashkeel,
                unknown_policy=unknown_policy_ar2br
            )
        else:
            st.session_state.out_text = braille_to_arabic(
                src,
                arabic_digits=arabic_digits_out,
                unknown_policy=unknown_policy_br2ar
            )
with c2:
    if st.button("تبديل ↔️", use_container_width=True):
        st.session_state.in_text, st.session_state.out_text = st.session_state.out_text, st.session_state.in_text
with c3:
    if st.button("مسح الكل 🧹", use_container_width=True):
        st.session_state.in_text = ""
        st.session_state.out_text = ""
with c4:
    st.download_button(
        "تحميل الناتج TXT ⬇️",
        data=st.session_state.out_text.encode("utf-8"),
        file_name="output.txt",
        mime="text/plain",
        use_container_width=True
    )
with c5:
    st.download_button(
        "تحميل الناتج BRAILLE/AR ⬇️",
        data=st.session_state.out_text.encode("utf-8"),
        file_name="output_utf8.txt",
        mime="text/plain",
        use_container_width=True
    )

st.markdown("---")
st.caption(f"الجهة: {APP_COMPANY} — الإصدار {APP_VERSION}")
# update
