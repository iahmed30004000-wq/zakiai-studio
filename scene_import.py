"""
استيراد المشاهد من نص أو Excel — للمشروع الحر (free_project.py) وللسيناريو اليدوي بالمهمة الموجّهة (manual_script.py).

  parse_text(text, split_sentences=False) → {scenes, warnings}
  parse_excel(data)                       → {scenes, warnings}    (xlsx بس، ≤ 5 ميغا، ≤ 60 سطر)
  template()                              → bytes                 (xlsx: ورقة «اقرأني» بمثال + ورقة «المشاهد» بقوائم منسدلة)

المشهد (نفس أسماء حقول السيناريو):
  {voiceover, visual, on_screen_text, duration_sec, shot_type, emotion}

النص: الفقرة (سطر فاضي بين فقرتين) = مشهد. جوّا الفقرة أسطر بتبلّش بعنوان بتعبّي الحقل:
  صورة: … · شاشة: … · مدة: 4 · لقطة: قريبة · إحساس: فضول · كلام: …   (الباقي بيصير كلام المشهد)
المدة الناقصة: max(2, كلمات ÷ 2.4) ثانية، أو 3 ثواني لمشهد بلا كلام.
كل الأخطاء رسالة عربية جاهزة (SceneImportError).
"""

from __future__ import annotations

import io
import re
import zipfile

MAX_TEXT = 20_000
MAX_SCENES = 40
MAX_ROWS = 60
MAX_BYTES = 5 * 1024 * 1024
MAX_UNZIPPED = 50 * 1024 * 1024
SILENT_SEC = 3.0
MIN_SEC = 2.0
WORDS_PER_SEC = 2.4
MAX_DURATION_SEC = 60.0

SHEET_SCENES, SHEET_README = "المشاهد", "اقرأني"
SHOT_AR = {"قريبة": "close", "قريب": "close", "لقطة قريبة": "close", "close": "close",
           "متوسطة": "medium", "متوسط": "medium", "لقطة متوسطة": "medium", "medium": "medium",
           "واسعة": "wide", "واسع": "wide", "لقطة واسعة": "wide", "wide": "wide",
           "يد مع المنتج": "hand_product", "يد": "hand_product", "hand_product": "hand_product"}
SHOT_LABELS = ["قريبة", "متوسطة", "واسعة", "يد مع المنتج"]
EMOTIONS = ["فضول", "ثقة", "راحة", "حماس", "ترقّب", "هدوء", "استغراب"]


class SceneImportError(Exception):
    """رسالة عربية جاهزة للعرض (400)."""


# ── أدوات ───────────────────────────────────────────────────────────────
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")
_WORD = re.compile(r"\S+")
_SENT_END = re.compile(r"(?<=[.!؟?!۔])\s+")


def _digits(s: str) -> str:
    return s.translate(_DIGITS)


def words(text) -> int:
    return len(_WORD.findall(str(text or "")))


def _norm(s) -> str:
    return re.sub(r"[\s*:：]+", " ", str(s or "")).strip().casefold()


def _clamp_sec(v: float) -> float:
    return round(min(max(v, 0.5), MAX_DURATION_SEC), 1)


def default_duration(voiceover: str) -> float:
    n = words(voiceover)
    if not n:
        return SILENT_SEC
    return round(max(MIN_SEC, n / WORDS_PER_SEC), 1)


def parse_duration(v) -> float:
    """«4» · «4.5» · «4 ث» · «٤ ثواني» ← ثواني. ValueError لو مش رقم."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        sec = float(v)
    else:
        m = re.search(r"\d+(?:\.\d+)?", _digits(str(v)).replace(",", "."))
        if not m:
            raise ValueError("المدة مش رقم")
        sec = float(m.group(0))
    if sec <= 0:
        raise ValueError("المدة لازم تكون أكبر من صفر")
    return _clamp_sec(sec)


def shot_type_of(v) -> str | None:
    return SHOT_AR.get(_norm(v)) if v else None


def _scene(voiceover="", visual="", text="", dur=None, shot=None, emotion="") -> dict:
    voiceover = re.sub(r"[ \t]+", " ", str(voiceover or "")).strip()
    return {"voiceover": voiceover, "visual": str(visual or "").strip(), "on_screen_text": str(text or "").strip(),
            "duration_sec": dur if dur else default_duration(voiceover), "shot_type": shot,
            "emotion": str(emotion or "").strip()}


# ── النص ────────────────────────────────────────────────────────────────
_LABELS = {
    "visual": ("صورة", "وصف الصورة", "الصورة", "visual", "image"),
    "on_screen_text": ("شاشة", "نص الشاشة", "نص على الشاشة", "الشاشة", "on screen", "screen"),
    "duration": ("مدة", "المدة", "duration"),
    "shot": ("لقطة", "نوع اللقطة", "shot"),
    "emotion": ("إحساس", "الإحساس", "شعور", "emotion"),
    "voiceover": ("كلام", "الكلام", "تعليق", "voiceover"),
}
_LABEL_OF = {_norm(w): k for k, ws in _LABELS.items() for w in ws}
_LINE = re.compile(r"^\s*(?:[-•*·]\s*)?([^:：]{1,24}?)\s*[:：]\s*(.*)$")


def _paragraph(par: str, warnings: list[str], idx: int) -> dict | None:
    fields = {"voiceover": [], "visual": "", "on_screen_text": "", "duration": None, "shot": None, "emotion": ""}
    for line in par.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _LINE.match(line)
        key = _LABEL_OF.get(_norm(m.group(1))) if m else None
        if not key:
            fields["voiceover"].append(line)
            continue
        val = m.group(2).strip()
        if key == "duration":
            try:
                fields["duration"] = parse_duration(val)
            except ValueError:
                warnings.append(f"مشهد {idx}: المدة «{val}» مش رقم — حسبتها من الكلام")
        elif key == "shot":
            fields["shot"] = shot_type_of(val)
            if not fields["shot"]:
                warnings.append(f"مشهد {idx}: نوع اللقطة «{val}» غير معروف — انتجاهل")
        elif key == "voiceover":
            fields["voiceover"].append(val)
        else:
            fields[key] = val
    vo = " ".join(fields["voiceover"])
    if not (vo or fields["visual"] or fields["on_screen_text"]):
        return None
    return _scene(vo, fields["visual"], fields["on_screen_text"], fields["duration"], fields["shot"], fields["emotion"])


def parse_text(text: str, split_sentences: bool = False) -> dict:
    text = str(text or "").replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise SceneImportError("النص فاضي")
    if len(text) > MAX_TEXT:
        raise SceneImportError(f"النص أطول من {MAX_TEXT} حرف — قسّمه لمشروعين")
    warnings: list[str] = []
    scenes: list[dict] = []
    for par in re.split(r"\n\s*\n", text.strip()):
        sc = _paragraph(par, warnings, len(scenes) + 1)
        if not sc:
            continue
        if split_sentences and sc["voiceover"]:
            parts = [p.strip() for p in _SENT_END.split(sc["voiceover"]) if p.strip()]
            if len(parts) > 1:
                first = True
                for p in parts:
                    # عنوان الفقرة (صورة/شاشة/مدة…) بيروح للجملة الأولى بس
                    scenes.append(_scene(p, sc["visual"] if first else "", sc["on_screen_text"] if first else "",
                                         None, sc["shot_type"] if first else None, sc["emotion"] if first else ""))
                    first = False
                continue
        scenes.append(sc)
    if not scenes:
        raise SceneImportError("ما لقيت ولا مشهد بالنص")
    if len(scenes) > MAX_SCENES:
        raise SceneImportError(f"{len(scenes)} مشهد — الحد {MAX_SCENES}. قسّم النص لمشروعين")
    return {"scenes": scenes, "warnings": warnings}


# ── Excel ───────────────────────────────────────────────────────────────
_COLS = [  # (مفتاح، عنوان بالنموذج، بدائل مقبولة، عرض)
    ("voiceover", "الكلام *", ("الكلام", "النص", "كلام", "voiceover"), 46),
    ("on_screen_text", "نص الشاشة", ("شاشة", "نص على الشاشة", "on screen"), 26),
    ("visual", "وصف الصورة", ("صورة", "الصورة", "visual"), 40),
    ("duration", "المدة (ث)", ("المدة", "مدة", "duration"), 12),
    ("shot", "نوع اللقطة", ("لقطة", "shot"), 16),
    ("emotion", "الإحساس", ("إحساس", "شعور", "emotion"), 14),
]
_COL_LOOKUP = {_norm(a): k for k, title, alts, _w in _COLS for a in (title, *alts)}


def _check_file(data: bytes) -> None:
    if not data:
        raise SceneImportError("الملف فاضي")
    if len(data) > MAX_BYTES:
        raise SceneImportError(f"الملف أكبر من {MAX_BYTES // (1024 * 1024)} ميغا")
    if data[:4] == b"\xd0\xcf\x11\xe0":
        raise SceneImportError("هذا ملف Excel قديم (.xls) — افتحه واحفظه كـ .xlsx وارفعه من جديد")
    if data[:2] != b"PK":
        raise SceneImportError("الملف مش بصيغة xlsx — نزّل النموذج وعبّيه")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
        names = set(zf.namelist())
    except zipfile.BadZipFile:
        raise SceneImportError("الملف تالف أو مش xlsx")
    if len(infos) > 300 or sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise SceneImportError("الملف كبير بشكل غير طبيعي")
    if "[Content_Types].xml" not in names or not any(n.startswith("xl/") for n in names):
        raise SceneImportError("الملف مش xlsx — نزّل النموذج وعبّيه")


def _cell(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v == int(v):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    return s or None


def parse_excel(data: bytes) -> dict:
    import openpyxl
    _check_file(data)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:                                           # noqa: BLE001 — أي خلل بالقراءة = ملف مش صالح
        raise SceneImportError("ما قدرت أقرأ الملف — تأكد إنو xlsx سليم") from e
    try:
        ws = None
        for n in wb.sheetnames:
            if _norm(n) in (_norm(SHEET_SCENES), "scenes"):
                ws = wb[n]
                break
        if ws is None:                                               # بلا ورقة «المشاهد»: أول ورقة مش «اقرأني»
            for n in wb.sheetnames:
                if _norm(n) != _norm(SHEET_README):
                    ws = wb[n]
                    break
        if ws is None:
            raise SceneImportError(f"ما لقيت ورقة «{SHEET_SCENES}» — استعمل النموذج (زر «نزّل النموذج»)")
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    if not rows:
        raise SceneImportError(f"ورقة «{SHEET_SCENES}» فاضية")
    colmap: dict[int, str] = {}
    unknown: list[str] = []
    for i, h in enumerate(rows[0]):
        if h is None or not str(h).strip():
            continue
        k = _COL_LOOKUP.get(_norm(h))
        if k is None:
            unknown.append(str(h).strip())
        elif k not in colmap.values():
            colmap[i] = k
    if not colmap:
        raise SceneImportError("ما لقيت عناوين الأعمدة بالسطر الأول — استعمل النموذج")
    warnings: list[str] = []
    if unknown:
        warnings.append("أعمدة مش معروفة وانتجاهلت: " + "، ".join(unknown))
    scenes: list[dict] = []
    errors: list[str] = []
    for rn, row in enumerate(rows[1:], 2):
        vals = {k: _cell(row[i]) if i < len(row) else None for i, k in colmap.items()}
        if not any(v is not None for v in vals.values()):
            continue
        if len(scenes) >= MAX_ROWS:
            raise SceneImportError(f"أكتر من {MAX_ROWS} مشهد بالملف — قسّمه لملفين")
        dur = None
        if vals.get("duration") is not None:
            try:
                dur = parse_duration(vals["duration"])
            except ValueError:
                errors.append(f"سطر {rn}: المدة «{vals['duration']}» مش رقم")
        shot = None
        if vals.get("shot") is not None:
            shot = shot_type_of(vals["shot"])
            if not shot:
                errors.append(f"سطر {rn}: نوع اللقطة «{vals['shot']}» مش من القائمة — اختر من القائمة المنسدلة")
        vo, vis, txt = vals.get("voiceover"), vals.get("visual"), vals.get("on_screen_text")
        if vo is None and vis is None and txt is None:
            warnings.append(f"سطر {rn}: بلا كلام ولا وصف ولا نص شاشة — تجاهلته")
            continue
        scenes.append(_scene(_digits(str(vo)) if isinstance(vo, (int, float)) else vo, vis, txt, dur, shot, vals.get("emotion")))
    if errors:
        raise SceneImportError("أخطاء بالملف: " + "؛ ".join(errors[:5]) + (f" (و{len(errors) - 5} غيرها)" if len(errors) > 5 else ""))
    if not scenes:
        raise SceneImportError("ما لقيت ولا مشهد بالملف")
    return {"scenes": scenes, "warnings": warnings}


def template() -> bytes:
    """ملف النموذج: ورقة «اقرأني» (شرح + مثال، ما بتنستورد) وورقة «المشاهد» فاضية بقوائم منسدلة."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    rd = wb.active
    rd.title = SHEET_README
    rd.sheet_view.rightToLeft = True
    rd.column_dimensions["A"].width = 110
    lines = [
        "كيف تستعمل النموذج",
        "1) روح لورقة «المشاهد»: سطر لكل مشهد. الأعمدة: الكلام · نص الشاشة · وصف الصورة · المدة · نوع اللقطة · الإحساس.",
        "2) الحقل الوحيد المطلوب هو «الكلام» (ممكن مشهد بلا كلام إذا عبّيت وصف الصورة أو نص الشاشة).",
        "3) المدة بالثواني؛ إذا تركتها فاضية بتتحسب من عدد الكلمات (حوالي كلمتين ونص بالثانية).",
        "4) نوع اللقطة والإحساس من القائمة المنسدلة (أو اتركهم فاضيين).",
        f"5) أقصى عدد مشاهد: {MAX_ROWS}. ارفع الملف من «استورد» بالمشروع.",
        "",
        "مثال (ما بينستورد):",
        "الكلام: ليش عيونك بتتعب آخر النهار؟ | نص الشاشة: عيونك تعبانة؟ | وصف الصورة: وجه امرأة بتفرك عيونها قدام اللابتوب | المدة: 3 | نوع اللقطة: قريبة | الإحساس: فضول",
    ]
    for i, t in enumerate(lines, 1):
        c = rd.cell(row=i, column=1, value=t)
        c.alignment = Alignment(wrap_text=True, vertical="top", horizontal="right")
        if i == 1:
            c.font = Font(bold=True, size=14)
    ws = wb.create_sheet(SHEET_SCENES)
    ws.sheet_view.rightToLeft = True
    head_fill = PatternFill("solid", fgColor="FFE7A3")
    for i, (_k, title, _alts, width) in enumerate(_COLS, 1):
        c = ws.cell(row=1, column=i, value=title)
        c.font = Font(bold=True)
        c.fill = head_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    lists = wb.create_sheet("قوائم")
    for i, v in enumerate(SHOT_LABELS, 1):
        lists.cell(row=i, column=1, value=v)
    for i, v in enumerate(EMOTIONS, 1):
        lists.cell(row=i, column=2, value=v)
    lists.sheet_state = "hidden"
    col = {k: get_column_letter(i) for i, (k, *_r) in enumerate(_COLS, 1)}
    dv_shot = DataValidation(type="list", formula1=f"=قوائم!$A$1:$A${len(SHOT_LABELS)}", allow_blank=True)
    dv_emo = DataValidation(type="list", formula1=f"=قوائم!$B$1:$B${len(EMOTIONS)}", allow_blank=True)
    dv_dur = DataValidation(type="decimal", operator="between", formula1="0.5", formula2=str(int(MAX_DURATION_SEC)), allow_blank=True)
    for dv, k in ((dv_shot, "shot"), (dv_emo, "emotion"), (dv_dur, "duration")):
        ws.add_data_validation(dv)
        dv.add(f"{col[k]}2:{col[k]}{MAX_ROWS + 1}")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
