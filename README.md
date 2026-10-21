# VidPattern — منظومة استخراج أنماط الإعلانات الناجحة وتوليد السيناريوهات

أربع مراحل، كل مرحلة أداة مستقلة، ومخرج كل واحدة JSON بيغذّي اللي بعدها.

```
كلمة بحث   →  [0] Harvester   →  links.txt (مفلتر بالأداء)
                                      ↓
                              [1] Extractor    →  extract.json + frames + srt
                                      ↓
                              [2] Pattern Miner →  library/patterns/*.pattern.json
                                      ↓
ملف منتجك  →  [3] Matcher + Writer →  library/scripts/*.md + *.json
```

**السلسلة كاملة بأمر واحد:**

```bash
python run_all.py --source tiktok --query "كريم ازالة الشعر" --product products/vara.json
python run_all.py --links library/links.txt --product products/vara.json   # عندي روابط جاهزة
python run_all.py --product products/vara.json --from 3                    # المكتبة جاهزة، سيناريو بس
```

---

## التثبيت

```bash
# 1) ffmpeg (إلزامي)
#    ويندوز:  winget install Gyan.FFmpeg
#    ماك:     brew install ffmpeg
#    لينكس:   sudo apt install ffmpeg

# 2) مكتبات بايثون
pip install -r requirements.txt

# 3) المفاتيح
export ANTHROPIC_API_KEY=sk-ant-...        # ويندوز: setx ANTHROPIC_API_KEY "sk-ant-..."
export APIFY_TOKEN=apify_api_...           # للمرحلة 0 فقط
```

أول تشغيل بينزّل موديل Whisper و OCR (حوالي 2 جيجا) — مرة وحدة بس.

---

## المرحلة 0 — الحصاد

```bash
# بحث بكلمة
python stage0_harvest.py tiktok --query "كريم ازالة الشعر" --limit 60

# بهاشتاق
python stage0_harvest.py tiktok --hashtag hairremoval --limit 100

# حساب منافس كامل
python stage0_harvest.py tiktok --profile competitor_account

# مكتبة إعلانات فيسبوك
python stage0_harvest.py adlibrary --query "كريم" --country SY

# ادمج كل الحصادات في ملف روابط واحد بدون تكرار
python stage0_harvest.py --merge
```

بيفلتر أوتوماتيك حسب عتبات `config.py`: مشاهدات، لايكات، نسبة تفاعل، وعمر الفيديو.
وبيرتّب المرشّحين بمعادلة مركّبة (وصول + تفاعل + حداثة) وبياخد أعلى `HARVEST_TOP_N`.

المخرج: `library/candidates/<مصدر>_<تاريخ>.json` + `library/links.txt`.

> **مهم:** معرّفات أكترز Apify في `config.py` بتتغيّر أحياناً. لو رجع خطأ 404،
> افتح متجر Apify، خد المعرّف الصحيح، وبدّله في `APIFY_ACTORS`.
> العتبات الافتراضية مضبوطة لسوق كبير — للسوق السوري نزّل `MIN_VIEWS` لـ 20,000.

---

## المرحلة 1 — الاستخراج

```bash
# رابط تيك توك أو ريلز
python stage1_extract.py "https://www.tiktok.com/@user/video/123456"

# ملف محلي (مكتبة إعلانات فيسبوك: حمّل الفيديو ومرّر الملف)
python stage1_extract.py ./ads/competitor_01.mp4 --id competitor_01

# دفعة كاملة
python stage1_extract.py --batch links.txt
```

بيطلع في `library/raw/<video_id>/`:
- `extract.json` — كل شي منظّم
- `transcript.srt` — تفريغ بالتوقيتات (بينفع مباشرة مع Kling / Veo)
- `frames/scene_XX.jpg` — لقطة مفتاحية لكل مشهد

**ملاحظة عن Ad Library:** روابط `facebook.com/ads/library` ما بتتحمّل مباشرة غالباً. افتح الإعلان، حمّل الفيديو، وشغّله كملف محلي.

---

## المرحلة 2 — تشريح النمط

```bash
python stage2_pattern.py library/raw/competitor_01/extract.json

# أو حلّل كل الجديد دفعة وحدة
python stage2_pattern.py --all
```

بيطلع ملف نمط مستقل في `library/patterns/`. كل نمط بيحتوي:
نوع الهوك وآليته، القوس العاطفي مشهد بمشهد، ثانية دخول المنتج، آلية الإثبات،
الاعتراضات المعالَجة، إيقاع القص، ولغة بصرية — بالإضافة لـ `scene_blueprint`
مجرّد لوظائف قابلة للنقل على أي منتج.

**كل ما زاد عدد الأنماط زادت قيمة المنظومة.** الهدف 25–30 نمط.

---

## المرحلة 3 — المطابقة والتوليد

```bash
# انسخ النموذج واملأه
cp products/_template.json products/vara.json

# شوف أفضل 3 أنماط لهذا المنتج بدون توليد
python stage3_generate.py products/vara.json --match-only

# ولّد السيناريو على أفضل نمط
python stage3_generate.py products/vara.json

# أو افرض نمط معيّن
python stage3_generate.py products/vara.json --pattern competitor_01
```

بيطلع في `library/scripts/`:
- `<منتج>__<نمط>__<تاريخ>.md` — السيناريو جاهز للقراءة
- نفس الملف `.json` — جاهز يدخل على Nano Banana 2

**السيناريو ملتزم:** 7 مشاهد بالضبط، 45–50 ثانية، إيقاع كلام محسوب (2.2–2.6 كلمة/ثانية)، ولهجة المنتج.

---

## منع التكرار

`library/used_registry.json` بيسجّل لكل منتج: الهوكات، اللقطات، نقاط الألم،
والأنماط المستخدمة. كل توليد جديد بيستلم السجل ومصرّح عليه إنه ما يعيد أي شي منهم.
احذف الملف إذا بدك تبلّش من الصفر.

---

## التوصيل مع Nano Banana 2

مخرج `.json` من المرحلة 3 فيه لكل مشهد: `visual` + `voiceover` + `shot_type` +
`duration_sec` — وهاي بالضبط مدخلات برومبت الصور وبرومبت الحركة عندك.
و `transcript.srt` من المرحلة 1 بينفع كمرجع إيقاع للمزامنة.

---

## الضبط

كل الإعدادات في `config.py`: موديل Whisper، حساسية كشف المشاهد، لغات OCR،
الموديلات المستخدمة، وقواعد السيناريو (عدد المشاهد والمدة).
البرومبتات الثلاثة في `prompts/` — عدّلها براحتك، هي نصوص مفتوحة.
