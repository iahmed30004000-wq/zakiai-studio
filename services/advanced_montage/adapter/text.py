"""أدوات نص: توحيد الأرقام للاتينية، وكشف البيانات الشخصية/السرية قبل ما توصل للـ job."""

from __future__ import annotations

import re

# الأرقام الهندية (٠-٩) والفارسية (۰-۹) ← لاتينية (0-9)، والفاصلة العشرية/الآلاف العربية ← . و ,
_DIGITS = {0x0660 + i: str(i) for i in range(10)}
_DIGITS.update({0x06F0 + i: str(i) for i in range(10)})
_DIGITS.update({0x066B: ".", 0x066C: ","})


def latin_digits(s) -> str:
    """بيحوّل أي أرقام عربية بالنص لأرقام لاتينية (مثال: «١٩٫٩» ← «19.9»)."""
    return str(s if s is not None else "").translate(_DIGITS)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_PHONE = re.compile(r"(?<!\d)(?:\+|00)\d[\d\s\-()]{7,}\d|(?<!\d)\d(?:[\s\-]?\d){8,}(?!\d)")
_SECRET = re.compile(
    r"\b(?:sk|pk|ghp|xox[abp]|AKIA|AIza|bearer)[-_ ]?[A-Za-z0-9_\-]{10,}|[A-Za-z0-9_\-+/=]{32,}", re.I)


def find_sensitive(text: str, *, check_phone: bool = True) -> str | None:
    """بيرجّع سبب (عربي) لو النص فيه إيميل/رابط/رقم هاتف/مفتاح، وإلا None.
    السعر ما بنفحصه على الهاتف لأن أسعار كبيرة (مثل 1500000) ممكنة."""
    t = latin_digits(text)
    if _EMAIL.search(t):
        return "فيه عنوان إيميل"
    if _URL.search(t):
        return "فيه رابط"
    if _SECRET.search(t):
        return "فيه نص شبيه بمفتاح سرّي"
    if check_phone and _PHONE.search(t):
        return "فيه رقم هاتف"
    return None


# أسماء مفاتيح ممنوعة بأي job (فحص دفاعي أخير)
SECRET_KEY_RX = re.compile(r"token|secret|api[_-]?key|passw|authorization|bearer|credential", re.I)
_ABS_PATH_RX = re.compile(r"^(?:[A-Za-z]:[\/]|[\/]{1,2}|~)")


_PATH_KEYS = {"library_path", "src", "path", "library_rel"}


def scan_job_for_leaks(obj, where: str = "job", key: str = "") -> list[str]:
    """بيمشي على كل الـ job ويرجّع قائمة مشاكل: مفاتيح سرّية، مسارات مطلقة، إيميلات، توكنات."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if SECRET_KEY_RX.search(str(k)):
                out.append(f"{where}.{k}: اسم حقل شبيه بمفتاح/توكن")
            out += scan_job_for_leaks(v, f"{where}.{k}", str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += scan_job_for_leaks(v, f"{where}[{i}]", key)
    elif isinstance(obj, str):
        if _ABS_PATH_RX.match(obj) or "\\" in obj:
            out.append(f"{where}: مسار مطلق أو بشرطة عكسية")
        elif key in _PATH_KEYS:
            pass                                    # مسارات نسبية: ما بنفحصها كنص سرّي
        elif _EMAIL.search(obj):
            out.append(f"{where}: إيميل")
        elif _SECRET.search(obj):
            out.append(f"{where}: نص شبيه بتوكن")
    return out


_WIN_PATH = re.compile(r"""[A-Za-z]:[\\/][^\s"'<>|]*""")
_POSIX_PATH = re.compile(r"(?<![\w:./-])/(?:[\w.\-\u0600-\u06FF]+/)+([\w.\-\u0600-\u06FF]+)")


def redact_paths(text: str) -> str:
    """بيشيل المسارات المطلقة من نص خطأ (بيخلّي اسم الملف بس) حتى ما يظهر اسم المستخدم أو هيكل الجهاز."""
    def base_of(m):
        return "…/" + re.split(r"[\\/]", m.group(0).rstrip("\\/"))[-1]
    t = _WIN_PATH.sub(base_of, str(text or ""))
    return _POSIX_PATH.sub(lambda m: "…/" + m.group(1), t)
