# Handoff to GLM: Zakiai content studio (27 Oct 2026)

Read this file completely before you touch anything. It assumes you know nothing about this project. Follow it literally. When this file and your own judgement disagree, this file wins. When this file and `AGENTS.md` disagree, `AGENTS.md` section 2 and 3 win (they are the owner's rules), and you tell the owner about the conflict.

Arabic words in «guillemets» are the exact labels the owner sees on screen or his exact words. Keep them exactly as written: never translate them, never retype them from memory, copy them from the source file.

Order of reading:
1. `AGENTS.md` (rules, repo map). Mandatory.
2. This file (state, procedures, checklists). Mandatory.
3. `docs/agent_skills/zakiai-studio-art-prompts/SKILL.md`, only when a task needs a picture.
4. `docs/WORK_LOG_AR.md`, `docs/PROJECT_STATE_AR.md`, `docs/RESEARCH_FEATURES_AR.md`, `docs/PLAN_google_drive_AR.md`, only when you need history on one area.

---

## 0. The ten commandments (read again before every task)

1. **Speak to the owner in Levantine Arabic only.** Not one English word in chat, not even in short progress lines. Write service names in Arabic letters: جيت هب، كوليفاي، درايف، كروم، طلب دمج. English is allowed only inside a command he must copy, and that should be rare.
2. **Never push to `main`.** It is protected and will reject you. Always: new branch → pull request → auto-merge (section 4).
3. **Run the tests yourself before every pull request.** The GitHub check (`image`) does NOT run pytest. It only builds the Docker image and checks that it answers HTTP 200. A broken feature with a green check will go live on the public site within ~15 minutes.
4. **Run `python tools/secret_scan.py` before every commit.** It must print a line that starts with «نظيف». The repository is PUBLIC. A leaked key is leaked forever.
5. **Never write a secret anywhere.** No keys, tokens, passwords, e-mail addresses or personal data in code, tests, commits, docs or chat. Refer to secrets by NAME only. The owner types secrets himself, in the UI or in Coolify, never in chat.
6. **Never stage ignored/private paths:** `settings.json`, `.env*`, `library/`, `products/*` (except `products/_template.json`), `models/*`, `secrets/`, `third_party/*`, `_handoff/`, media files. If `git status` shows any of them, stop and unstage.
7. **Do not touch:** `services/openmontage/` (third-party, read-only), the OMS repository (needs the owner's exact words «نفّذ العمليات»), the media buyer repository (`C:\Users\LOQ\Documents\zaki-mediabuyer`, a separate product), Coolify settings, Google Cloud settings, GitHub repository settings.
8. **The guided mission must behave exactly as before.** Any new manual behaviour goes behind the free-project gate (`_meta.mode == "free"` for scripts, `tl["mode"] == "free"` for timelines). Tests that pin mission rules must stay green; never edit those tests to make your change pass.
9. **No silent fallbacks** for voice, lip-sync, music, sound effects and motion. If the chosen model fails, the error is shown. Generated audio lands in the sound library as unapproved.
10. **Never claim something works unless you ran it.** In every report, list what you verified (which tests, which real run) and what you did not.

---

## 1. Who the owner is and how to work with him

- Ahmad («Zaki AI»), a business owner (cash-on-delivery stores). Not a programmer. Speaks Levantine Arabic.
- He delegates decisions: «القرارات عليّ، والأسهل». Pick the simplest, smoothest option yourself and say in one line what you picked.
- **Standing order (26 Oct), his words:** «بشكل تلقائي بتخلص شغلة شغلة لا تنتقل لشغلة غير لما تخلص الي قبلها بشكل كامل لا تسألني عن اشي اعمل الأفضل و الأنسب دمج تلقائي لجيت هاب و ديبلوي تلقائي لكوليفاي».
  - What this means:
    - Do one task at a time.
    - Finish it end to end and verify it.
    - Ship it with auto-merge.
    - Then start the next task.
  - Do not ask small questions.
- **Also (26 Oct):** «نسخ العمل ع جيت هاب بتضل عامة». Never make a work repository private.
- **Ask him only for** real decisions or things only he can do: secrets, payments, logins, spending credits, licence confirmations.
  - When you must ask, use one sentence.
  - Give your recommended option first, with its reason, one concrete example and its cost.
  - Then give the other options.
- If he says «وقف عند التنفيذ»: write the decisions down and wait until he writes «نفّذ».
- **Reports:** short, plain, one concrete example per explanation, and no file-name tables unless he must open the file.
- **Pictures:** he generates them in ChatGPT; you write the prompts. All prompts of one request go into ONE Word (.docx) file (his standing rule). See section 9.

---

## 2. What exists today (state on 27 Oct 2026)

### 2.1 Live system
- **Site:** https://studio.zakiai.io, UI version 89.
- **Repository:** `iahmed30004000-wq/zakiai-studio`, which is PUBLIC.
  - The old `MKory18/zakiai-studio` is private and obsolete. It is the remote named `mkory18`; never push there.
- **Image:** `ghcr.io/iahmed30004000-wq/zakiai-studio:main` and `:sha-xxxxxxx`, both public.
- **Coolify:** app `zakiai-studio`, project «Zakiai Studio». Every merge to `main` deploys automatically (section 4.3).
- **First owner account:** created from the container terminal and verified to log in. The login form refuses account creation from outside the machine, by design.

### 2.2 Done between 23 and 26 Oct (all merged and live)

| PR | What |
|---|---|
| (direct, before protection) | Work log `docs/WORK_LOG_AR.md/.docx`. `tools/local_models/*.bat` are now tiny launchers for `.ps1` files (UTF-8 with BOM). UI restructure («＋ إعلان جديد» chooser, «إعلاناتي» in Home, factory readiness list, guide page, neon theme with real photos). Light local models (Piper, Stable Audio command, Whisper turbo-ar by name). GHCR image workflow. Google Drive export (`437871e`). Coolify deploy hook. |
| #1 | Pull-request flow, `main` protected, check `image` on every PR. |
| #2 | Coolify deploy call is `POST` (GET returned 405). |
| #3 | Research report `docs/RESEARCH_FEATURES_AR.md` (top 10 ideas). |
| #4 | Ollama: `reasoning_effort: "none"` in `llm._call_openai` (qwen3.5 returned empty replies). Model list = the models on the owner's PC. No task was switched to local AI: Levantine quality of 4B/7B models was weak. |
| #5 | `voice_upload.py`: every uploaded recording goes through `highpass=f=70,afftdn=nr=12:nf=-30:tn=1` (`VOICE_CLEAN=True`). Noise −6.4 dB, duration unchanged. |
| #6 | Pattern library bundle: `pattern_store.export_bundle/import_bundle`, `GET /api/pattern-lib/bundle.zip`, `POST /api/pattern-lib/bundle`, button «انقل المكتبة». The 53 local patterns are now on the site. |
| #7 | `motion.fit_duration(..., smooth=True)`: free projects only. A clip of at least half the needed length is stretched with `minterpolate` (≤ 2×, `SMOOTH_STRETCH_MAX`). The guided mission is unchanged. |
| #8 | Button «الصق رابط إعلان رابح» in the pattern library (`hvAdLinkOpen` in `app.js`): adds the candidate and approves it. |
| #9 | `autocomplete="off"` on every `type="search"` input. Chrome was filling the user name into the pattern search, so the library showed «0 من 53». Guarded by a test. |
| #10 | `beats.py` (numpy only): beat detection plus snapping shot boundaries in the free montage (checkbox under the music, `ambience.beat_snap`). Scene boundaries never move. |
| #11 | `textclean.py` (EasyOCR + `cv2.inpaint`): option «شيل الكتابة والعلامة المائية» when uploading product photos (`?clean=1`). Text that matches the product label or box text is kept. |
| #12 | Public bilingual privacy page `web/static/privacy.html` (needed to publish the Google app). |
| #13 | This handoff and `AGENTS.md` update. |

### 2.3 Google Drive
- Connected on the site to the owner's Google account.
- Approved station outputs are uploaded to a «Zakiai» folder, one sub-folder per ad.
- Verified: folder created, «الأنماط» uploaded, pending 0, failed 0.
- **Google Cloud side** (owner's, do not touch):
  - Project `zakiai-512814`, Drive API on.
  - Consent screen External, status "In production".
  - Client type "TVs and Limited Input devices", scope `drive.file`, device flow.
- **Code:**
  - `gdrive.py`, `drive_sync.py`, `web/routes_drive.py`, `web/static/drive.js`.
  - Fake: `tests/fake_drive.py`.
  - Tests run with `VIDPATTERN_NO_DRIVE=1` (set in conftest).
  - Approvals call `drive_sync.request_ad(stem)`. It never raises, and does nothing unless Drive is connected.
- **Import from Drive (phase 2) is NOT built.** Do not start it without «نفّذ».

### 2.4 Models on the owner's PC (`models/`, git-ignored, never commit)
- BiRefNet (background removal).
- Real-ESRGAN x4plus (upscale).
- face (character face match).
- faster-whisper-large-v3 and whisper-turbo-ar-ct2 (speech to text with word timing).
- piper-ar (Arabic voice on CPU).
- stable-audio-open-1.0 (music and sound effects, 5 GB).

The PC GPU is an RTX 4050 with 6 GB. Never download big weights to the PC; they belong on the GPU server.

### 2.5 Media buyer link
- The media buyer (separate product, https://mediabuyer.zakiai.io) already has the studio-contract endpoints and token. The studio side already exists: `crm.py`, settings key `"CRM"`, https allowed.
- Only the owner's linking steps are missing (section 3). Do not change `crm.py` for this.

---

## 3. What is left

### 3.1 Owner-only items (you cannot do these; list them for him when relevant, do not nag)
1. **Old Coolify app:** delete the empty `studio-old.zakiai.io` app. It needs his Coolify password and is harmless meanwhile.
2. **Licences:** confirm the Piper and Stable Audio licences in the factory screen (button next to each model). The licence rules are in `AGENTS.md` section 3.
3. **Chrome:** restart it fully, to clear an old "Not secure" certificate exception. The certificate is fine.
4. **Link studio ↔ media buyer:**
   - In the media buyer: settings ← integrations ← content studio ← «اعمل توكن».
   - In the studio settings: put `https://mediabuyer.zakiai.io` as «عنوان الـ OMS», paste the token, press «مزامنة الآن».
   - The numbers stay empty until real Meta data and orders exist. That is expected, not a bug.
5. **Anthropic key:** replace the rejected key (it answered 401). Until then, automatic translation of patterns and character identity cards are waiting.
6. **Optional:** fal.ai key for Kling/Hailuo.
7. **Extension:** install extension 0.4.0, then run a calibration session on the real sites with the owner logged in. Every selector is `verified:false`.
8. **Face match:** calibrate the threshold (0.363) on real characters.

### 3.2 Engineering work, in this order (one at a time, each finished before the next)
1. **Move products, scripts and images from the PC to the site.**
   - **Only when the owner asks.** He said «مش هلأ» on 26 Oct.
   - Recipe: copy the pattern bundle design exactly (section 7.4).
2. **First real run on the GPU server**, with `README_AR_نشر_السيرفر.md`. Fix what the first run shows; the owner pastes `docker compose logs`.
   - **Open design point:** the site runs on the Coolify server, and the engine URL allow-list accepts only loopback or docker-internal names (`net_allow.py`, `motion.validate_engine_url`).
   - So the studio must run on the GPU server (decision already made: «everything on one server»), or a new allowed host is needed.
   - Do not change `net_allow.py` rules without the owner's decision. Present the two options per section 1.
   - Research items 8, 9 and 10 also wait for this server.
3. **OMS side:** not built. Forbidden without «نفّذ العمليات». Specs: `مواصفات_تنفيذ_العمليات.md`, `CRM_CONTRACT.md`, `CRM_CONTRACT_QUEUE.md`.
4. **Lowest priority ideas:**
   - WanGP.
   - Video upscaling.
   - Transitions and advanced montage for the free project.
   - HEIC photos.
   - Converting a free project to a launchable mission.

### 3.3 Things NOT to redo
- Research items 1, 2, 3, 4, 6 and 7 are built.
- Item 5 (voice conversion) was rejected by the owner.
- ComfyUI is rejected.
- The theme decisions are made: the neon theme is back by the owner's wish, and the Islamic «نجمة وطريق» look is the default.

---

## 4. How to ship a change (exact procedure)

Run everything from the project root `C:\Users\LOQ\Pictures\المشروع`. Use Git Bash or PowerShell. Under PowerShell 5.1 do not use `&&`; run the commands one by one.

### 4.1 Start a task
```
git checkout main
git -c credential.helper= -c "credential.helper=!gh auth git-credential" pull --ff-only origin main
git checkout -b <short-english-branch-name>
```
- `git status` must be clean before you branch. If it is not, find out whose changes they are. Never discard work you did not create.
- The GitHub CLI on this PC is logged in as `MKory18`, which is a collaborator on `iahmed30004000-wq/zakiai-studio`. That is expected.

### 4.2 Before the pull request (all must pass; paste the results in your report)
1. **Targeted tests** for the area you touched:
   ```
   python -X utf8 -m pytest tests/test_<area>.py -q -p no:cacheprovider
   ```
2. **Guard tests** (about 30 s, measured on 27 Oct: 77 passed):
   ```
   python -X utf8 -m pytest tests/test_ui_globals.py tests/test_activity.py tests/test_ui_shell.py tests/test_auth_gate.py -q -p no:cacheprovider
   ```
3. **Full suite**, when you touched Python shared by many areas: `python -X utf8 -m pytest tests -q -p no:cacheprovider`. It takes about 16 minutes. The last full green run was 2404 passed (23 Oct).
4. **Each changed JS file:** `node --check web/static/<file>.js`.
5. **Secrets:** `git add -A`, then `git status --short` (read every line; no private paths, rule 6), then `python tools/secret_scan.py`. It must print «نظيف…».
6. **If you changed anything under `web/static`:** open the page in mock mode (`python run_web.py`, then http://127.0.0.1:8000/?mock=1) and look at the screen you changed.

### 4.3 Commit, pull request, auto-merge
```
git commit -m "<Arabic one-line summary>" -m "<Arabic body: what and why>"
git -c credential.helper= -c "credential.helper=!gh auth git-credential" push -u origin <branch>
gh pr create --repo iahmed30004000-wq/zakiai-studio --base main --head <branch> --title "<Arabic title>" --body "<Arabic description: what, why, which tests ran>"
gh pr merge --repo iahmed30004000-wq/zakiai-studio <branch> --auto --merge
```
- **Commit messages and PR text:** in Arabic, matching `git log`.
- **The check `image`:**
  - It takes about 14 minutes.
  - On a PR it only builds and smoke-tests.
  - After the merge to `main`, it builds again, publishes the image, and POSTs the Coolify deploy hook.
  - The site updates about 15–20 minutes after the merge.
- **Follow it:** `gh pr checks <n> --repo iahmed30004000-wq/zakiai-studio` and `gh run list --repo iahmed30004000-wq/zakiai-studio --limit 3`.
- **If `image` fails:** read the log with `gh run view <id> --log-failed`, fix it on the same branch, and push again. Auto-merge stays on. Never disable branch protection, and never merge with admin rights.
- **After it merges:** `git checkout main`, then pull with the same credential command as in 4.1.
- **Verify live:** open https://studio.zakiai.io/login.html and confirm the `?v=` in the page source is your new number (for UI changes). For a new endpoint, call it as a logged-in user only if the owner is there; otherwise say it was not checked live.

### 4.4 After Python changes on the PC
The owner's local studio must be restarted to pick up Python edits: close it, then run «تشغيل الاستوديو.bat». Tell him in one Arabic line if he has it open.

---

## 5. Engineering rules with the exact files to touch

### 5.1 Language
- UI text, code comments, error messages: Levantine Arabic.
- Identifiers: English.
- Never rename the compatibility names: keyring service `vidpattern`, `/api/vidpattern/*`, `vp:*`, `VP-` ids, `VP_*` env vars, `vidpattern_backup_*`, settings key `"CRM"`.

### 5.2 Front end (`web/static`, vanilla JS, no build step, RTL)
- There are no modules. Every top-level `const`, `let` or `function` name in any `web/static/*.js` file shares ONE global scope with all other files.
  - `tests/test_ui_globals.py` fails on a collision.
  - Give new top-level names a file prefix, the way existing files do (`pe…` in `patedit.js`, `pr…` in `productref.js`, `hv…` in `app.js`).
  - Prefer keeping helpers inside an existing function.
- `patedit.js` may only call `/api/pattern-lib…`. A test enforces it. Code that calls other APIs from the pattern screen goes in `app.js` (this is why `hvAdLinkOpen` lives there).
- **CSS:** only through `--vp-*` variables. No raw colours.
- **Search inputs:** `<input type="search" autocomplete="off">`. A test enforces it.
- **Cache version:** any change under `web/static` means bumping `?v=` in ALL THREE pages to the same new number (now 89 → next 90): `index.html`, `login.html`, `privacy.html`.
  - Command (Git Bash): `sed -i 's/?v=89/?v=90/g' web/static/index.html web/static/login.html web/static/privacy.html`
  - Verify: `grep -o '?v=[0-9]*' web/static/index.html web/static/login.html web/static/privacy.html | sort | uniq -c`. Every line must show the new number and no line the old one.
- **Upload URL in `productref.js`:** it must keep the literal `?auto=1` first and `&clean=1` after it. A test reads that literal.

### 5.3 Adding a new API endpoint: all five places, every time
Model it on PR #6 (`git show 4b22f04`):
1. **The route:** in the right `web/routes_*.py`. Keep the handler thin; the logic lives in a module at the root (for example `pattern_store.py`). Wrap errors the way the file already does (`_guard(...)`).
2. **Activity label** (write routes only: POST, PUT, PATCH, DELETE):
   - Add one tuple to `_R` in `activity.py`, next to its siblings, shaped like `("POST", r"/api/pattern-lib/bundle", "create", "استيراد مكتبة أنماط من ملف مضغوط")`.
   - Or put it in `SILENT` if it is a background poll.
   - `tests/test_activity.py` compares `_R` with the OpenAPI paths and fails if you forget.
3. **Mock file:** `web/static/mock/<name>.json`, a realistic Arabic example response.
4. **Mock handler** in `mockApi()` in `web/static/app.js`:
   - For example: `if (path === "/api/pattern-lib/bundle" && method === "POST") return mockFile("pattern_bundle_import");`
   - Downloads return `NOMOCK`.
   - Order matters: put specific paths before generic regex paths.
5. **Tests:** `tests/test_<feature>.py`.
   - Use the existing fixtures and fakes (`tests/fake_openai.py`, `fake_gradio.py`, `fake_drive.py`, `engine_box.py`).
   - Never call a real paid API or a real Google or Meta endpoint.
   - Never use `monkeypatch.undo()`.

Then bump `?v=` if any static file changed (5.2).

### 5.4 Outgoing network calls
- **User-configured services** (model boxes, Gradio apps, OpenAI-compatible servers) go through `net_allow.py`:
  - http only.
  - Loopback or docker-internal names only.
  - Explicit port.
  - No redirects.
  - No environment proxies.
- **Fixed external services written in code** (Google Drive) use `net_allow.fixed_base`: https to listed hosts only.
- **The OMS / media buyer client** is `crm.py`: https required, http allowed only for localhost.

Never widen any of these rules on your own.

### 5.5 Models
- **Licences:** "no" blocks activation. "conditional" or "unknown" need the owner's confirmation, which resets when the licence changes.
- **Fallback:** `model_library.pick()` falls back to the built-in provider when a task's default model is disabled or deleted. This is known and by design.
- **Remotion:** pinned to 4.0.530. Version 5 has a different licence.

### 5.6 Windows pitfalls on this PC
- Print Arabic from Python with `PYTHONIOENCODING=utf-8` (the console is cp1252 otherwise).
- PowerShell 5.1 scripts that contain Arabic must be saved as UTF-8 **with BOM**.
  - Do not use `2>&1` on native commands in PowerShell.
  - No `&&` in PowerShell 5.1.
- Some shell tools eat backslashes in inline commands and heredocs. Write any script that contains regex or backslashes to a file first, then run the file.
- `grep -r` over the whole project is slow (`library/`, `node_modules`). Search a specific folder.
- Docker commands from Git Bash mangle paths: prefix them with `MSYS_NO_PATHCONV=1`, or run them from PowerShell.
- **Hugging Face downloads:**
  - On this PC they fail on SSL unless `from pip._vendor import truststore; truststore.inject_into_ssl()` runs first.
  - Long `.cache` paths break `snapshot_download`; use a short folder.
- **Screenshots:** headless Edge with `python tools/edge_shot.py jobs.json` (see its docstring).

---

## 6. Running things

| Goal | Command |
|---|---|
| Run the studio locally | `python run_web.py` → http://127.0.0.1:8000 (or the owner double-clicks «تشغيل الاستوديو.bat») |
| UI with fake data | http://127.0.0.1:8000/?mock=1 |
| Create a staff account (on the machine itself, or in the Coolify container terminal, which only the owner opens) | `python accounts.py create <username> <display name…>` |
| Static check of the engine compose file | `ENGINE_TOKEN=x docker compose -f docker-compose.engines.yml config` |
| Local model scripts (owner double-clicks) | `tools/local_models/*.bat` → each runs the `.ps1` with the same name |

Never run the local model download scripts yourself: they download 0.8–8 GB each. Never run a generation on the owner's paid accounts: he presses «جرّب» himself.

---

## 7. Recipes for the likely next tasks

### 7.1 A small UI fix
1. Branch.
2. Edit the JS/HTML/CSS.
3. Run `node --check` on the file.
4. Bump `?v=` in the three pages.
5. Run the guard tests and the `tests/test_ui_<area>.py` tests.
6. Look at the page in `?mock=1`.
7. Secret scan, then PR with auto-merge.

### 7.2 A new backend feature
1. Write the module at the root.
2. Add the route, `_R` label, mock file, mock handler and tests (5.3).
3. Run the targeted tests, then the guard tests, then the full suite.
4. Ship as in 4.3.
5. If the feature touches the mission, prove the mission tests are untouched and green.

### 7.3 A feature that needs a picture
Follow `docs/agent_skills/zakiai-studio-art-prompts/SKILL.md` (section 9). Never block the feature on the picture: every slot has a drawn fallback in code.

### 7.4 Moving products, scripts and images to the site (only on the owner's request)
1. Read `pattern_store.export_bundle` and `import_bundle` and `tests/test_pattern_bundle.py` first. Copy their safety rules exactly:
   - Size limit.
   - Reject absolute paths, `..`, and unknown names.
   - Add only what is missing.
   - Never overwrite existing or archived items.
   - Report `added / skipped / bad`.
2. Products live in `products/` (private, git-ignored), and reference images in the product-ref store (`product_ref.py`). The bundle carries data between two studios at run time. It is NEVER committed.
3. Add the routes (`GET …/bundle.zip`, `POST …/bundle`), the `_R` label, the mock, the button next to the existing import button, and tests including a malicious zip.
4. Ship it.
5. Then tell the owner in Arabic, in 3 steps:
   - Download the file from the PC studio.
   - Upload it on the site.
   - Check the count.

   He does the clicking. You never upload his data yourself.

---

## 8. What must never happen (each one is a real past risk)

- Pushing a private file to the public repository.
- Pushing directly to `main`, disabling protection, or merging with admin rights.
- Editing a mission-rule test so that a change passes.
- Adding a silent fallback from one voice, music or motion provider to another.
- Changing `VP_SECRETS_KEY` or advising the owner to change it. The server vault would stop opening.
- Rotating or editing anything in Google Cloud, Coolify or GitHub settings.
- Copying the studio extension over the wrong folder.
  - The owner reorganised his desktop. Checked on 27 Oct:
    - `C:\Users\LOQ\Desktop\مشاريع برمجة\Zakiai-extension` = the studio extension. Its `manifest.json` name is "Zakiai Systems — مولّد الوسائط".
    - `C:\Users\LOQ\Desktop\مشاريع برمجة\New folder (2)` = a DIFFERENT extension (دفتر). Never copy there.
  - Before copying `extension/` anywhere, open the target's `manifest.json` and confirm the name. The folders may move again.
- Writing English to the owner.
- Saying "done" without the test output.

---

## 9. Skills (instructions packaged for agents)

Claude used local "skills" on this PC. The one that belongs to this repository is copied into the repo so you can follow it:

- `docs/agent_skills/zakiai-studio-art-prompts/`
  - `SKILL.md`: when a studio screen needs a picture. It covers:
    - The slots.
    - The palette (navy `#0d2140`, gold `#f5c542`, turquoise `#1fd1a5`, …).
    - The rule "no text, no faces, no brands in images".
    - What is never asked from GPT (ornaments are SVG in code; the neon theme uses real photos with `credits.json`).
  - `references/zakiai-art.json`: every prompt sent so far. Add new ones with `"pack": "new"`.
  - `scripts/build_docx.py`: builds the ONE Word file the owner wants (`python docs/agent_skills/zakiai-studio-art-prompts/scripts/build_docx.py --pack new`). It writes `برومبتات_رسومات_الموقع_الجديدة.docx` to the project root and uses the project's `refprompts.build_docx`. Set `ZAKIAI_PROJECT` if the project path differs.
  - **Open state:**
    - Packs of 22 Oct and 23 Oct (13 pictures: `login-bg`, `empty-patterns/hooks/moves/activity`, `new-guided/free/quick`, `guide-cover`, `guide-help`, `mission-done`, `factory-ready`, `not-found`) were sent and never came back.
    - When the owner says «الصور جاهزة», do the following:
      - Check each image: no letters, no faces, real transparency.
      - Copy each one to `web/static/img/art/`.
      - Add the CSS line in `ornament.css` for a new empty state.
      - Bump `?v=`.
      - Ship.

Other skills on this PC belong to other repositories. Do not apply them here:
- `zaki-mediabuyer-guard`: media buyer.
- `crm-oms-guard`: OMS, forbidden without «نفّذ العمليات».
- `zaki-image-prompts`: System 7 and OMS art.
- `daftar-art-prompts`, `falak-art-prompts`, game skills: other products.

---

## 10. Report template for the owner (write it in Arabic)

```
خلصت: <شو تغيّر بجملة، مع مثال واحد من الشاشة>.
انفحص: <أي اختبارات نجحت بالأرقام، وشو جرّبت فعلياً>.
ما انفحص: <بصراحة>.
على الموقع: <انرفع بطلب الدمج رقم N، وبيوصل الموقع خلال ربع ساعة تقريباً> أو <لسا ما انرفع وليش>.
عليك (إذا في): <خطوة وحدة واضحة>.
```
