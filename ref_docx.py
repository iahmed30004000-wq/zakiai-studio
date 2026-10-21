"""ملف Word واحد بكل برومبتات الصور المرجعية: قسم لكل منتج وقسم لكل شخصية (بتتجمّع من product_ref وcharacters)."""

from __future__ import annotations

import refprompts

FILENAME = "all_reference_prompts.docx"


def all_prompts_docx() -> tuple[str, bytes]:
    """بيرجّع (اسم الملف، bytes). المنتجات أول وبعدها الشخصيات (غير المتقاعدة)، وكل قسم ترقيمه من 1."""
    import characters
    import product_ref
    items: list[dict] = []
    for row in product_ref.list_products():
        items += product_ref.docx_sections(row["code"])
    for ch in characters.list_all(False):
        items += characters.docx_sections(ch["id"])
    intro = ["ترتيب الشغل لكل منتج ولكل شخصية: ولّد وضعية «أمام» أول وراجعها. بعدها لكل وضعية تانية: ارفق صورة «أمام» مع برومبت الوضعية (قفل الهوية)، وولّد، وارفع كل صورة بمكانها بالنظام.",
             "كل برومبتات المنتج الواحد بنفس الإطار والإضاءة والخلفية عشان الحجم والزوايا تطلع ثابتة؛ ما بيتغيّر غير وضعية الكاميرا. وبالشخصية نفس الوجه واللبس بكل الوضعيات."]
    if not items:
        intro.append("ما في منتجات ولا شخصيات بعد — أضفها بالنظام وبعدين نزّل الملف من جديد.")
    return FILENAME, refprompts.build_docx("برومبتات الصور المرجعية — كل المنتجات والشخصيات", intro, items)
