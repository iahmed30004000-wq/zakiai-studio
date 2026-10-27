# Handoff 2: code review, audit plan and everything that is left (27 Oct 2026)

Audience: the next agent account and the human developer who will review this project.
Written by: the previous agent (Claude). Everything below was checked against the repository and the live site on 27 Oct 2026. Where something was NOT checked, the text says so.

This file does **not** repeat what is already done. It tells you (A) where the work lives and the rules, (B) how the system is built, (C) the audit plan, (D) every integration with other systems, (E) the complete list of what is left, in order, (F) the stop conditions.

Arabic words in «guillemets» are the exact labels the owner sees on screen or his exact words. Copy them from the source, never retype or translate them.

---

## 0. Order of reading, and the one rule above all

1. `AGENTS.md` (the owner's rules and repo map).
2. `docs/HANDOFF_GLM.md` (the first handoff: the ten commandments, exact ship procedure, engineering rules, recipes, never-do list, skills). **It is still valid.** This file adds to it and never replaces it. Where this file says "see HANDOFF_GLM §n", read that section.
3. This file.
4. Only when needed: `docs/WORK_LOG_AR.md` (full history, Arabic), `docs/PROJECT_STATE_AR.md`, `docs/RESEARCH_FEATURES_AR.md`, `docs/PLAN_google_drive_AR.md`, `docs/PLAN_free_project_model_library_AR.md`, `STUDIO_DESIGN.md`, `ui_contract.md`, `ext_contract.md`, `CRM_CONTRACT.md`, `CRM_CONTRACT_QUEUE.md`, `contracts/vp-ops.v1.yaml`, `مواصفات_تنفيذ_العمليات.md`, `README_AR_نشر_السيرفر.md`.

**The rule above all (the owner's words, 27 Oct):** «ما بدي يخرب شي عاملو … مش لازم يغلط اي غلط». Treat the project as live and fragile. The site is used by the owner from now on. Every change goes through a pull request, with tests you ran yourself, and with your report saying what was verified and what was not. If you are not sure a change is safe, do not make it: write it in the report as a finding or a question.

---

## 1. Where the work lives (accounts, links, deployment)

| Item | Value |
|---|---|
| Work repository (the ONLY one you push to) | https://github.com/iahmed30004000-wq/zakiai-studio — **PUBLIC**, default branch `main` |
| Old repository | `MKory18/zakiai-studio`, private, obsolete. In this PC's git it is the remote named `mkory18`. **Never push there.** |
| Media buyer repository (separate product) | https://github.com/iahmed30004000-wq/zaki-mediabuyer — PUBLIC. Local copy on the owner's PC: `C:\Users\LOQ\Documents\zaki-mediabuyer`. |
| OMS repository (the COD order system) | Local only: `C:\Users\LOQ\Documents\osm`. **Forbidden** without the owner's exact words «نفّذ العمليات». |
| Live studio | https://studio.zakiai.io (UI version 89 on 27 Oct) |
| Live media buyer | https://mediabuyer.zakiai.io |
| Container image | `ghcr.io/iahmed30004000-wq/zakiai-studio:main` and `:sha-xxxxxxx` (public) |
| Hosting | Coolify at `coolify.zakiai.io`, project «Zakiai Studio», app `zakiai-studio`, port 8000, volumes `/app/library` and `/app/secrets` |
| Deploy | Automatic. Merge to `main` → workflow `.github/workflows/image.yml` builds, smoke-tests (must answer HTTP 200), publishes the image, then POSTs the Coolify deploy hook using the GitHub secret `COOLIFY_TOKEN`. Site updates ~15–20 minutes after the merge. |
| Who has write access | GitHub users `iahmed30004000-wq` (owner of the repo) and `MKory18` (collaborator; this PC's `gh` is logged in as this user). |

**To work from a different account** the owner must (1) invite that account as a collaborator with **write** access to `iahmed30004000-wq/zakiai-studio`, (2) accept the invitation from that account. You cannot do this for him (it is a GitHub setting; HANDOFF_GLM §0 rule 7). If your push is rejected with 403, this is the reason: tell him in one Arabic sentence.

`main` is protected: direct push is rejected; a pull request is required and the check named `image` must pass. **The `image` check does NOT run pytest.** It only proves the Docker image builds and answers. You must run the tests yourself (HANDOFF_GLM §4.2).

### 1.1 Set-up from zero on a new machine (not verified on a second machine; verified on a clean clone, see §3.1)
```
git clone https://github.com/iahmed30004000-wq/zakiai-studio.git
cd zakiai-studio
python -m pip install -r requirements.txt     # Python 3.11
# also needed on PATH: ffmpeg/ffprobe, node 18+ (only for node --check and Remotion)
python -X utf8 -m pytest tests/test_ui_globals.py tests/test_activity.py tests/test_ui_shell.py tests/test_auth_gate.py -q -p no:cacheprovider
```
A fresh clone has **no data**: no `library/`, no `settings.json`, no `models/` weights, no `products/` (all git-ignored, private). Tests do not need them (see §3.1). Never ask the owner to commit them. Use `python run_web.py` and the mock mode `http://127.0.0.1:8000/?mock=1` to see the UI with fake data.

---

## 2. Rules digest (the owner's rules, short; the full text is AGENTS.md §2–3 and HANDOFF_GLM §0, §4, §5, §8)

**Talking to the owner**
- Levantine Arabic only. **Not one English word** in chat, including progress lines. Service names in Arabic letters: جيت هب، كوليفاي، درايف، كروم، طلب دمج. English only inside a command he must copy.
- Short, plain, one concrete example per explanation, no file-name tables.
- Standing order (26 Oct): «بشكل تلقائي بتخلص شغلة شغلة لا تنتقل لشغلة غير لما تخلص الي قبلها بشكل كامل لا تسألني عن اشي اعمل الأفضل و الأنسب دمج تلقائي لجيت هاب و ديبلوي تلقائي لكوليفاي». One task at a time, finish and verify, ship with auto-merge, next task. No small questions.
- «نسخ العمل ع جيت هاب بتضل عامة». Work repositories stay PUBLIC under `iahmed30004000-wq`.
- Ask only for real decisions or things only he can do (secrets, payments, logins, spending credits, licence confirmations). Batch them into ONE message at the end of a work block (§7). First option = your recommendation with the reason, one example, the cost.
- «وقف عند التنفيذ» = write decisions down and wait for «نفّذ».
- Secrets: he types them himself. Never ask in chat, never write them anywhere (code, tests, docs, commits, logs, chat). A password he once pasted in chat is never to be used.

**Git**
- Never push to `main`. Branch → push → pull request → `gh pr merge --auto --merge`. Commit text in Arabic. Exact commands: HANDOFF_GLM §4.
- Before every commit: `git add -A`, read `git status --short`, then `python tools/secret_scan.py` must print «نظيف». Never stage `settings.json`, `.env*`, `library/`, `products/*` (except `_template.json`), `models/*`, `secrets/`, `third_party/*`, `_handoff/`, `.claude/`, media files.
- **The repository is public: no e-mail addresses, no personal data, no account passwords, no tokens, no keys, no customer data** in any file, including this kind of document.

**Product**
- The guided mission (7 scenes, 45–50 s, ordered stations, AI review) must behave exactly as before. Tests that pin its rules stay green and are never edited to pass. New manual behaviour is gated: `_meta.mode == "free"` (script) or `tl["mode"] == "free"` (timeline).
- No silent fallback for voice, lip-sync, music, sound effects, motion. Errors surface. Generated audio lands in the sound library as unapproved.
- Model licences: "no" blocks activation; "conditional"/"unknown" need the owner's confirmation.
- Compatibility names never change: keyring service `vidpattern`, `/api/vidpattern/*`, `vp:*`, `VP-` ids, `VP_*` env vars, `vidpattern_backup_*`, settings key `"CRM"`.
- `VP_SECRETS_KEY` (Coolify env) must never be changed or rotated: the server vault stops opening.

**Engineering**
- UI text, comments, messages: Levantine Arabic. Identifiers: English.
- Each `web/static/*.js` is a closed IIFE exposing one `window.*` name; top-level names collide (guard: `tests/test_ui_globals.py`).
- CSS only via `--vp-*` variables. Any change under `web/static` bumps `?v=` (89 → 90 …) in `index.html`, `login.html` and `privacy.html` to the same number.
- New write route: label in `activity._R` (or `SILENT`), mock JSON in `web/static/mock/`, handler in `app.js` `mockApi()`, tests. (HANDOFF_GLM §5.3.)
- Outgoing calls: user-configured services through `net_allow.py`; fixed external services (Google Drive) through `net_allow.fixed_base`; the OMS client `crm.py`: https (http only for localhost).
- Tests fake external services (`tests/fake_gradio.py`, `fake_openai.py`, `fake_drive.py`, `engine_box.py`); never call real paid APIs. Never `monkeypatch.undo()`.
- Do not touch: `services/openmontage/` (third-party), the OMS repo, Coolify/Google Cloud/GitHub settings. Remotion stays pinned at 4.0.530.

**Windows pitfalls** (HANDOFF_GLM §5.6): `PYTHONIOENCODING=utf-8`; PowerShell scripts with Arabic = UTF-8 **with BOM**; no `&&` in PowerShell 5.1; shell tools eat backslashes (write scripts to a file); restart the local studio after Python edits.

---

## 3. State today

### 3.1 Verified on 27 Oct (by running it)
- `origin/main` = `353e3ef`; local `main` identical; working tree clean.
- Live site answers: `/login.html` → 200; `/api/auth/me` → `{"user":null,"needs_setup":false}` (an owner account exists, a stranger gets nothing).
- Guard tests: 77 passed in ~28 s (`test_ui_globals`, `test_activity`, `test_ui_shell`, `test_auth_gate`).
- **Clean-clone full test run** (fresh `git clone` of the public repo, no `library/`, no `settings.json`): 2512 passed, 13 skipped (details in §3.2).
- OpenAPI: **329 operations on 278 paths, 200 of them write operations** (POST/PUT/PATCH/DELETE). Count them yourself with `python -c "from web.app import app; print(len(app.openapi()['paths']))"` (set `VIDPATTERN_NO_DRIVE=1`).

### 3.2 Clean-clone test result
On 27 Oct a fresh `git clone` of the public repository at `353e3ef` (no `library/`, no `settings.json`, no `products/`, no model weights) was tested with `python -X utf8 -m pytest tests -q -p no:cacheprovider`: **2512 passed, 13 skipped, 0 failed, in 18 min 50 s** (5 warnings: deprecated FastAPI `on_event`, an invalid escape in `tests/test_routes_drive.py:84`). So the suite does not depend on the owner's private data, and this number (2512) is the new baseline; the old figure 2404 (23 Oct) in HANDOFF_GLM is outdated. Caveat: it ran on the same Python installation as the owner's PC (same installed packages), not on a machine with only `requirements.txt` installed; a second-machine run is still to be done by the reviewer. The 13 skips were not itemised: list them with `pytest -rs` and confirm each skip reason is legitimate (missing GPU, missing weights, platform).

### 3.3 Done and live (do not redo; details HANDOFF_GLM §2.2)
Pull requests #1–#13 merged: PR flow and protection; deploy-hook fix; research report; Ollama fix; voice-upload noise filter; pattern-library bundle (53 patterns now on the site); smooth stretch for free-project clips; «الصق رابط إعلان رابح»; search-input fix; beat snapping; text/watermark removal for product photos; privacy page; first handoff. Google Drive export is live and tested (import from Drive = phase 2, NOT built, do not start without «نفّذ»). Media buyer side of the contract exists (§6.1). Research items 1, 2, 3, 4, 6, 7 are built; 5 was rejected; 8, 9, 10 wait for the GPU server.

### 3.4 Not verified anywhere (expect surprises)
Big real weights on a GPU server (Qwen-Image, FLUX, Wan, LTX, Stable Audio); the real ACE-Step and Wan2.2-S2V apps; real paid providers (fal.ai); live Meta Graph from the hosted site (see finding H-1); the extension on real sites (every selector `verified:false`); the hosted site from a second machine.

---

## 4. Architecture map (for the reviewer)

**Size** (tracked files only): 674 files. Python 310 files / 77.5k lines (root modules ≈ 33k); web back end `web/*.py` 24 files / 6.0k lines; front end `web/static/*.js` 33 files / 13.5k lines (vanilla JS, RTL, no build step); tests 136 files / 33.9k lines; engine boxes `services/engine` 2.0k lines; extension 9 JS files / 2.0k lines.

**One process, one container.** `python run_web.py --lan --port 8000` starts FastAPI/uvicorn (`web/app.py`) and, inside it, a background scheduler thread (`scheduler.py`). Data is files + SQLite on the volume `/app/library`. Secrets are in an encrypted vault on `/app/secrets` (unlocked by env `VP_SECRETS_KEY`). No external database, no queue broker, no Redis. The design assumes a single instance (in-process locks and threads, SQLite and JSON files on one volume, `oplock.py` between the server and `agent.py`): do not run two containers on the same volume unless the audit proves it safe.

**Request path** (outermost first): `LocalGuard` (`web/guard.py`: Host allow-list from `VP_ALLOWED_HOSTS`, Origin check on POST/PUT/PATCH/DELETE) → `AuthGate` (`web/auth_gate.py`: every `/api/*` needs the `vp_session` cookie, except the PUBLIC list; the extension token only opens `/api/ext/*` and `/api/studio/<f>/ext/*`; `must_change` users only reach the password routes; sets `accounts.ACTOR`; records every successful write in `activity.py`) → routers `web/routes_*.py` (thin) → modules at the repo root (logic).

**Public (no session) on purpose:** static files and pages; `GET /api/auth/me`; `POST /api/auth/login|setup|logout`; `GET /api/ads/meta/callback`; `GET /api/ext/download`; `/?mock=1` (the app shell with fake data). Setup of the first account only works when no account exists and (client is loopback or `VP_ALLOW_REMOTE_SETUP=1`).

**Modules by area** (open these first):

| Area | Files |
|---|---|
| Accounts, sessions, activity | `accounts.py` (argon2id, sha256 of session token, 5 failed logins/10 min lock per username), `web/auth_gate.py`, `web/routes_auth.py`, `activity.py` |
| Pipeline (guided mission) | `stage0_harvest.py`, `stage1_extract.py`, `stage2_pattern.py`, `stage3_generate.py`, `review_script.py`, `review_loop.py`, `studio_state.py` (stations and gates), `timeline.py`, `shot_prompts.py`, `image_studio.py`, `voice_studio.py`, `generate_voice.py`, `motion.py`, `montage.py`, `montage_advanced.py`, `placements.py`, `performance.py`, `fatigue.py` |
| Free project | `studio_gate.py`, `free_project.py`, `scene_import.py`, `media_io.py`, `free_montage.py`, `voice_upload.py`, `ar_align.py`, `manual_script.py`, `beats.py`, `textclean.py` |
| Patterns | `pattern_store.py` (+ bundle), `pattern_excel.py`, `pattern_dedupe.py`, `pattern_i18n.py`, `translate_patterns.py`, `learn_patterns.py`, `clusters.py`, `taxonomy.py`, `review_queue.py` |
| Models | `model_library.py`, `model_run.py`, `link_std.py`, `link_cmd.py`, `link_engine.py`, `link_app.py`, `net_allow.py`, `gpu_lease.py`, `media_check.py`, `sound_gen.py`, `word_timing.py`; GPU boxes `services/engine/` (`app.py` contract v2) |
| LLM and providers | `llm.py`, `connections.py`, `usage.py` (token/cost accounting and limits), `imagegen.py`, `tts.py`, `stt.py`, `motion_api.py` |
| Secrets and backup | `secrets_store.py`, `settings_io.py`, `backup.py` (Fernet), `migrate_secrets.py` |
| Integrations | `crm.py` (OMS/media buyer client), `queue_worker.py`, `library_sync.py`, `ads_meta.py` (Facebook login, read-only), `gdrive.py`, `drive_sync.py`, `ext_bridge.py`, `ext_config.py`, `ext_tasks.py`, `web/routes_ext.py`, `extension/` (Chrome MV3 0.4.0) |
| Jobs | `web/jobs.py` (SQLite `jobs.db`, subprocess runner), `scheduler.py` (6 tasks: `queue_poll`, `crm_sync`, `fatigue_scan`, `learn_weekly`, `backup_daily`, `library_sync`), `oplock.py` |
| Front end | `web/static/index.html`, `app.js` (largest), `shell.js`, `boot.js`, one JS per screen, `style.css`, `theme.css`, `ornament.css`, `mock/*.json` |

**Data locations** (all under `library/`, git-ignored): `accounts.db`, `activity.db`, `jobs.db`, `production_log.db`, `drive.db` (SQLite); `patterns/`, `scripts/`, `studio/`, `reviews/`, `raw/`, `images/`, `ext/` (files); `model_library.json`, `scheduler_state.json`, `queue_state.json`, `sync_state.json`, `learning_state.json` (JSON state). Settings: `settings.json` (secrets stripped; values live in the vault).

**Tunable numbers** are all in `config.py` (spend caps, thresholds, windows). The reviewer must read that file completely (§5, phase 3).

---

## 5. Audit plan (the developer's job; do this BEFORE adding features)

**Mode: report first, fix second.** Produce `docs/AUDIT_REPORT.md` in English. For each finding: ID, severity (Critical/High/Medium/Low), exact file and line, evidence (command output or a failing test), impact in one concrete example, proposed fix, who decides (agent or owner). Do not fix anything while auditing, except a Critical item that exposes data or money right now (fix it alone, in its own pull request, and tell the owner in one Arabic sentence). After the report: fix in severity order, one pull request per finding, each with a test that fails before and passes after (HANDOFF_GLM §4). Anything that changes a product rule or the "equal staff" decision (H-3) goes to the owner first (§7).

The owner asked for exactly these five checks: **code structure, logic, calculations, permissions, security holes.** Each phase below lists the files, the questions, and the hypotheses already found while preparing this handoff. **A hypothesis is not a verified finding**: prove it or drop it.

### Phase 1: Structure and maintainability
Questions: Is each module's job clear from its docstring? Dead code? Duplicate logic? Circular imports? Which modules are untested?
- Biggest files to read for design quality: `motion.py` (1269 lines), `web/app.py` (1340), `ext_tasks.py` (852), `image_studio.py` (736), `model_library.py` (716), `link_app.py` (700), `voice_upload.py` (680), `stage3_generate.py` (677), `drive_sync.py` (635), `free_project.py` (632), `backup.py` (573), `crm.py` (572).
- `web/app.py` mixes routes and logic (1340 lines) while the other routers are thin: list what should move, but only move with tests and no behaviour change.
- Coverage: run `pytest --cov` (install `pytest-cov` locally, do not add it to `requirements.txt` without a reason) and list modules under 50%.
- Front end: global scope sharing (HANDOFF_GLM §5.2); `app.js` size; every `innerHTML` assignment (feeds Phase 5, XSS).
- Hard-coded Windows assumptions that break on the Linux server (paths, `keyring` Windows backend, `cuda_dlls.py`).
- Stale comments: `Dockerfile` header says "not tested" and `.github/workflows/image.yml` says the repository is private; both are out of date. Fix wording only.

### Phase 2: Logic
For every rule below: read the code, read its test, then try to break it with an unusual input.
1. **Mission state machine:** `studio_state.py` (stations and gates), `review_loop.py` (`SCRIPT_MAX_REVIEW_ROUNDS = 2`), `script_versions.py`. Can a station be skipped, repeated or approved twice? What if two staff approve the same script at the same moment?
2. **Free mode gate:** every place that checks `_meta.mode == "free"` / `tl["mode"] == "free"`. Can a free project reach the OMS launch (must answer 409 `free_project`)? Can mission rules leak into free mode or the reverse?
3. **Script rules:** 7 scenes, 45–50 s (`SCRIPT_SCENES`, `SCRIPT_MIN_SEC`, `SCRIPT_MAX_SEC`), hooks 3..5, forbidden claims (`claims.py`, regex, not model).
4. **Ad naming and linking:** `adname.py` (fifth field = `VP-…` id regex), `placements.py`, `script_for`. A wrong link makes performance feed the wrong pattern. The media buyer has the mirror of this regex in `src/core/studio-contract.ts`: they must stay identical.
5. **Queue worker failure policy** (`queue_worker.py` docstring): permanent vs temporary failure, `QUEUE_MAX_ATTEMPTS`, "never pay twice for a computed draft".
6. **Scheduler:** `scheduler.py` catch-up after downtime, task isolation, lock behaviour (`oplock.py`). The scheduler runs inside the web container now: `queue_poll`, `crm_sync`, `library_sync` will try to reach the OMS once an address is configured. Confirm they do nothing harmful when no OMS address is set.
7. **Licence gating:** `model_library.py` ("no" blocks, "conditional"/"unknown" need confirmation that resets when the licence changes) and `model_library.pick()` fallback to the built-in provider (known, by design, but confirm it never applies to the no-fallback kinds: voice, lip-sync, music, effects, motion).
8. **Approvals to Drive:** `drive_sync.request_ad` never raises and is a no-op when Drive is not connected.

### Phase 3: Calculations (money, time, scores)
Verify each formula against its docstring with a table of hand-computed cases (include zero, negative, huge, missing-data, and rounding cases). Use `decimal`/integer cents where money is summed; flag any float accumulation.

| Number | Where | What to check |
|---|---|---|
| Token cost and daily/monthly limits | `usage.py` (price table in code), `llm.py` | Price table matches the providers' current published prices; unknown model = what? (must not be 0 silently); limit check happens BEFORE the call; concurrent calls cannot overshoot the limit |
| Motion spend cap | `config.MOTION_API_CAP_USD = 15.0` per script, `motion_api.py`, `motion.py` | Counted per script, includes failed/retried calls? What happens exactly at the cap? |
| Image call cap | `config.STUDIO_MAX_IMAGE_CALLS = 80` per video, `image_studio.py` | Counted per call or per image? Retries? |
| Cost per delivered order, fatigue | `fatigue.py` | 7 consecutive calendar days rising (8 points); a missing day breaks the chain; immature days excluded (`PERF_MATURITY_DAYS = 3`); engagement-falling rule (last third ≥5% below first third, negative slope, data for ≥75% of points); `MIN_DELIVERED = 20`. Off-by-one on the window and on dates in the shop's time zone |
| Performance sync | `crm.py`, `performance.py` | Resync lookback 14 days (`CRM_RESYNC_LOOKBACK_DAYS`), initial backfill 60 days; upsert keyed by (ad, day) means no double count; window ≤ 31 days per call (the media buyer rejects more); currency; whitelist of fields |
| Baseline and comparisons | `performance.py`, `MIN_BASELINE_SCRIPTS = 3` | Division by zero, tiny samples, ties |
| Pattern scoring and penalties | `stage3_generate.py` / matching, `FAR_CATEGORY_PENALTY = 25`, `ADJACENT_CATEGORY_PENALTY = 5`, `LIBRARY_QUOTA = 10` | Score range, ordering stability, quota counting (merged variants are not counted) |
| Harvest thresholds | `config.MIN_VIEWS`, `MIN_LIKES`, `MIN_ENGAGEMENT_RATE` (likes ÷ views), `MAX_AGE_DAYS` | Zero views divide; boundary equality |
| Timeline | `timeline.py` | Shot durations sum exactly to the voice duration (ms rounding drift); `STUDIO_MAX_SHOT_SEC = 3.0`; at most 3 shots per scene |
| Voice length gate | `studio_gate.py`, `voice_studio.py` | 45–50 s measured by `ffprobe` on the final file, `STUDIO_VOICE_MAX_ROUNDS = 2` |
| Word timing and alignment | `word_timing.py`, `ar_align.py` | Arabic tokenisation, diacritics, mixed digits |
| Smooth stretch | `motion.fit_duration(..., smooth=True)` | Stretch ≤ 2× (`SMOOTH_STRETCH_MAX`), clip ≥ half the needed length, free projects only |
| Beat snapping | `beats.py` | Never moves scene boundaries; tolerance |
| Face match | `facecheck.py`, `FACE_MATCH_THRESHOLD = 0.363` | Calibration is the owner's step; verify the cosine maths and the `FACE_MIN_PX` rule |
| Backup rotation | `backup.py`, `BACKUP_KEEP = 30`, `BACKUP_ALERT_DAYS = 2` | Never deletes the only good backup |

### Phase 4: Permissions
**Design fact (the owner's decision, not a bug):** there are no roles. All staff accounts are equal; any staff member can create accounts, deactivate others, and reset others' passwords (the last active account cannot be deactivated; nobody can deactivate or reset themselves; everything appears in «النشاط»). The owner chose this («بلا صلاحيات»). Your job: confirm the code does exactly that, then list the consequences in the report and let the owner decide whether to change it (H-3).
Checks:
1. **Complete auth sweep:** with `web.auth_gate.ACTIVE = True`, request every path in `app.openapi()` without a cookie; each must be 401 except the PUBLIC list. Write this as a permanent test if `tests/test_auth_gate.py` does not already do it for all routes.
2. **Extension token scope:** `X-VP-Ext-Token` must open only `/api/ext/*`, `/api/studio/<f>/ext/*`, and `GET /api/scripts`. Try every other route with only the token.
3. **`must_change` users** reach only `/api/auth/me|password|logout`.
4. **Session handling:** token randomness and length, only the sha256 hash is stored, 30-day sliding expiry (`SLIDE_EVERY_SEC = 300`), logout deletes the row, deactivation/reset kills all sessions, password change kills other sessions? Is a session bound to anything (user agent)?
5. **Login throttle:** it is per username (5 fails / 10 min → lock 10 min). Hypothesis H-4: an attacker can lock out a real user at will (no per-IP limit), and distributed guessing across many usernames is not slowed. Also check whether the error text reveals whether a username exists.
6. **Local-only routes (hypothesis H-1, High):** 20 handlers (`web/routes_ads.py` `_local`, `web/routes_ext.py` `_local`, `web/routes_ops.py` `_require_local`, and others found with `grep -rn "_local(request)\|_require_local(request)" web/`) allow only `request.client.host` in `127.0.0.1/::1/localhost`. Behind Coolify's reverse proxy the client address inside the container is the proxy's Docker address, so these routes should answer 403 «بس من نفس الجهاز» for everyone on the live site (Facebook login, extension pairing, reveal-key actions). `uvicorn.run` in `run_web.py` is called without `proxy_headers`/`forwarded_allow_ips`. **Simulated on 27 Oct** (TestClient with a Docker-range client address: 403 on `/api/ads/meta/status`). Confirm on the live site with the owner logged in, then fix with a test. Decide with the owner how "this machine only" should work on a hosted site (e.g. a setting that enables these actions for logged-in staff over https); do not just delete the check.
7. **Setup route:** `POST /api/auth/setup` is allowed when no account exists and the client is loopback or `VP_ALLOW_REMOTE_SETUP=1`. Confirm that after the first account exists it always refuses, including under concurrent calls (race), and that `VP_ALLOW_REMOTE_SETUP` is not set in Coolify.
8. **Activity log integrity:** who can read, who can delete (`activity.db`), is the actor spoofable via `VP_ACTOR` env or a header in background jobs.
9. **Per-resource access:** every route taking `{filename}`, `{file}`, `{stem}`, `{id}`: can a staff member read another product's or script's files by changing the parameter? (Equal staff means they may, but they must not leave the allowed folders: see Phase 5, path traversal.)

### Phase 5: Security
1. **Response headers (hypothesis H-2, Medium):** `curl -I https://studio.zakiai.io/login.html` on 27 Oct showed no `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options` or `Referrer-Policy` (Coolify's proxy may add some; verify from outside). The UI uses inline scripts/styles? Check before adding a CSP so you do not break the site; start with `X-Content-Type-Options`, `X-Frame-Options` (or `frame-ancestors`), `Referrer-Policy`, HSTS.
2. **Cookie `Secure` flag (hypothesis H-2b):** `web/routes_auth.py` sets `secure=request.url.scheme == "https"`. Behind the proxy uvicorn sees `http` unless forwarded headers are trusted, so the live cookie may lack `Secure`. Verify in the browser's cookie view with the owner, then fix together with H-1 (trusted proxy configuration).
3. **CSRF:** cookie is `SameSite=Lax` + `HttpOnly`; unsafe methods are protected by the Origin check in `LocalGuard`. Test: cross-origin POST with and without `Origin`; `Origin: null`; requests with no `Origin` and no `Sec-Fetch-Site` are deliberately allowed (curl, tests): make sure that cannot be used from a browser via a form POST on an older browser.
4. **Path traversal:** every file/folder name that comes from a URL, JSON body, upload name or zip entry. Find the shared sanitiser and check every route uses it. Known zip readers: `pattern_store.import_bundle`, `scene_import.py`, `pattern_excel.py`, `backup.py` restore. Test with `../`, absolute paths, drive letters, backslashes, symlinks, reserved Windows names, zip-slip, zip bombs (size and entry-count limits), duplicate entries.
5. **Uploads:** size caps and type checks in `media_io.py`, `routes_free.py`, `routes_characters.py`, `routes_montage.py`, `routes_patterns.py`, `routes_pipeline.py`, `routes_studio.py`, `routes_model_library.py`. Is the whole body read into memory? Is the content type trusted? Are files served back with a safe `Content-Type` (no HTML/SVG served inline from user uploads = stored XSS)?
6. **Subprocess and argument injection:** `ffmpeg`/`ffprobe`/`node` are called from 25+ modules (list from `grep -ln subprocess`). Confirm no `shell=True` (none found on 27 Oct outside a comment), that user text never lands in a filter graph (`drawtext`, subtitles, concat lists) unescaped, and that file names starting with `-` cannot become options.
7. **SSRF and outbound control:** model URLs go through `net_allow.py` (http, loopback/docker names only, explicit port, no redirects). **But** features that fetch a URL the user pastes (the pattern-library «الصق رابط إعلان رابح», `stage0_harvest.py`/`stage1_extract.py` using yt-dlp, Apify actors, product image import) now run on a server inside the owner's Docker network. Hypothesis H-5: a staff member (or a stolen session) could make the server request internal addresses (cloud metadata, the Coolify panel, other containers). Already seen: `POST /api/extract/link` validates only the `http(s)://` prefix before passing the text to yt-dlp. Check every URL fetch (`/api/extract/link`, `/api/harvest/candidates` + `/approve`, product image import, `stage0_harvest.py`) for scheme/host/IP-range validation (resolve the name, refuse loopback/private/link-local/metadata ranges) and redirect handling.
8. **XSS in the vanilla front end:** list every `innerHTML`, `insertAdjacentHTML`, `outerHTML`, `document.write` in `web/static/*.js`. Data from LLM output, imported Excel/zip, scraped captions and user text must be escaped (look for the project's escape helper) before reaching them. Test with `<img src=x onerror=...>` in a pattern name, product name, hook text, character name, and an Excel cell.
9. **Secrets:** run a secret scanner over the FULL git history, not only the working tree (`gitleaks detect` or `trufflehog git file://.`). History was checked by hand at 19 commits on 26 Oct, now it is larger. Confirm no secret in logs (`last_raw_response.txt` is git-ignored but exists on the owner's PC: check what `llm.py` writes there), in error messages, in `activity.db`, in `production_log.db`, or in backups (`backup.py` strips them). Confirm `secret_scan.py` patterns cover the providers in use.
10. **Vault:** `secrets_store.py` Fernet vault `secrets/vault.enc` keyed from `VP_SECRETS_KEY` (KDF, salt, iterations, file permissions, atomic write, behaviour when the key is wrong or missing: must refuse, never fall back to plain text).
11. **Container:** `Dockerfile` has no `USER`, so on Coolify the app runs as **root** (hypothesis H-6, Medium). `docker-compose.yml` sets a user and `cap_drop`, Coolify does not. Propose a non-root user that can still write `/app/library` and `/app/secrets` on existing volumes (a file-ownership migration risk: coordinate with the owner, test with a copy of the volume, never break the live data).
12. **Dependencies:** `pip install pip-audit && pip-audit -r requirements.txt`; pin versions where loose; check the `npm`/Remotion side in `services/advanced_montage`. Do not upgrade major versions without the full test run.
13. **Public repository exposure:** everything committed is world-readable, including `prompts/` (the business know-how) and `docs/`. List what the owner may not want public and tell him; do not move or delete anything yourself.
14. **GitHub Actions:** `image.yml` runs on `pull_request`; `permissions: contents: read, packages: write`. Confirm a pull request from a fork cannot reach `COOLIFY_TOKEN` or push an image (it publishes only on `push` to `main`; verify the `if:` conditions and that secrets are not exposed to fork PRs).
15. **Abuse and spend:** any logged-in staff member can trigger paid LLM/image/voice/motion calls. Confirm the limits in `usage.py` and the caps in `config.py` actually stop spending across concurrent requests, and that no unauthenticated route can trigger spend.
16. **Extension (`extension/`, MV3 0.4.0):** permissions are `storage, notifications, alarms, downloads, offscreen`; hosts are the studio (localhost) plus gemini/chatgpt/aistudio/flow/elevenlabs/flowmusic. For the hosted site the studio origin must be added; do that only after H-1 is decided. Confirm the pairing token never leaves `chrome.storage` toward third-party hosts, and the extension never reads page content outside its job. `ext_bridge.py` stops completely on captcha/verification pages by design: confirm.

### Phase 6: Resilience and data
- Backup: `backup.py` encrypts with a key held in the vault. The restore path must be tested into a NEW folder (`python backup.py restore-test`). Where do backups go on the server (inside `/app/library`, so inside the same volume that could be lost)? The owner has no off-site copy; Google Drive export covers approved outputs only, not the databases. Report it; propose the simplest fix.
- SQLite: WAL mode? Busy timeouts? Concurrent writers from the scheduler thread, request threads and job subprocesses.
- Files written as JSON: atomic write (temp + rename) everywhere? A crash mid-write must not corrupt `model_library.json`, `scheduler_state.json`, patterns.
- Disk growth: videos and images accumulate in `library/`; what is the retention and the volume size on Coolify?
- Restart behaviour: jobs running when the container restarts; stuck `running` rows in `jobs.db`; the 15–20 minute deploy window drops in-flight jobs (is that visible to the owner?).
- Time: the server runs in UTC; the shop's days are in the shop's time zone. Check every "today", "yesterday", "daily" computation (`crm.py`, `fatigue.py`, `scheduler._daily`, `usage.py`).

### Audit deliverables (the phase is finished only when all exist)
1. `docs/AUDIT_REPORT.md` (findings, ordered by severity, each with evidence).
2. A list of new tests added for each fixed finding.
3. A short Arabic message to the owner: how many findings per severity, which are fixed, which need his decision (§7). No English words.

---

## 6. Integrations with other systems (complete)

For every system: direction, authentication, where configured, contract, status, what is missing, who does it.

### 6.1 Media buyer («الميديا باير», `zaki-mediabuyer`, https://mediabuyer.zakiai.io) — the live partner
- **What it is:** a separate Next.js + Prisma product that manages Meta ads for COD. It owns ad spend and order-based numbers.
- **Direction:** the studio always initiates (pull). The server never calls the studio. No customer personal data in either direction. Studio client: `crm.py`; settings key `"CRM"` (address «عنوان الـ OMS»; the token is stored in the vault under `crm_token`). Contract documents: studio side `CRM_CONTRACT.md`, `CRM_CONTRACT_QUEUE.md`, `contracts/vp-ops.v1.yaml`; media buyer side `docs/STUDIO_DATA_CONTRACT_AR.md` and `src/core/studio-contract.ts`.
- **Endpoints that already exist on the media buyer** (checked in its source on 27 Oct): `GET /api/vidpattern/ad-performance?since&until` (scope `vp:read`; one row per ad per day; ≤ 31 days per call; ad name must carry the `VP-…` id in the fifth `|` field); `GET /api/vidpattern/queue`, `POST /api/vidpattern/queue/{id}/claim`, `POST /api/vidpattern/queue/{id}/result` (scope `vp:launch`); `GET /api/v1/vp/performance`, `/api/v1/vp/creatives`; token management at `/api/studio/tokens` and `/api/studio/links`.
- **Status:** studio side exists and is tested with fakes. **Not yet run end to end against the real service.**
- **Missing, owner-only steps:** in the media buyer: settings → integrations → content studio → «اعمل توكن»; in the studio settings: «عنوان الـ OMS» = `https://mediabuyer.zakiai.io`, paste the token, press «مزامنة الآن». Numbers stay empty until real Meta data and orders exist: expected.
- **Your job:** (1) after the owner links, run one real sync with him present and check the rows land in the right (ad, day); (2) in the audit (§5 Phase 2.4/3) verify the two copies of the `VP-` regex and the date/time-zone handling match; (3) `library_sync.py` pushes the pattern library to the other side: the media buyer's `vp:sync` scope is "proposed" (`x-proposed` in the contract); do not enable until both sides agree. Do not edit the media buyer repository: it is a separate product with its own guard rules. If a change is needed there, write it as a request in the report.

### 6.2 The OMS («العمليات», order system, local `C:\Users\LOQ\Documents\osm`)
- The contract between the studio and the OMS (performance read, launch, queue) was designed by the studio side; **the OMS side was never built** (checked 21 Oct: no `vp:*` scopes, no `/api/vidpattern/*`). Today the media buyer plays the partner role (6.1). Anything that needs the OMS itself (auto-launch, queue from the OMS, per-order numbers) stays disabled.
- **Forbidden** without the owner's exact words «نفّذ العمليات». Specs: `مواصفات_تنفيذ_العمليات.md`, `CRM_CONTRACT.md`, `CRM_CONTRACT_QUEUE.md`. Facts from the OMS team (21 Oct): campaign numbers are computed internally by `GET /api/growth/campaigns` (session only); the external API `/api/v1` has 5 scopes and no campaign read; the link between ad and order is the campaign code `?c=CODE`; open decision for the owner: connect the ad accounts, or let the OMS accept a manual external id.

### 6.3 Meta (Facebook) Marketing API — `ads_meta.py`, read-only
- Scope `ads_read` only. App ID/secret and token in the vault. `state` is HMAC-signed, one-time, 10 minutes. The return URL is always `http://localhost:<port>` (tunnel option was removed on purpose).
- **Consequence for the hosted site (H-1):** the login flow is built for the owner's PC. On `studio.zakiai.io` it cannot complete as designed (local-only check, `localhost` return URL). Options for the owner (present as in §7): (a) keep Facebook login on the PC studio only; (b) redesign the return URL for the https site and drop the local-only check for staff sessions; (c) take ad numbers from the media buyer only (it already owns Meta) and retire `ads_meta` pulling in the studio. Recommendation: (c), the simplest, because the media buyer already has Meta.
- Status: never run against live Meta. A Business-type Meta app needs `config_id`; token paste is accepted as a fallback (same checks). Token lasts ~60 days.

### 6.4 Google Drive — `gdrive.py`, `drive_sync.py`, `web/routes_drive.py`, `web/static/drive.js`
- Device-flow OAuth, scope `drive.file` only (the app sees only files it created), fixed Google hosts via `net_allow.fixed_base`. Queue in `library/drive.db`, worker thread. Approvals call `drive_sync.request_ad(stem)`.
- Google Cloud project `zakiai-512814` (Drive API on, consent screen External, status "In production", client type "TVs and Limited Input devices"). **Owner's console: do not touch.** The public privacy page required for the consent screen is `web/static/privacy.html`.
- Live and verified: folder «Zakiai», «الأنماط» uploaded, pending 0, failed 0. Import from Drive = phase 2, not built.
- Audit: token storage in the vault, refresh handling, what happens when the owner revokes access, queue retry limits, folder-name injection.

### 6.5 Coolify, GitHub Container Registry, GitHub Actions
- Described in §1. Coolify env vars on the app: `VP_ALLOWED_HOSTS`, `VP_SECRETS_DIR`, `VP_SECRETS_KEY` (never change), `HOME=/tmp`, `PYTHONUNBUFFERED`, `PYTHONIOENCODING`. `VP_ALLOW_REMOTE_SETUP` must NOT be set.
- Owner-only: delete the empty old app `studio-old.zakiai.io`; any Coolify setting. You never open Coolify's terminal or settings.

### 6.6 LLM, image, voice, motion providers (all optional, keys typed by the owner in the UI → vault)
- Text/vision: Anthropic (models in `config.py`: `MODEL_ANALYSIS`, `MODEL_MATCH`, `MODEL_WRITER`), DeepSeek, OpenAI-compatible servers, Ollama (`llm.py`, `connections.py`). The current Anthropic key is **rejected (401)**: until the owner replaces it, automatic translation of patterns and character identity cards wait.
- Images: OpenAI, Gemini, BFL, Replicate (`imagegen.py`). Voice: ElevenLabs and others (`tts.py`); speech to text and word timing (`stt.py`, `word_timing.py`). Motion: fal.ai (Kling/Hailuo) optional (`motion_api.py`), local boxes otherwise. Scraping: Apify actors (`config.APIFY_ACTORS`).
- All calls log token/cost into `usage.py`; limits apply. Tests use fakes only.

### 6.7 Model boxes and the GPU server (not deployed yet)
- `services/engine/` (Docker, contract v2: `/jobs`, `/health`, `/models`), `docker-compose.engines.yml`, guide `README_AR_نشر_السيرفر.md`. One box per model family, one model loaded at a time, one shared GPU lock (`gpu_lease.py`, volume `vidpattern_gpu_locks`). Model URLs must be loopback or docker-internal (`net_allow.py`).
- **Open design point:** the live studio runs on the Coolify server, which has no GPU; the allow-list refuses any other host. Decision already made: "everything on one server" (the studio would then run on the GPU server). Do not relax `net_allow.py`; present the options to the owner when the GPU run is scheduled (§7).
- Tested only with tiny real diffusers models on an RTX 4050 (6 GB). Big weights are the owner's downloads. First real run: the owner pastes `docker compose logs`; you fix what shows.

### 6.8 Chrome extension «Zakiai Systems — مولّد الوسائط» (`extension/`, 0.4.0)
- Runs on third-party sites (Gemini, ChatGPT, AI Studio, Flow, ElevenLabs, Flow Music) with the owner's own logged-in accounts; the studio side is `ext_bridge.py` + `web/routes_ext.py`; contract `ext_contract.md`. Pairing token in the vault, header `X-VP-Ext-Token` on every call. It stops completely on any captcha/verification. Using it may violate those sites' terms and risk the owner's accounts: the warning is shown in the UI and stays.
- Every selector is `verified:false`: a calibration session with the owner logged in is required (his step).
- **Careful with folders on the owner's desktop:** `C:\Users\LOQ\Desktop\مشاريع برمجة\Zakiai-extension` is this extension; `…\New folder (2)` is a DIFFERENT extension (دفتر). Open the target's `manifest.json` and check the name before copying anything (HANDOFF_GLM §8).

### 6.9 Local models on the owner's PC (`models/`, git-ignored)
BiRefNet, Real-ESRGAN x4plus, face model, faster-whisper-large-v3, whisper-turbo-ar-ct2, piper-ar, stable-audio-open-1.0. Scripts `tools/local_models/*.bat` are launchers for same-name `.ps1` files. Never run the download scripts yourself (0.8–8 GB each).

---

## 7. What is left (complete list, in this order)

**Order of work:** audit first (§5), then fixes by severity, then the engineering backlog, one pull request at a time. Between items follow the standing order: no small questions.

### 7.1 Engineering
1. **Audit** (§5) and `docs/AUDIT_REPORT.md`.
2. **Fix findings**, Critical → High → Medium → Low, one pull request each. Expected early candidates: H-1 (local-only routes behind the proxy + trusted proxy headers), H-2 (security headers, cookie `Secure`), H-6 (non-root container), H-5 (SSRF on pasted links), H-4 (login throttle per IP). Each needs the owner's choice only where it changes behaviour he sees (H-1 options, H-3 roles).
3. **Move products, scripts and images from the PC to the site:** only when the owner says so (he answered «مش هلأ» on 26 Oct). Recipe: HANDOFF_GLM §7.4 (copy the pattern bundle design and its safety rules exactly; he does the clicking; never upload his data yourself).
4. **First real GPU server run** (§6.7).
5. **Media buyer link run** after the owner links (§6.1).
6. **OMS side**: only on «نفّذ العمليات».
7. **Lowest priority ideas** (HANDOFF_GLM §3.2): WanGP; video upscaling and auto-upscale after choosing; transitions and advanced montage for the free project; HEIC photos; converting a free project into a launchable mission; import from Drive (phase 2, needs «نفّذ»); research items 8–10 (need the GPU server).
8. **Pictures:** 13 art slots were sent as prompts on 22–23 Oct and never came back. When the owner says «الصور جاهزة», follow `docs/agent_skills/zakiai-studio-art-prompts/SKILL.md` (HANDOFF_GLM §9).

### 7.2 Owner-only (list for him once, do not nag)
Delete the empty Coolify app `studio-old.zakiai.io`; confirm the Piper and Stable Audio licences in the factory screen; restart Chrome (stale "Not secure" badge); create the media-buyer token and press «مزامنة الآن»; replace the rejected Anthropic key; optional fal.ai key; install the extension 0.4.0 and run the calibration session; calibrate the face threshold (0.363) on real characters; invite the new GitHub account as collaborator (§1); download model weights for the GPU server.

### 7.3 Decisions to put to the owner (ONE batched message in Arabic, after the audit report)
Use his decision format: one sentence question, your recommendation first (reason, one example, cost), then the alternatives.
1. **Roles (H-3):** keep "all staff equal" (simple; any member can reset anyone) or add an owner-only area for accounts, spend limits and settings. Recommendation: owner-only for accounts and spend limits, everything else equal. Example: today a new employee could reset the owner's password.
2. **Hosted site and "this machine only" actions (H-1):** options in §6.3.
3. **Off-site backup:** where the encrypted backups should also go (the simplest: a second folder in his Drive, encrypted).
4. **What in the public repository he does not want public** (`prompts/`).

---

## 8. Stop conditions and the report you send

Stop and tell the owner (Arabic, one sentence, no English) when: a change would touch a forbidden area (§2), a secret would be needed, a test that pins a mission rule fails and the only "fix" is editing the test, push is rejected for permissions (§1), the live site breaks after a deploy (check `https://studio.zakiai.io/login.html` returns 200 and the `?v=` number matches; if not, report it first and do not push further changes until it is understood).

**Never do:** push to `main`; disable protection or merge with admin rights; commit private data; write or ask for a secret; edit a mission-rule test to make it pass; add a silent provider fallback; change `VP_SECRETS_KEY`; touch Coolify/Google Cloud/GitHub settings, the OMS repo, the media buyer repo or `services/openmontage/`; write English to the owner; say "done" without test output.

**Before you say anything is done**, all of these must be true and listed in your report: targeted tests green (give the numbers); guard tests green; full suite green when shared Python changed (≈16 min, give the numbers); `node --check` on changed JS; `?v=` bumped identically in the three pages when static files changed; `python tools/secret_scan.py` printed «نظيف»; `git status --short` shows no private path; the pull request merged and the `image` check green; for UI changes the live page shows the new `?v=`.

**Report to the owner (Arabic, this template):**
```
خلصت: <شو تغيّر بجملة، مع مثال واحد>.
انفحص: <أي اختبارات نجحت بالأرقام، وشو جرّبت فعلياً>.
ما انفحص: <بصراحة>.
على الموقع: <انرفع بطلب الدمج رقم N، وبيوصل خلال ربع ساعة تقريباً> أو <لسا ما انرفع وليش>.
عليك (إذا في): <خطوة وحدة واضحة>.
```

---

## 9. Hypotheses found while preparing this handoff (all UNVERIFIED unless marked)

| ID | Claim | Evidence so far | Severity if true |
|---|---|---|---|
| H-1 | 20 "this machine only" routes answer 403 to everyone on the hosted site (client address behind the proxy is not loopback); Facebook login cannot complete on the site | Code read: `request.client.host` checks in `routes_ads.py`, `routes_ext.py`, `routes_ops.py`; `uvicorn.run` has no proxy settings. **Simulated on 27 Oct** with FastAPI `TestClient(app, client=("172.18.0.5", 5000))`: `GET /api/ads/meta/status` answered 403 «بس من نفس الجهاز» (200 from 127.0.0.1). The only unproven part is what address Coolify's proxy really presents; check it on the live site with the owner logged in | High (features silently unavailable) |
| H-2 | Live responses carry none of the standard security headers; session cookie may lack `Secure` behind the proxy | `curl -I` on 27 Oct showed none of them; cookie code uses `request.url.scheme` | Medium |
| H-3 | No roles: any staff can reset any other account's password, including the owner's | Documented in `accounts.py`; owner's decision | Owner decides |
| H-4 | Login lock is per username only: easy to lock a user out; no per-IP slowing | Code read in `accounts.py` | Medium |
| H-5 | Features that fetch pasted URLs may reach internal addresses from the server | Code read: `POST /api/extract/link` (`web/app.py`, `extract_link`) only checks that the text starts with `http://` or `https://`, then runs `stage1_extract.py <url>` which hands it to yt-dlp (its generic extractor fetches arbitrary pages). The «الصق رابط إعلان رابح» button goes through `/api/harvest/candidates` then `/approve` (not read yet). No host, IP-range or redirect validation seen. Not yet tested | High if confirmed |
| H-6 | Container runs as root on Coolify (no `USER` in `Dockerfile`) | `Dockerfile` read on 27 Oct | Medium |
| H-7 | Backups live on the same volume as the data; no off-site copy of the databases | Docstring + volume layout | Medium |
| H-8 | `web/app.py` (1340 lines) holds logic that other routers keep in modules | Size and structure | Low |
