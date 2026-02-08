# -*- coding: utf-8 -*-
import os
import re
import sys
import threading
import difflib
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk

APP_TITLE_AR = "نرى معًا ونقرأ"
APP_SUBTITLE = "محوّل عربي ↔ بريل + PDF (نصّي/OCR)"
APP_VERSION = "1.0.2"
APP_COMPANY = "Akademiat Al-Mawhiba / أكاديمية الموهبة المشتركة"

# --- Optional exports ---
try:
    from docx import Document
except Exception:
    Document = None

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
except Exception:
    canvas = None
    A4 = None
    pdfmetrics = None
    TTFont = None

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except Exception:
    arabic_reshaper = None
    get_display = None

# --- PDF reading / OCR ---
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
# 0) Resources helper (PyInstaller-safe paths)
# =========================
def resource_path(relative_path: str) -> str:
    """Returns an absolute path to resource, works for dev and for PyInstaller onefile."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)

def safe_photoimage(path: str, max_w: int = 120, max_h: int = 120):
    """
    Load PhotoImage safely and auto-scale down if it's too large.
    Uses Tkinter subsample (works without PIL).
    """
    try:
        if not path or not os.path.exists(path):
            return None

        img = tk.PhotoImage(file=path)

        w, h = img.width(), img.height()
        if w > max_w or h > max_h:
            fx = max(1, w // max_w)
            fy = max(1, h // max_h)
            f = max(fx, fy)
            img = img.subsample(f, f)

        return img
    except Exception:
        return None


# =========================
# 1) تنظيف النص
# =========================
TASHKEEL_RE = re.compile(r'[\u0617-\u061A\u064B-\u0652\u0670\u0653-\u0655]')

def remove_tashkeel(text: str) -> str:
    return re.sub(TASHKEEL_RE, '', text)

def normalize_newlines(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n')


# =========================
# 2) جداول التحويل (عربي -> بريل)
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

ARABIC_DIGITS_TO_LATIN = {
    '٠':'0','١':'1','٢':'2','٣':'3','٤':'4',
    '٥':'5','٦':'6','٧':'7','٨':'8','٩':'9',
}
LATIN_TO_ARABIC_DIGITS = {v:k for k,v in ARABIC_DIGITS_TO_LATIN.items()}

ALEF_FORMS = {'ا', 'أ', 'إ', 'آ'}


# =========================
# 3) عكس التحويل (بريل -> عربي) بدون تضارب
# =========================
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


# =========================
# 4) محرك التحويل
# =========================
def normalize_digits_to_latin(text: str) -> str:
    return ''.join(ARABIC_DIGITS_TO_LATIN.get(ch, ch) for ch in text)

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
# 5) TXT helpers
# =========================
def convert_file(path_in: str, path_out: str, direction: str, keep_tashkeel: bool,
                 arabic_digits: bool, unknown_policy_ar2br: str, unknown_policy_br2ar: str):
    with open(path_in, 'r', encoding='utf-8') as f:
        content = normalize_newlines(f.read())

    if direction == 'AR2BR':
        converted = arabic_to_braille(content, keep_tashkeel=keep_tashkeel, unknown_policy=unknown_policy_ar2br)
    else:
        converted = braille_to_arabic(content, arabic_digits=arabic_digits, unknown_policy=unknown_policy_br2ar)

    with open(path_out, 'w', encoding='utf-8') as f:
        f.write(converted)


# =========================
# 6) Export helpers (Word / PDF)
# =========================
def export_to_word(text: str, path_out: str):
    if Document is None:
        raise RuntimeError("python-docx غير مثبت. ثبّته بالأمر: pip install python-docx")
    doc = Document()
    for line in normalize_newlines(text).split('\n'):
        doc.add_paragraph(line)
    doc.save(path_out)

def _shape_arabic_for_pdf_if_possible(text: str) -> str:
    if arabic_reshaper and get_display:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    return text

def _try_register_pdf_font() -> tuple[str, str]:
    if pdfmetrics is None or TTFont is None:
        return ("Helvetica", "reportlab غير متاح لتسجيل خطوط TTF.")

    candidates = []
    win_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    candidates += [
        os.path.join(win_fonts, "DejaVuSans.ttf"),
        os.path.join(win_fonts, "DejaVuSansCondensed.ttf"),
        os.path.join(win_fonts, "NotoSansSymbols2-Regular.ttf"),
        os.path.join(win_fonts, "NotoSansArabic-Regular.ttf"),
        os.path.join(win_fonts, "SegoeUI.ttf"),
        os.path.join(win_fonts, "seguisym.ttf"),
        os.path.join(win_fonts, "arial.ttf"),
    ]
    local_fonts = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")
    if local_fonts:
        candidates += [
            os.path.join(local_fonts, "NotoSansSymbols2-Regular.ttf"),
            os.path.join(local_fonts, "NotoSansArabic-Regular.ttf"),
            os.path.join(local_fonts, "DejaVuSans.ttf"),
        ]

    for path in candidates:
        try:
            if path and os.path.exists(path):
                name = "UIFont"
                pdfmetrics.registerFont(TTFont(name, path))
                return (name, f"تم استخدام الخط: {os.path.basename(path)}")
        except Exception:
            continue

    return ("Helvetica", "لم يتم العثور على خط TTF مناسب. قد لا تظهر العربية/البرايل بشكل مثالي في PDF.")

def export_to_pdf(text: str, path_out: str, assume_arabic: bool = True) -> str:
    if canvas is None or A4 is None:
        raise RuntimeError("reportlab غير مثبت. ثبّته بالأمر: pip install reportlab")

    font_name, note = _try_register_pdf_font()

    c = canvas.Canvas(path_out, pagesize=A4)
    width, height = A4
    margin = 50
    y = height - margin

    c.setFont(font_name, 14)

    lines = normalize_newlines(text).split('\n')
    for line in lines:
        if y < margin:
            c.showPage()
            c.setFont(font_name, 14)
            y = height - margin

        draw_line = _shape_arabic_for_pdf_if_possible(line) if assume_arabic else line
        c.drawString(margin, y, draw_line)
        y -= 18

    c.save()
    return note


# =========================
# 7) PDF reading + OCR (improved)
# =========================
def ensure_tesseract_configured():
    """Try to auto-detect tesseract.exe on Windows if not in PATH."""
    if pytesseract is None:
        return
    if os.name == "nt":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        try:
            current = getattr(pytesseract.pytesseract, "tesseract_cmd", "")
        except Exception:
            current = ""
        if current and os.path.exists(current):
            return
        for p in candidates:
            if os.path.exists(p):
                pytesseract.pytesseract.tesseract_cmd = p
                return

def tesseract_ready() -> tuple[bool, str]:
    if pytesseract is None:
        return False, "pytesseract غير مثبت داخل البيئة."
    ensure_tesseract_configured()
    cmd = getattr(getattr(pytesseract, "pytesseract", None), "tesseract_cmd", "")
    if os.name == "nt":
        if cmd and os.path.exists(cmd):
            return True, cmd
        return True, "PATH"
    return True, "OK"

def _parse_page_range(user_text: str, page_count: int) -> tuple[int, int]:
    t = (user_text or "").strip().lower()
    if t in ("", "all", "*"):
        return (0, page_count)
    if "-" in t:
        a, b = t.split("-", 1)
        s = int(a.strip())
        e = int(b.strip())
        if s < 1: s = 1
        if e > page_count: e = page_count
        if e < s: e = s
        return (s - 1, e)
    p = int(t)
    if p < 1: p = 1
    if p > page_count: p = page_count
    return (p - 1, p)

def pdf_extract_text_range(path_pdf: str, start0: int, end0: int, progress_cb=None) -> str:
    if fitz is None:
        raise RuntimeError("PyMuPDF غير مثبت. ثبّت: pip install pymupdf")
    doc = fitz.open(path_pdf)
    parts = []
    total = max(1, end0 - start0)

    for i, pno in enumerate(range(start0, end0), start=1):
        page = doc.load_page(pno)
        t = page.get_text("text") or ""
        if t.strip():
            parts.append(t)
        if progress_cb:
            progress_cb(i, total, f"استخراج نص: صفحة {pno+1}/{doc.page_count}")

    doc.close()
    return normalize_newlines("\n".join(parts)).strip()

def _preprocess_for_ocr(img: "Image.Image") -> "Image.Image":
    img = ImageOps.grayscale(img)
    img = ImageOps.autocontrast(img)
    img = img.point(lambda p: 255 if p > 160 else 0)
    img = img.resize((img.width * 2, img.height * 2))
    return img

def pdf_ocr_to_text_range(
    path_pdf: str,
    start0: int,
    end0: int,
    lang: str = "ara+eng",
    dpi: int = 300,
    progress_cb=None,
    psm: int = 6
) -> str:
    if fitz is None:
        raise RuntimeError("PyMuPDF غير مثبت. ثبّت: pip install pymupdf")
    if pytesseract is None:
        raise RuntimeError("pytesseract غير مثبت. ثبّت: pip install pytesseract")
    if Image is None:
        raise RuntimeError("Pillow غير مثبت. ثبّت: pip install pillow")

    ok, how = tesseract_ready()
    if not ok:
        raise RuntimeError("OCR غير جاهز: " + how)

    doc = fitz.open(path_pdf)
    parts = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    total = max(1, end0 - start0)

    config = f"--oem 3 --psm {psm}"

    for i, pno in enumerate(range(start0, end0), start=1):
        page = doc.load_page(pno)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")

        import io
        img = Image.open(io.BytesIO(img_bytes))
        img = _preprocess_for_ocr(img)

        text = pytesseract.image_to_string(img, lang=lang, config=config)
        if text.strip():
            parts.append(text)

        if progress_cb:
            progress_cb(i, total, f"OCR: صفحة {pno+1}/{doc.page_count} (DPI {dpi})")

    doc.close()
    return normalize_newlines("\n".join(parts)).strip()

def pdf_to_text_auto_range(path_pdf: str, start0: int, end0: int, progress_cb=None) -> tuple[str, str]:
    direct = ""
    try:
        direct = pdf_extract_text_range(path_pdf, start0, end0, progress_cb=progress_cb)
    except Exception:
        direct = ""

    if len(direct) >= 60:
        return direct, "PDF نصّي (استخراج مباشر)"

    ocr = pdf_ocr_to_text_range(path_pdf, start0, end0, lang="ara+eng", dpi=300, progress_cb=progress_cb, psm=6)
    return ocr, "PDF صورة/سكان (OCR محسّن)"


# =========================
# 8) GUI (No Splash) + safe logo
# =========================
def run_gui():
    root = tk.Tk()
    root.title(f"{APP_TITLE_AR} — {APP_SUBTITLE}")
    root.geometry("1180x780")
    root.minsize(900, 600)

    direction = tk.StringVar(value="AR2BR")
    keep_tashkeel = tk.BooleanVar(value=False)
    arabic_digits_out = tk.BooleanVar(value=True)

    unknown_policy_ar2br = tk.StringVar(value="qmark")
    unknown_policy_br2ar = tk.StringVar(value="qmark")

    # OCR options
    ocr_lang = tk.StringVar(value="ara+eng")
    ocr_dpi = tk.IntVar(value=300)
    ocr_psm = tk.IntVar(value=6)

    # ========= Header (logo + title) =========
    header = tk.Frame(root)
    header.pack(fill="x", padx=10, pady=(10, 0))

    logo_small = safe_photoimage(resource_path(os.path.join("assets", "logo.png")), max_w=120, max_h=120)
    if logo_small is not None:
        tk.Label(header, image=logo_small).pack(side="left", padx=(0, 10))
        root._logo_small_keep = logo_small  # keep reference

    title_box = tk.Frame(header)
    title_box.pack(side="left", fill="x", expand=True)
    tk.Label(title_box, text=APP_TITLE_AR, font=("Arial", 18, "bold")).pack(anchor="w")
    tk.Label(title_box, text=f"{APP_SUBTITLE} — الإصدار {APP_VERSION}", font=("Arial", 10)).pack(anchor="w")

    # ========= Top controls =========
    top = tk.Frame(root)
    top.pack(fill="x", padx=10, pady=8)

    tk.Label(top, text="الاتجاه:").pack(side="left")
    tk.Radiobutton(top, text="عربي → بريل", variable=direction, value="AR2BR").pack(side="left", padx=8)
    tk.Radiobutton(top, text="بريل → عربي", variable=direction, value="BR2AR").pack(side="left", padx=8)

    tk.Checkbutton(top, text="عدم حذف التشكيل", variable=keep_tashkeel).pack(side="left", padx=14)
    tk.Checkbutton(top, text="(بريل → عربي) أرقام عربية ٠١٢٣…", variable=arabic_digits_out).pack(side="left", padx=14)

    pol = tk.Frame(root)
    pol.pack(fill="x", padx=10, pady=(0, 6))

    tk.Label(pol, text="مجهول (عربي → بريل):").pack(side="left")
    tk.Radiobutton(pol, text="⍰", variable=unknown_policy_ar2br, value="qmark").pack(side="left", padx=6)
    tk.Radiobutton(pol, text="تمرير", variable=unknown_policy_ar2br, value="pass").pack(side="left", padx=6)
    tk.Radiobutton(pol, text="حذف", variable=unknown_policy_ar2br, value="drop").pack(side="left", padx=6)

    tk.Label(pol, text="   |   مجهول (بريل → عربي):").pack(side="left", padx=10)
    tk.Radiobutton(pol, text="⍰", variable=unknown_policy_br2ar, value="qmark").pack(side="left", padx=6)
    tk.Radiobutton(pol, text="تمرير", variable=unknown_policy_br2ar, value="pass").pack(side="left", padx=6)
    tk.Radiobutton(pol, text="حذف", variable=unknown_policy_br2ar, value="drop").pack(side="left", padx=6)

    # ========= OCR settings (compact) =========
    ocrbar = tk.Frame(root)
    ocrbar.pack(fill="x", padx=10, pady=(0, 8))
    tk.Label(ocrbar, text="OCR:").pack(side="left")
    tk.Label(ocrbar, text="لغة").pack(side="left", padx=(10, 4))
    ttk.Entry(ocrbar, textvariable=ocr_lang, width=10).pack(side="left")
    tk.Label(ocrbar, text="DPI").pack(side="left", padx=(10, 4))
    ttk.Spinbox(ocrbar, from_=150, to=600, increment=10, textvariable=ocr_dpi, width=6).pack(side="left")
    tk.Label(ocrbar, text="PSM").pack(side="left", padx=(10, 4))
    ttk.Spinbox(ocrbar, from_=3, to=13, increment=1, textvariable=ocr_psm, width=4).pack(side="left")
    tk.Label(ocrbar, text="(6 مناسب للنصوص)").pack(side="left", padx=10)

    # ========= Text boxes + scrollbars =========
    main = tk.Frame(root)
    main.pack(fill="both", expand=True, padx=10, pady=10)

    left = tk.Frame(main)
    right = tk.Frame(main)
    left.pack(side="left", fill="both", expand=True, padx=(0, 6))
    right.pack(side="left", fill="both", expand=True, padx=(6, 0))

    tk.Label(left, text="النص الأصلي").pack(anchor="w")
    in_wrap = tk.Frame(left)
    in_wrap.pack(fill="both", expand=True)
    in_text = tk.Text(in_wrap, wrap="word", undo=True)
    in_scroll = ttk.Scrollbar(in_wrap, orient="vertical", command=in_text.yview)
    in_text.configure(yscrollcommand=in_scroll.set)
    in_text.pack(side="left", fill="both", expand=True)
    in_scroll.pack(side="right", fill="y")

    tk.Label(right, text="الناتج").pack(anchor="w")
    out_wrap = tk.Frame(right)
    out_wrap.pack(fill="both", expand=True)
    out_text = tk.Text(out_wrap, wrap="word", undo=True)
    out_scroll = ttk.Scrollbar(out_wrap, orient="vertical", command=out_text.yview)
    out_text.configure(yscrollcommand=out_scroll.set)
    out_text.pack(side="left", fill="both", expand=True)
    out_scroll.pack(side="right", fill="y")

    # ========= Status =========
    status = tk.StringVar(value="الأصلي: 0 حرف | الناتج: 0 حرف")
    status_bar = tk.Label(root, textvariable=status, anchor="w")
    status_bar.pack(fill="x", padx=10, pady=(0, 6))

    def update_counts(note: str = ""):
        src = in_text.get("1.0", "end-1c")
        dst = out_text.get("1.0", "end-1c")
        base = f"الأصلي: {len(src)} حرف | الناتج: {len(dst)} حرف"
        status.set(base + (f"   —   {note}" if note else ""))

    def do_convert():
        src = in_text.get("1.0", "end-1c")
        if direction.get() == "AR2BR":
            res = arabic_to_braille(src, keep_tashkeel=keep_tashkeel.get(), unknown_policy=unknown_policy_ar2br.get())
        else:
            res = braille_to_arabic(src, arabic_digits=arabic_digits_out.get(), unknown_policy=unknown_policy_br2ar.get())
        out_text.delete("1.0", "end")
        out_text.insert("1.0", res)
        update_counts("تم التحويل")

    def swap():
        a = in_text.get("1.0", "end-1c")
        b = out_text.get("1.0", "end-1c")
        in_text.delete("1.0", "end")
        out_text.delete("1.0", "end")
        in_text.insert("1.0", b)
        out_text.insert("1.0", a)
        update_counts("تم التبديل")

    def clear_all():
        in_text.delete("1.0", "end")
        out_text.delete("1.0", "end")
        update_counts("تم المسح")

    def copy_output():
        data = out_text.get("1.0", "end-1c")
        root.clipboard_clear()
        root.clipboard_append(data)
        update_counts("تم نسخ الناتج")

    def compare_texts():
        a = in_text.get("1.0", "end-1c")
        b = out_text.get("1.0", "end-1c")

        if not a.strip() or not b.strip():
            messagebox.showwarning("تنبيه", "ضع نصًا في الصندوقين (أو حوّل أولًا) ثم اضغط مقارنة.")
            return

        ratio = difflib.SequenceMatcher(None, a, b).ratio()
        percent = round(ratio * 100, 2)

        a_lines = a.splitlines()
        b_lines = b.splitlines()
        diff_lines = list(difflib.unified_diff(a_lines, b_lines, fromfile="الأصلي", tofile="الناتج", lineterm=""))

        win = tk.Toplevel(root)
        win.title(f"مقارنة النص — تطابق {percent}%")
        win.geometry("980x600")

        tk.Label(win, text=f"نسبة التطابق التقريبية: {percent}%", font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=8)

        box = tk.Text(win, wrap="none")
        box.pack(fill="both", expand=True, padx=10, pady=10)

        if diff_lines:
            box.insert("1.0", "\n".join(diff_lines))
        else:
            box.insert("1.0", "لا توجد اختلافات (أو النصان متطابقان تقريبًا).")
        box.config(state="disabled")

    def about_app():
        ok, how = tesseract_ready()
        ocr_state = "جاهز" if ok else f"غير جاهز ({how})"
        messagebox.showinfo(
            "حول التطبيق",
            f"{APP_TITLE_AR}\n"
            f"{APP_SUBTITLE}\n\n"
            f"الإصدار: {APP_VERSION}\n"
            f"الجهة: {APP_COMPANY}\n"
            f"OCR: {ocr_state}\n"
        )

    def load_txt():
        path = filedialog.askopenfilename(
            title="اختر ملف TXT",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not path:
            return
        with open(path, 'r', encoding='utf-8') as f:
            in_text.delete("1.0", "end")
            in_text.insert("1.0", normalize_newlines(f.read()))
        update_counts(f"تم فتح: {os.path.basename(path)}")

    def save_output_txt():
        path = filedialog.asksaveasfilename(
            title="حفظ الناتج كملف TXT",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not path:
            return
        data = out_text.get("1.0", "end-1c")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(data)
        update_counts(f"تم حفظ: {os.path.basename(path)}")

    def convert_file_gui():
        pin = filedialog.askopenfilename(
            title="اختر ملف TXT للتحويل",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not pin:
            return
        pout = filedialog.asksaveasfilename(
            title="اختر مكان حفظ الناتج",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not pout:
            return
        convert_file(
            pin, pout,
            direction.get(),
            keep_tashkeel.get(),
            arabic_digits_out.get(),
            unknown_policy_ar2br.get(),
            unknown_policy_br2ar.get()
        )
        update_counts(f"تم تحويل ملف كامل: {os.path.basename(pin)}")

    def export_word_gui():
        data = out_text.get("1.0", "end-1c")
        if not data.strip():
            messagebox.showwarning("تنبيه", "لا يوجد ناتج للتصدير. اضغط تحويل أولًا.")
            return
        path = filedialog.asksaveasfilename(
            title="تصدير إلى Word",
            defaultextension=".docx",
            filetypes=[("Word Document", "*.docx")]
        )
        if not path:
            return
        try:
            export_to_word(data, path)
            update_counts(f"تم تصدير Word: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("خطأ", str(e))

    def export_pdf_gui():
        data = out_text.get("1.0", "end-1c")
        if not data.strip():
            messagebox.showwarning("تنبيه", "لا يوجد ناتج للتصدير. اضغط تحويل أولًا.")
            return
        path = filedialog.asksaveasfilename(
            title="تصدير إلى PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")]
        )
        if not path:
            return

        assume_arabic = (direction.get() == "BR2AR")
        try:
            note = export_to_pdf(data, path, assume_arabic=assume_arabic)
            extra = []
            if assume_arabic and (arabic_reshaper is None or get_display is None):
                extra.append("لتشكيل العربية داخل PDF ثبّت: arabic-reshaper و python-bidi")
            if note:
                extra.append(note)
            update_counts(" | ".join(extra) if extra else f"تم تصدير PDF: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("خطأ", str(e))

    # ---------- PDF loader ----------
    def load_pdf():
        path = filedialog.askopenfilename(
            title="اختر ملف PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if not path:
            return

        if fitz is None:
            messagebox.showerror("نقص مكتبات", "PyMuPDF غير مثبت. نفّذ: pip install pymupdf")
            return

        try:
            doc = fitz.open(path)
            page_count = doc.page_count
            doc.close()
        except Exception as e:
            messagebox.showerror("خطأ PDF", str(e))
            return

        dlg = tk.Toplevel(root)
        dlg.title("فتح PDF (نصّي / OCR)")
        dlg.geometry("640x460")
        dlg.minsize(640, 460)
        dlg.resizable(True, True)
        dlg.transient(root)
        dlg.grab_set()

        mode = tk.StringVar(value="auto")
        page_mode = tk.StringVar(value="all")
        page_range = tk.StringVar(value="1-1")

        tk.Label(dlg, text=f"الملف: {os.path.basename(path)}  |  عدد الصفحات: {page_count}",
                 anchor="w").pack(fill="x", padx=12, pady=(10, 6))

        frm1 = tk.LabelFrame(dlg, text="طريقة القراءة")
        frm1.pack(fill="x", padx=12, pady=6)
        tk.Radiobutton(frm1, text="تلقائي (نصّي ثم OCR إذا لزم)", variable=mode, value="auto").pack(anchor="w", padx=12, pady=2)
        tk.Radiobutton(frm1, text="استخراج نص مباشر (PDF نصّي)", variable=mode, value="text").pack(anchor="w", padx=12, pady=2)
        tk.Radiobutton(frm1, text="OCR (PDF صورة/سكان)", variable=mode, value="ocr").pack(anchor="w", padx=12, pady=2)

        frm2 = tk.LabelFrame(dlg, text="الصفحات")
        frm2.pack(fill="x", padx=12, pady=6)
        row = tk.Frame(frm2)
        row.pack(fill="x", padx=10, pady=6)
        tk.Radiobutton(row, text="كل الصفحات", variable=page_mode, value="all").pack(side="left")
        tk.Radiobutton(row, text="نطاق:", variable=page_mode, value="range").pack(side="left", padx=(16, 4))
        tk.Entry(row, textvariable=page_range, width=10).pack(side="left")
        tk.Label(row, text="مثال: 1-3 أو 2").pack(side="left", padx=10)

        info = tk.StringVar(value="")
        tk.Label(dlg, textvariable=info, fg="blue").pack(anchor="w", padx=12, pady=(6, 0))

        def run_with_progress(work_fn, done_fn):
            prog = tk.Toplevel(root)
            prog.title("جاري المعالجة…")
            prog.geometry("540x170")
            prog.resizable(False, False)
            prog.transient(root)
            prog.grab_set()

            msg = tk.StringVar(value="بدء…")
            tk.Label(prog, textvariable=msg, anchor="w").pack(fill="x", padx=12, pady=(10, 6))

            pb2 = ttk.Progressbar(prog, length=500, mode="determinate")
            pb2.pack(padx=12, pady=10)
            pb2["value"] = 0

            cancel_flag = {"stop": False}

            def on_cancel():
                cancel_flag["stop"] = True
                msg.set("سيتم الإيقاف بعد الصفحة الحالية…")

            tk.Button(prog, text="إلغاء", command=on_cancel, width=10).pack(pady=6)

            def progress_cb(i, total, text):
                def _ui():
                    msg.set(text)
                    pb2["maximum"] = total
                    pb2["value"] = i
                root.after(0, _ui)

            def worker():
                try:
                    result = work_fn(progress_cb, cancel_flag)
                    root.after(0, lambda: done_fn(result))
                except RuntimeError as e:
                    root.after(0, lambda: messagebox.showinfo("تم", str(e)))
                except Exception as e:
                    root.after(0, lambda: messagebox.showerror("خطأ", str(e)))
                finally:
                    root.after(0, prog.destroy)

            threading.Thread(target=worker, daemon=True).start()

        def start_load():
            if page_mode.get() == "all":
                s0, e0 = (0, page_count)
            else:
                try:
                    s0, e0 = _parse_page_range(page_range.get(), page_count)
                except Exception:
                    messagebox.showerror("خطأ", "صيغة نطاق الصفحات غير صحيحة. اكتب مثل: 1-3 أو 2")
                    return

            chosen_mode = mode.get()

            def work(progress_cb, cancel_flag):
                def cb(i, total, text):
                    progress_cb(i, total, text)
                    if cancel_flag["stop"]:
                        raise RuntimeError("تم إلغاء العملية بواسطة المستخدم.")

                if chosen_mode == "text":
                    txt = pdf_extract_text_range(path, s0, e0, progress_cb=cb)
                    return (txt, "PDF نصّي (استخراج مباشر)")
                elif chosen_mode == "ocr":
                    txt = pdf_ocr_to_text_range(
                        path, s0, e0,
                        lang=ocr_lang.get(),
                        dpi=int(ocr_dpi.get()),
                        progress_cb=cb,
                        psm=int(ocr_psm.get())
                    )
                    return (txt, f"OCR محسّن (lang={ocr_lang.get()}, dpi={int(ocr_dpi.get())}, psm={int(ocr_psm.get())})")
                else:
                    txt, method = pdf_to_text_auto_range(path, s0, e0, progress_cb=cb)
                    return (txt, method)

            def done(result):
                txt, method_used = result
                in_text.delete("1.0", "end")
                in_text.insert("1.0", txt if txt else "")
                update_counts(f"تم فتح PDF — {method_used}")
                if not (txt or "").strip():
                    messagebox.showwarning("تنبيه", "تمت العملية لكن لم يتم استخراج نص. قد تكون جودة السكان ضعيفة أو OCR غير جاهز.")

            dlg.destroy()
            run_with_progress(work, done)

        def update_hint(*_):
            if mode.get() == "ocr":
                ok, how = tesseract_ready()
                info.set(f"OCR {'جاهز' if ok else 'غير جاهز'} — {how}")
            else:
                info.set("")
        update_hint()
        mode.trace_add("write", update_hint)

        btnrow = tk.Frame(dlg)
        btnrow.pack(side="bottom", fill="x", padx=12, pady=12)

        start_btn = tk.Button(btnrow, text="ابدأ", command=start_load, width=12, height=2)
        start_btn.pack(side="left")

        tk.Button(btnrow, text="إلغاء", command=dlg.destroy, width=12, height=2).pack(side="left", padx=10)

        dlg.bind("<Return>", lambda e: start_load())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        start_btn.focus_set()

    # ========= Buttons (two rows so they won't go off-screen) =========
    btns = tk.Frame(root)
    btns.pack(fill="x", padx=10, pady=8)
    row1 = tk.Frame(btns)
    row2 = tk.Frame(btns)
    row1.pack(fill="x")
    row2.pack(fill="x", pady=(6, 0))

    def add_btn(parent, text, cmd, w=12):
        tk.Button(parent, text=text, command=cmd, height=2, width=w).pack(side="left", padx=6)

    add_btn(row1, "تحويل", do_convert)
    add_btn(row1, "تبديل", swap)
    add_btn(row1, "مقارنة", compare_texts)
    add_btn(row1, "نسخ الناتج", copy_output)
    add_btn(row1, "مسح الكل", clear_all)
    add_btn(row1, "فتح TXT", load_txt)
    add_btn(row1, "فتح PDF", load_pdf)

    add_btn(row2, "حفظ الناتج TXT", save_output_txt, w=14)
    add_btn(row2, "تحويل ملف TXT كامل", convert_file_gui, w=16)
    add_btn(row2, "تصدير Word", export_word_gui)
    add_btn(row2, "تصدير PDF", export_pdf_gui)
    add_btn(row2, "حول", about_app, w=10)

    in_text.bind("<KeyRelease>", lambda e: update_counts())
    out_text.bind("<KeyRelease>", lambda e: update_counts())

    update_counts()
    root.mainloop()


if __name__ == "__main__":
    try:
        run_gui()
    except KeyboardInterrupt:
        pass
