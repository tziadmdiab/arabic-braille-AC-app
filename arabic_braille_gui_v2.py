# -*- coding: utf-8 -*-
import re
import tkinter as tk
from tkinter import filedialog, messagebox

# --- Optional exports ---
# Word export: pip install python-docx
try:
    from docx import Document  # type: ignore
except ImportError:
    Document = None

# PDF export: pip install reportlab
try:
    from reportlab.pdfgen import canvas  # type: ignore
    from reportlab.lib.pagesizes import A4  # type: ignore
except ImportError:
    canvas = None
    A4 = None

# Optional (better Arabic shaping in PDF when exporting Arabic):
# pip install arabic-reshaper python-bidi
try:
    import arabic_reshaper  # type: ignore
    from bidi.algorithm import get_display  # type: ignore
except ImportError:
    arabic_reshaper = None
    get_display = None


# =========================
# 1) تنظيف النص: حذف التشكيل
# =========================
TASHKEEL_RE = re.compile(r'[\u0617-\u061A\u064B-\u0652\u0670\u0653-\u0655]')


def remove_tashkeel(text: str) -> str:
    return re.sub(TASHKEEL_RE, '', text)


def normalize_newlines(text: str) -> str:
    # يحوّل كل أنواع نهاية السطر إلى \n (يحل مشكلة \r التي كانت تنتج ⍰)
    return text.replace('\r\n', '\n').replace('\r', '\n')


# =========================
# 2) جداول التحويل (عربي -> برايل)
# =========================
NUM_SIGN = '⠼'  # numeric indicator

AR2BR = {
    'ا': '⠁', 'أ': '⠁', 'إ': '⠁', 'آ': '⠁',
    'ب': '⠃', 'ت': '⠞', 'ث': '⠹', 'ج': '⠚', 'ح': '⠱', 'خ': '⠭',
    'د': '⠙', 'ذ': '⠮', 'ر': '⠗', 'ز': '⠵', 'س': '⠎', 'ش': '⠩',
    'ص': '⠯', 'ض': '⠷', 'ط': '⠾', 'ظ': '⠿', 'ع': '⠫', 'غ': '⠣',
    'ف': '⠋', 'ق': '⠟', 'ك': '⠅', 'ل': '⠇', 'م': '⠍', 'ن': '⠝',
    'ه': '⠓', 'ة': '⠓', 'و': '⠺', 'ي': '⠊', 'ى': '⠊',

    # الهمزات (تمثيل عملي/تعليمي)
    'ء': '⠄', 'ؤ': '⠺⠄', 'ئ': '⠊⠄',

    # مسافات/أسطر
    ' ': ' ',
    '\n': '\n',
    '\t': '\t',

    # علامات ترقيم
    '،': '⠂', ',': '⠂',
    '.': '⠲', '۔': '⠲',
    '؛': '⠆', ';': '⠆',
    ':': '⠒',
    '!': '⠖',
    '-': '⠤', '_': '⠤',
    'ـ': '⠤',  # التطويل (حل عملي)

    # اقتباسات/أقواس (ملاحظة: بعض الرموز تتصادم مع ؟ في العكس)
    '«': '⠦',   # فتح اقتباس
    '»': '⠴',   # غلق اقتباس
    '“': '⠦',   # فتح اقتباس (نفس ⠦)
    '”': '⠴',   # غلق اقتباس (نجعله ⠴ لتمييزه)
    '"': '⠶',
    '(': '⠶', ')': '⠶',

    # استفهام
    '؟': '⠦', '?': '⠦',
}

DIGIT_TO_BR = {
    '1': '⠁', '2': '⠃', '3': '⠉', '4': '⠙', '5': '⠑',
    '6': '⠋', '7': '⠛', '8': '⠓', '9': '⠊', '0': '⠚',
}

ARABIC_DIGITS_TO_LATIN = {
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
    '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
}

LATIN_TO_ARABIC_DIGITS = {
    '0': '٠', '1': '١', '2': '٢', '3': '٣', '4': '٤',
    '5': '٥', '6': '٦', '7': '٧', '8': '٨', '9': '٩',
}


# =========================
# 3) عكس التحويل (برايل -> عربي)
# =========================
BR2AR = {}
for k, v in AR2BR.items():
    if len(k) == 1:
        # ملاحظة: إذا تكرر v لأكثر من مفتاح عربي، سيأخذ الأخير (طبيعي)
        BR2AR[v] = k

BR_TO_DIGIT = {v: k for k, v in DIGIT_TO_BR.items()}

# إضافات/تفضيلات في العكس (بدون مفاتيح مكررة)
EXTRA_BR2AR = {
    '⠂': '،',
    '⠲': '.',
    '⠆': '؛',
    '⠒': ':',
    '⠖': '!',
    '⠤': '-',
    '⠶': '"',
    '⠴': '»',

    # ⠦ يستعمل عندك لعدة علامات (؟ و « و “)
    # لا يمكن إرجاعه بدقة بدون سياق؛ نختار افتراضيًا "؟"
    '⠦': '؟',
}

ALEF_FORMS = {'ا', 'أ', 'إ', 'آ'}


# =========================
# 4) محرك التحويل
# =========================
def normalize_digits_to_latin(text: str) -> str:
    return ''.join(ARABIC_DIGITS_TO_LATIN.get(ch, ch) for ch in text)


def arabic_to_braille(text: str, keep_tashkeel: bool = False) -> str:
    text = normalize_newlines(text)
    if not keep_tashkeel:
        text = remove_tashkeel(text)
    text = normalize_digits_to_latin(text)

    out = []
    i = 0
    in_number = False

    while i < len(text):
        # تحسين "لا" بمختلف أشكال الألف: لا / لأ / لإ / لآ
        if i + 1 < len(text) and text[i] == 'ل' and text[i + 1] in ALEF_FORMS:
            in_number = False
            out.append(AR2BR.get('ل', '⍰'))
            out.append(AR2BR.get(text[i + 1], '⍰'))
            i += 2
            continue

        ch = text[i]

        if ch.isdigit():
            if not in_number:
                out.append(NUM_SIGN)
                in_number = True
            out.append(DIGIT_TO_BR.get(ch, '⍰'))
            i += 1
            continue

        in_number = False
        out.append(AR2BR.get(ch, '⍰'))
        i += 1

    return ''.join(out)


def braille_to_arabic(braille_text: str, arabic_digits: bool = False) -> str:
    braille_text = normalize_newlines(braille_text)

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
            else:
                in_number = False
                out.append(BR2AR.get(ch, EXTRA_BR2AR.get(ch, '؟')))
            i += 1
            continue

        out.append(BR2AR.get(ch, EXTRA_BR2AR.get(ch, '؟')))
        i += 1

    return ''.join(out)


# =========================
# 5) وظائف ملفات TXT
# =========================
def convert_file(path_in: str, path_out: str, direction: str, keep_tashkeel: bool, arabic_digits: bool):
    with open(path_in, 'r', encoding='utf-8') as f:
        content = normalize_newlines(f.read())

    if direction == 'AR2BR':
        converted = arabic_to_braille(content, keep_tashkeel=keep_tashkeel)
    else:
        converted = braille_to_arabic(content, arabic_digits=arabic_digits)

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
    if arabic_reshaper is not None and get_display is not None:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    return text


def export_to_pdf(text: str, path_out: str, assume_arabic: bool = True):
    if canvas is None or A4 is None:
        raise RuntimeError("reportlab غير مثبت. ثبّته بالأمر: pip install reportlab")

    c = canvas.Canvas(path_out, pagesize=A4)
    width, height = A4
    margin = 50
    y = height - margin

    lines = normalize_newlines(text).split('\n')

    for line in lines:
        if y < margin:
            c.showPage()
            y = height - margin

        draw_line = _shape_arabic_for_pdf_if_possible(line) if assume_arabic else line

        # العربية أفضل بالمحاذاة يمين
        if assume_arabic:
            c.drawRightString(width - margin, y, draw_line)
        else:
            c.drawString(margin, y, draw_line)

        y -= 16

    c.save()


# =========================
# 7) GUI
# =========================
def run_gui():
    root = tk.Tk()
    root.title("محوّل عربي ↔ برايل (TXT + GUI + Word/PDF)")
    root.geometry("1020x700")

    direction = tk.StringVar(value="AR2BR")
    keep_tashkeel = tk.BooleanVar(value=False)
    arabic_digits_out = tk.BooleanVar(value=True)  # عند (برايل → عربي)

    # ========= أدوات النسخ/اللصق داخل Tkinter =========
    def make_context_menu(text_widget: tk.Text):
        menu = tk.Menu(root, tearoff=0)
        menu.add_command(label="قص (Cut)", command=lambda: text_widget.event_generate("<<Cut>>"))
        menu.add_command(label="نسخ (Copy)", command=lambda: text_widget.event_generate("<<Copy>>"))
        menu.add_command(label="لصق (Paste)", command=lambda: text_widget.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="تحديد الكل (Select All)", command=lambda: text_widget.event_generate("<<SelectAll>>"))

        def show_menu(event):
            text_widget.focus_set()  # مهم: يعطي التركيز للمربع قبل تنفيذ الأوامر
            menu.tk_popup(event.x_root, event.y_root)

        # زر يمين (Windows/Linux) + Button-2 لبعض الأنظمة
        text_widget.bind("<Button-3>", show_menu)
        text_widget.bind("<Button-2>", show_menu)

        # اختصارات لوحة المفاتيح (تعمل داخل المربع نفسه)
        text_widget.bind("<Control-a>", lambda e: (text_widget.event_generate("<<SelectAll>>"), "break"))
        text_widget.bind("<Control-c>", lambda e: (text_widget.event_generate("<<Copy>>"), "break"))
        text_widget.bind("<Control-x>", lambda e: (text_widget.event_generate("<<Cut>>"), "break"))
        text_widget.bind("<Control-v>", lambda e: (text_widget.event_generate("<<Paste>>"), "break"))

        # بعض لوحات المفاتيح: Shift+Insert للصق و Ctrl+Insert للنسخ
        text_widget.bind("<Shift-Insert>", lambda e: (text_widget.event_generate("<<Paste>>"), "break"))
        text_widget.bind("<Control-Insert>", lambda e: (text_widget.event_generate("<<Copy>>"), "break"))

    # أعلى
    top = tk.Frame(root)
    top.pack(fill="x", padx=10, pady=8)

    tk.Label(top, text="الاتجاه:").pack(side="left")
    tk.Radiobutton(top, text="عربي → برايل", variable=direction, value="AR2BR").pack(side="left", padx=8)
    tk.Radiobutton(top, text="برايل → عربي", variable=direction, value="BR2AR").pack(side="left", padx=8)

    tk.Checkbutton(
        top,
        text="عدم حذف التشكيل (قد يظهر ⍰ لبعض الحركات)",
        variable=keep_tashkeel
    ).pack(side="left", padx=14)

    tk.Checkbutton(
        top,
        text="عند (برايل → عربي) استخدم الأرقام العربية ٠١٢٣…",
        variable=arabic_digits_out
    ).pack(side="left", padx=14)

    # صناديق نص
    main = tk.Frame(root)
    main.pack(fill="both", expand=True, padx=10, pady=10)

    left = tk.Frame(main)
    right = tk.Frame(main)
    left.pack(side="left", fill="both", expand=True, padx=(0, 6))
    right.pack(side="left", fill="both", expand=True, padx=(6, 0))

    tk.Label(left, text="النص الأصلي").pack(anchor="w")
    in_text = tk.Text(left, wrap="word", undo=True)
    in_text.pack(fill="both", expand=True)

    tk.Label(right, text="الناتج").pack(anchor="w")
    out_text = tk.Text(right, wrap="word", undo=True)
    out_text.pack(fill="both", expand=True)

    # ✅ تفعيل النسخ/اللصق + القائمة بالزر الأيمن
    make_context_menu(in_text)
    make_context_menu(out_text)

    # شريط حالة (عداد)
    status = tk.StringVar(value="الأصلي: 0 حرف | الناتج: 0 حرف")
    status_bar = tk.Label(root, textvariable=status, anchor="w")
    status_bar.pack(fill="x", padx=10, pady=(0, 6))

    def update_counts(*_):
        src = in_text.get("1.0", "end-1c")
        dst = out_text.get("1.0", "end-1c")
        status.set(f"الأصلي: {len(src)} حرف | الناتج: {len(dst)} حرف")

    def do_convert():
        src = in_text.get("1.0", "end-1c")
        if direction.get() == "AR2BR":
            res = arabic_to_braille(src, keep_tashkeel=keep_tashkeel.get())
        else:
            res = braille_to_arabic(src, arabic_digits=arabic_digits_out.get())
        out_text.delete("1.0", "end")
        out_text.insert("1.0", res)
        update_counts()

    def swap_texts():
        a = in_text.get("1.0", "end-1c")
        b = out_text.get("1.0", "end-1c")
        in_text.delete("1.0", "end")
        out_text.delete("1.0", "end")
        in_text.insert("1.0", b)
        out_text.insert("1.0", a)
        update_counts()

    def clear_all():
        in_text.delete("1.0", "end")
        out_text.delete("1.0", "end")
        update_counts()

    def copy_output():
        data = out_text.get("1.0", "end-1c")
        root.clipboard_clear()
        root.clipboard_append(data)
        messagebox.showinfo("تم", "تم نسخ الناتج إلى الحافظة")

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
        update_counts()

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
        messagebox.showinfo("تم", "تم حفظ الملف بنجاح")

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
        convert_file(pin, pout, direction.get(), keep_tashkeel.get(), arabic_digits_out.get())
        messagebox.showinfo("تم", "تم تحويل الملف وحفظ الناتج")

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
            messagebox.showinfo("تم", "تم تصدير الملف إلى Word بنجاح")
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
            export_to_pdf(data, path, assume_arabic=assume_arabic)
            msg = "تم تصدير PDF بنجاح."
            if assume_arabic and (arabic_reshaper is None or get_display is None):
                msg += "\nملاحظة: لتحسين عرض العربية داخل PDF ثبّت: arabic-reshaper و python-bidi"
            messagebox.showinfo("تم", msg)
        except Exception as e:
            messagebox.showerror("خطأ", str(e))

    # أزرار
    buttons_frame = tk.Frame(root)
    buttons_frame.pack(fill="x", padx=10, pady=8)

    tk.Button(buttons_frame, text="تحويل", command=do_convert, height=2, width=12).pack(side="left", padx=6)
    tk.Button(buttons_frame, text="تبديل (Swap)", command=swap_texts, height=2, width=12).pack(side="left", padx=6)
    tk.Button(buttons_frame, text="نسخ الناتج", command=copy_output, height=2, width=12).pack(side="left", padx=6)
    tk.Button(buttons_frame, text="مسح الكل", command=clear_all, height=2, width=12).pack(side="left", padx=6)

    tk.Button(buttons_frame, text="فتح TXT", command=load_txt, height=2, width=12).pack(side="left", padx=6)
    tk.Button(buttons_frame, text="حفظ الناتج TXT", command=save_output_txt, height=2, width=14).pack(side="left", padx=6)
    tk.Button(buttons_frame, text="تحويل ملف كامل", command=convert_file_gui, height=2, width=14).pack(side="left", padx=6)

    tk.Button(buttons_frame, text="تصدير Word", command=export_word_gui, height=2, width=12).pack(side="left", padx=6)
    tk.Button(buttons_frame, text="تصدير PDF", command=export_pdf_gui, height=2, width=12).pack(side="left", padx=6)

    # تحديث العدادات عند الكتابة
    in_text.bind("<KeyRelease>", update_counts)
    out_text.bind("<KeyRelease>", update_counts)

    update_counts()
    root.mainloop()


if __name__ == "__main__":
    run_gui()
