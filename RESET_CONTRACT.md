# عقد إعادة الضبط — VidPattern

مرجع مشترك بين الوكلاء. **ما تغيّر شي هون** — إذا لقيت تناقض بلّغ بتقريرك.

الموقع: `C:\Users\LOQ\Pictures\المشروع` (بايثون 3.11، ويندوز، ترميز UTF-8 إجباري).
كل الرسائل للمستخدم **بالعربي**. الكود بلا تعليقات إلا للسبب غير الواضح.

## ما تم (المرحلة ١ — لا تعيد بناءه)

| وحدة | دور |
|---|---|
| `taxonomy.py` | قوائم مغلقة: `DIALECTS` `FRAMEWORKS` `CATEGORIES` `COUNTRIES`، `normalize_*`، `category_distance(a,b)` ← `same|adjacent|far|unknown`، `inject_vocab(prompt)`، `apply_to_pattern(p)` |
| `review_queue.py` | `add(kind, pattern_id, raw, candidates, note, applied)`، `list_items`، `resolve` |
| `clusters.py` | `apply()` بيوسم الأنماط `cluster_id`/`cluster_role` (primary\|variant)، `primaries()`، `load()` |
| `brief.py` | `FIELDS` `REQUIRED` `PUBLISH_REQUIRED` `empty_brief()` `completeness(b)` `require_complete(b)` (بيرمي `BriefIncomplete`) `normalize(b, stem)` `set_field(b,key,val,source,reason)` `load(path)` |
| `claims.py` | `effective_forbidden(b)` `scarcity_allowed(b)` `writer_rules(b)` `scan_script(script, brief)` ← ملاحظات `severity=blocker` بنفس شكل المراجِع |
| `pattern_dedupe.py` `pattern_pool` … | موجودين كما هم |

قيم الأنماط الآن مغلقة: `p["dialect_or_language"]` `p["framework"]` `p["framework_secondary"]` `p["product_category"]` كلها **slugs** (أو `None` لو بانتظار مراجعة). الأصل بـ `p["_legacy"]`.
البريف: `category`/`dialect`/`country` slugs. ملفات المنتجات بـ `products/*.json` والقالب `_template.json` فاضي.

## أشكال البيانات المشتركة

**سيناريو** `library/scripts/<stem>.json` — `_meta` بيصير:
```
_meta: {product, product_file, product_code, number, version, script_id, display_name,
        pattern_id, generated_at, provider, model, label,
        status: "draft"|"reviewing"|"approved"|"needs_owner",
        content_hash}                    # sha256 لـ scenes+hook+cta بعد التطبيع
script_id = "VP-{product_code}-{number}-v{version}"   # مثال: VP-kama-3-v2
```
**مراجعة** `library/reviews/<stem>.review.json`: كما هي + `script_hash` (يطابق `content_hash` وقت المراجعة) + `rounds`.
**اسم الإعلان**: `{country}|{product_code}|{landing_page}|video|{script_id}` — الخانة الخامسة اختيارية عند القراءة؛ الأربع الأولى بتنقرا كما هي.
**أداء يومي** (SQLite `library/perf.db`، جدول `ad_daily`): `ad_name, script_id, date, spend, orders, delivered, collected, delivery_rate, cost_per_delivered, engagement` (aggregate فقط — **ولا بيانات زبائن**).
**مستوى الدليل للنمط**: `evidence_level`: `proven | weak | unproven`، و`evidence_score` 0–100.
**حكم السيناريو**: بتكلفة الطلب المُسلَّم (`spend/delivered`) نسبةً لخط أساس المنتج/البلد؛ ما في حكم تحت `MIN_DELIVERED` (افتراضي 20 طلب مُسلَّم).

## الملكية — كل وكيل بيعدّل ملفاته بس

| وكيل | ملفات يملكها |
|---|---|
| **A · خط الكتابة** (مراحل ٢،٣،٤) | `stage3_generate.py` `review_script.py` `review_loop.py`(جديد) `script_versions.py`(جديد) `library_stats.py`(جديد) `harvest_plan.py`(جديد) `stage0_harvest.py` `generate_images.py` `generate_voice.py` (بوابة الموافقة فقط) `prompts/script_writer.txt` `prompts/script_reviewer.txt` `prompts/pattern_matcher.txt` `web/routes_pipeline.py`(جديد) `tests/test_phase2_*.py` `test_phase3_*.py` `test_phase4_*.py` |
| **B1 · الأداء مع الـ CRM** (مراحل ٥،٦) | `crm.py` `adname.py` `evidence.py` `fatigue.py` `drafts.py`(جديد) `learn_patterns.py` `performance.py` `web/routes_crm.py`(جديد) `CRM_CONTRACT.md`(جديد) `tests/test_phase5_*.py` `test_phase6_*.py` |
| **B2 · التشغيل والأمان** (مرحلة ٨ + الأسرار) | `secrets_store.py` `settings_io.py` `backup.py` `queue_worker.py` `library_sync.py` `scheduler.py` `agent.py` `usage.py` `llm.py`(الحدود والمفاتيح فقط) `connections.py` `imagegen.py` `tts.py` `stt.py` `web/routes_ops.py`(جديد) `CRM_CONTRACT_QUEUE.md`(جديد) `tests/test_phase8_*.py` وسطور كتابة الإعدادات بـ `web/app.py` (بس استبدال كتابة settings بـ `settings_io.save`) |
| **C · الواجهة** (مرحلة ٧) | `web/static/*` كلها (`index.html` `app.js` `style.css` + ملفات جديدة تحتها) |
| أنا (المنسّق) | `web/app.py` (باستثناء ما ذُكر لـ B2)، `taxonomy.py` `brief.py` `claims.py` `clusters.py` `review_queue.py` `stage2_pattern.py` `migrate_phase1.py` `config.py` `run_web.py` |

**ممنوع** تعدّل ملف مش لك. إذا احتجت تغيير بملف غيرك: اكتبه بتقريرك كطلب. الـ routers الجديدة بتصدّر متغير اسمه `router` (FastAPI `APIRouter`) وأنا بضمّها بـ `app.include_router`.
**لا تشغّل** السيرفر على المنفذ 8000 (شغّال). للاختبار استخدم `fastapi.testclient.TestClient(app)` وملفات مؤقتة (`tmp_path`)، ولا تكتب على `library/` الحقيقية بالاختبارات — مرّر مسارات بديلة (monkeypatch على `config.LIBRARY_DIR` وما شابه).
**ممنوع** أي نداء حقيقي لـ LLM أو شبكة بالاختبارات: اعمل monkeypatch على `llm.complete_json` / `llm.complete` و`requests`.

## عقد الـ API

كل مسار تحت `/api`. الأخطاء: `{"detail": "رسالة عربية"}` مع 4xx/5xx مناسب.

### A — `web/routes_pipeline.py`
- `GET /brief/schema` → `{fields:[{key,label,type,group}], required:[..], publish_required:[..]}`
- `GET /products/{file}/completeness` → `{score, filled, total, missing:[..], publish_missing:[..], ready, publish_ready, forbidden_effective:[..], scarcity:{allowed,basis}, offer_policy:"allowed"|"none"}`
- `POST /products/{file}/facts/sync` → يسحب الحقائق التجارية من الـ CRM (يستدعي `crm.fetch_product_facts(product_code, country)` من B، ويمسك `crm.CRMOffline`) ويطبّقها بـ `brief.set_field(..., source="crm")` ← `{applied:[keys], stale:bool, cached_at}`
- `GET /library/coverage` → `{quota:10, active_categories:[slug], matrix:[{category,framework,dialect,count}], per_category:[{category,label,count,quota_met,gap}], gaps:[{category,label,missing}]}`
- `GET /harvest/candidates?status=` ← `{items:[{id,category,source,url,platform,status:"pending|approved|rejected|extracted",note}]}`؛ `POST /harvest/candidates` (إضافة يدوية) ؛ `POST /harvest/candidates/{id}/approve|reject` (approve بيبدأ job استخراج) ؛ `POST /harvest/plan?category=` ← خطة استعلامات/مرشّحين للفئة الناقصة
- `POST /scripts/{file}/review-loop` → `{job_id}` ؛ `GET /scripts/{file}/status` → `{status, blockers, rounds, approved, reason}` ؛ `GET /scripts/{file}/versions` → `{versions:[{version,script_id,created_at,file,status}], diffs:[{from,to,changes:[{scene,field,before,after}]}]}` ؛ `POST /scripts/{file}/approve` (موافقة مالك يدوية — بس لو blockers=0)
- `POST /match` تعديل: نتيجة المطابقة فيها لكل نمط `category_distance` و`transfer_justification` و`fit_score` بعد الخصم، و`warnings:[..]` (خيارات محدودة).

### B1 — `web/routes_crm.py`
- `GET /crm/status` → `{configured, token_set, base_url, connected, last_sync:{at,ok,error,rows}, pending_queue, last_backup:{at,ok,path}, days_since_backup, backup_alert:bool}`
- `PUT /crm/config` `{base_url, token?}` (التوكن بيروح لـ Credential Manager وما بيرجع أبداً)؛ `DELETE /crm/token`
- `POST /crm/sync` → `{job_id}`
- `GET /scripts/{file}/ad-name` → `{ad_name, ready, missing:[..], parts:{country,product,landing_page,type,script_id}}`
- `GET /performance/patterns` → `[{pattern_id,name,evidence_level,evidence_score,delivered,spend,cost_per_delivered,scripts,reusability_opinion}]` مرتّب بـ `evidence_score` نزولاً
- `GET /performance/scripts` → `[{script_file,script_id,delivered,spend,cost_per_delivered,delivery_rate,verdict:"winner|ok|loser|insufficient",reason}]`
- `GET /performance/alerts` → `[{id,ad_name,script_id,type:"fatigue"|"watch",since,detail,draft_id?}]`
- `GET /drafts` / `POST /drafts/{id}/approve` / `POST /drafts/{id}/dismiss`
- `POST /learning/run` → `{job_id}` ؛ `GET /learning/last` → `{at,results:[{pattern_id,name,evidence_strength}],skipped_reason}`


### B2 — `web/routes_ops.py`
- `GET /queue` / `POST /queue/poll`
- `GET /backup/status` ؛ `POST /backup/run` ؛ `POST /backup/restore-test` → `{ok, files_backup, files_restored, match}` ؛ `POST /backup/export-key`
- `GET /settings/spend-limits` / `PUT /settings/spend-limits` `{daily_usd, monthly_usd}`

### وحدات بايثون بين الوكلاء
- B بيوفّر: `crm.fetch_product_facts(product_code, country) -> dict` (يرمي `crm.CRMOffline`)، `adname.build(country, product_code, landing_page, script_id) -> str`، `adname.parse(name) -> {country,product,landing_page,type,script_id|None}`، `evidence.pattern_evidence() -> {pattern_id: {...}}`، `evidence.script_verdicts() -> {script_file: {...}}`.
- A بيوفّر: `stage3_generate.write_for_product(product_path, pattern_id=None, *, review=True) -> Path` (بيكتب سيناريو جديد + حلقة المراجعة ويرجّع مسار الملف) ← B بيستدعيه لموافقة المسودات وطابور الـ CRM؛ و`stage3_generate.match_for_product(product_path) -> dict`.
- B2 بيوفّر: `secrets_store.get_secret(name)->str|None` · `set_secret(name,value)` · `delete_secret(name)` (Windows Credential Manager عبر keyring، خدمة `vidpattern`)؛ `settings_io.load()` (بيحلّ مراجع الأسرار) و`settings_io.save(dict)` (بينقل أي `api_key`/token لمخزن الأسرار ويكتب مرجع بس)؛ `backup.status()` `backup.run_daily_if_due()` `queue_worker.poll_once()` `queue_worker.pending_count()` `library_sync.push_if_changed()`.
- B1 بيوفّر: `crm.get_client()` (`.get/.post/.put(path, ...)` بتوكن من `secrets_store.get_secret("crm_token")`) `crm.is_configured()` `crm.CRMOffline` `crm.CRMError` `crm.sync_performance() -> {ok, rows, from, to, error?}` (بيسحب من آخر مزامنة ناجحة لليوم) `crm.fetch_failure_reasons(product_code, country)` `crm.sync_state() -> {last_success, last_attempt, last_error}` · `learn_patterns.run_weekly_if_due()` · `fatigue.scan_and_draft() -> [draft_id]` · `drafts.create/list/approve/dismiss`.
- B2 `scheduler.py` بينادي أعلاه بالاسم؛ لو وحدة مش موجودة لسا بيتخطّاها بلا انهيار (`try/except ImportError`).
- ثابت: `SCRIPT_MAX_REVIEW_ROUNDS = 2` بـ `config.py` (أنا بضيفه)، `MIN_DELIVERED = 20`، `LIBRARY_QUOTA = 10`.

## معايير الجودة (لكل الوكلاء)
1. اختبارات pytest حقيقية تشتغل بدون شبكة ولا مفاتيح، وتنجح: `python -m pytest tests -q`.
2. لا تكسر اللي شغّال: معيار ٧ مشاهد و٤٥–٥٠ث، سجل منع التكرار، المراجِع، وزن الأدلة بالمطابقة.
3. أي رقم/عتبة بـ `config.py` أو ثابت مسمّى — مش سحر بالكود.
4. تقريرك النهائي: قائمة الملفات، شو اختبرت (أرقام)، أي قرار أخذته وليش، وأي شي ما قدرت تتحقق منه.
