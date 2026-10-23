# Zakiai Systems — استوديو المحتوى (AGENTS.md)

> للمالك (عربي): هذا الملف بيقرأه Hermes لحاله لما تشغّله جوّا مجلد المشروع. فيه كل شي لازم GLM يعرفه ليكمّل بلا ما يخرّب: شو المشروع، قواعدك، شو خلص، وشو الجاي. التفاصيل الأعمق بـ `docs/` وبالوثائق المذكورة بآخر الملف.

## 1. What this is

Arabic (Levantine) COD video-ad studio. It learns reusable ad patterns from winning videos, writes 7-scene scripts (45–50 s), produces voice, images and motion, edits and exports 9:16 ads, and tracks performance. Used by a small team (3 people) on a Windows PC; heavy open-weights models run later on ONE Linux GPU server in Docker.

Stack: Python 3.11, FastAPI + SQLite + vanilla JS (no build step, RTL Arabic UI), ffmpeg, optional Remotion (`services/advanced_montage`), a Chrome MV3 extension (`extension/`, v0.4.0) that generates on third-party sites with the owner's own accounts, and Docker model boxes (`services/engine`).

The project continues the existing codebase. Do not rewrite or restructure it.

## 2. Talking to the owner (non-negotiable)

- The owner (Ahmad, "Zaki AI") is a business owner who speaks Levantine Arabic. He is not a programmer.
- Write to him in Levantine Arabic: short, plain, no unexplained jargon, ONE concrete example per explanation, no file-name tables unless he must open a file.
- Finish the job end to end without small questions. Ask only for real decisions or things only he can do (secrets, payments, logins, spending credits). When you must ask: say the question in one sentence, give your recommended option first with the reason, example and cost, then the other options.
- He delegates decisions ("القرارات عليّ، والأسهل"). Pick the simplest option. Smoothness and no complexity come first ("السلاسة وعدم التعقيد").
- He types keys, tokens and passwords himself. Never ask for them in chat, never write them anywhere.
- If he says "وقف عند التنفيذ": write the decisions down and wait for "نفّذ".
- Report honestly: what was verified (tests, a real run) and what was not. Never claim something works unless you ran it.

## 3. Hard rules

Git and private data
- Commit or push only when the owner asks ("ارفع"). Work on `main`, run `git pull --rebase` before pushing. Repo: https://github.com/MKory18/zakiai-studio (private).
- Before every commit: `git add -A`, then `python tools/secret_scan.py` must print "نظيف". Never stage anything that `.gitignore` excludes: `settings.json`, `.env*`, `library/`, `products/*` (except `_template.json`), `models/*`, `secrets/`, `third_party/*`, `_handoff/`, media files. That is the owner's private data; the encrypted backup (`backup.py`) is where it belongs. If he asks to upload data, ask first.
- Secret values never appear in code, logs, tests, commits or chat. Tokens are referenced by secret NAME only (`secrets_store.py`: OS keyring, or an encrypted vault when `VP_SECRETS_KEY` is set on Linux).
- Outgoing calls to user-configured services go through `net_allow.py`: http only, loopback or docker-internal names, explicit port, no redirects, no proxies from the environment.

Product rules
- The guided mission (7 scenes, 45–50 s, ordered stations, AI review) behaves exactly as before. Tests that pin its rules must stay green. New manual behaviour ("free project") is gated by `_meta.mode == "free"` (script) or `tl["mode"] == "free"` (timeline).
- Generated music, effects and voice land in the sound library as unapproved and enter a video only after the owner listens and approves. Voice, lip-sync, music, sound-effects and motion models have NO silent fallback to another provider: errors surface.
- Model licences: "no" blocks activation; "conditional" or "unknown" need the owner's confirmation (it resets when the licence changes).
- The free project never launches to the OMS (409 `free_project`). The OMS side is not built.
- Compatibility names never change: keyring service `vidpattern`, `/api/vidpattern/*` and `vp:*`, `VP-` ids, `VP_*` env vars, `vidpattern_backup_*`, settings key `"CRM"`.

Engineering conventions
- UI text, comments and messages: Levantine Arabic. Identifiers: English.
- Each `web/static/*.js` is a closed IIFE that exposes one `window.*` name. New top-level `const/let` names collide across files (`tests/test_ui_globals.py` guards this).
- CSS only through `--vp-*` variables. Any change under `web/static` bumps `?v=` in BOTH `index.html` and `login.html` to the same number (now 80).
- Every new write route needs an Arabic label in `activity._R` (or SILENT): a test compares them with the OpenAPI paths.
- Every new endpoint also needs a mock (`web/static/mock/*.json` + handler in `app.js`, page opens with `?mock=1`).
- Ship tests with every change. Fake external services in tests (`tests/fake_gradio.py`, `fake_openai.py`, `engine_box.py`); never call real paid APIs.
- Do not touch `services/openmontage/` (third-party, read-only). Remotion is pinned to 4.0.530; version 5 has a different licence.

## 4. Run, test, verify

```
python run_web.py                       # http://127.0.0.1:8000  (or double-click "تشغيل الاستوديو.bat")
python -X utf8 -m pytest tests -q -p no:cacheprovider     # about 16 min; 2370 passed, 4 skipped on 22 Oct 2026
python -X utf8 -m pytest tests/test_<area>.py -q -p no:cacheprovider   # targeted run first
node --check web/static/<file>.js
python tools/secret_scan.py             # before every push
python tools/edge_shot.py jobs.json     # headless Edge screenshots (see the docstring)
ENGINE_TOKEN=x docker compose -f docker-compose.engines.yml config      # static check of the engine compose file
```

Windows tips: set `PYTHONIOENCODING=utf-8` when printing Arabic. PowerShell 5.1 scripts that contain Arabic must be saved as UTF-8 with BOM. A shell tool may eat backslashes: write patch scripts to a file and run them. Do not use `monkeypatch.undo()` in tests. After editing Python files the running studio must be restarted.

## 5. Repo map

- Pipeline: `stage0..3`, `review_loop.py`, `studio_state.py` (stations and gates), `timeline.py`, `shot_prompts.py`, `image_studio.py`, `voice_studio.py`, `generate_voice.py`, `motion.py`, `montage.py`, `montage_advanced.py`, `performance.py`, `placements.py`.
- Free project: `studio_gate.py`, `free_project.py`, `scene_import.py`, `media_io.py`, `free_montage.py`, `voice_upload.py`, `ar_align.py`, `manual_script.py`; UI `free.js`, `freemontage.js`.
- Model library: `model_library.py` (+ `presets/model_templates.json`), `model_run.py`, links `link_std.py` (OpenAI-compatible), `link_cmd.py` (command), `link_engine.py` (weights box), `link_app.py` (Gradio 4+); `net_allow.py`, `gpu_lease.py`, `media_check.py`, `model_tasks.py`, `word_timing.py`, `sound_gen.py`; routes `web/routes_model_library.py`; UI `modellib.js`.
- Weights engine (Docker): `services/engine/` (`app.py` contract v2: `/jobs`, `/health`, `/models`; `backends/_introspect.py` safety scan + hints table, `diffusers_any.py`, `_upscale.py`, `fake.py`; `Dockerfile.diffusers`), `docker-compose.engines.yml`, deployment guide `README_AR_نشر_السيرفر.md`.
- Extension: `extension/` + `ext_contract.md` + `ext_*.py` + `web/routes_ext.py`.
- Web: `web/app.py`, `auth_gate.py` (login gate), `guard.py` (Host/Origin guard), `routes_*.py`, `web/static/*.js`.
- Private, ignored: `library/` (data), `settings.json`, `products/`, `models/`.
- Tools: `tools/secret_scan.py`, `tools/edge_shot.py`.

## 6. State on 22 Oct 2026

Done and pushed
- Overhaul in 8 phases: names, patterns in Arabic (+ Excel import, automatic translation), 3+ hooks per script, character face consistency, cinematic camera presets, staff accounts and activity log, neon theme and in-site guide.
- UI restructure (23 Oct): big «＋ إعلان جديد» chooser (guided mission / free project / quick task), «إعلاناتي» inside Home (no separate missions page), 4 library shelves, factory «readiness» list with fix buttons, 4 settings tabs, guide page `#/guide` (`web/static/guidepage.js`), neon theme back (real Unsplash photos under `img/theme/neon/`, credits in `credits.json`), quick tasks take one or many items and an explicit model (`provider=lib:ml_x` for image/voice, `model=mm_x` for motion).
- Free project (manual production from any start point) and the model library: weights box on the server, Gradio apps, OpenAI-compatible servers, local commands; lip-sync from the library; music and sound effects (Stable Audio) into the sound library as unapproved.

Verified
- Full test suite green. The engine Docker image was built and run for real. Tiny real diffusers models ran on a real GPU (RTX 4050, 6 GB) inside that image: audio, video, upscale, cancel, model switching; and studio to box to sound library end to end. Gradio apps checked on 4.44.1, 5.50.0 and 6.30.0. An independent review found 16 issues; 15 were fixed.

NOT verified (expect surprises)
- Big real weights on the server GPU: Qwen-Image, FLUX, Wan, LTX, Stable Audio.
- Real ACE-Step and Wan2.2-S2V apps; real paid providers (fal.ai keys); live Meta Graph; the extension on real sites (every selector is `verified:false`, it needs a calibration session with the owner logged in).
- Known by design: `model_library.pick()` falls back to the built-in provider if a task's default model is disabled or deleted, or the library file is corrupt.

Decisions already made (do not reopen)
- No ComfyUI. One Docker box per model family, one model loaded at a time, one shared GPU lock. Everything on one server; model URLs are loopback or docker-internal only.
- Open-weights models run on the server (the owner downloads weights and links them in the UI). fal.ai is optional.
- Remotion is free for up to 3 staff. TikTok and Snapchat ad pull wait until Facebook login is confirmed with a real app.
- Hermes-specific features inside the product are postponed. Hermes is only the way an agent runs.

## 7. Open work (in order)

1. First real server run with the guide `README_AR_نشر_السيرفر.md`; fix what the first GPU run shows (the owner pastes `docker compose logs`). Create once: `docker network create vidpattern_net` and `docker volume create vidpattern_gpu_locks`.
2. Owner-side items that block features: create the first staff account; replace the rejected Anthropic key (401), until then auto-translation of patterns and character identity cards wait; fal.ai key for Kling/Hailuo; calibrate the face-match threshold (0.363) on real characters; install the extension 0.4.0.
3. OMS side (performance read, launch, queue) is not built: specs in `مواصفات_تنفيذ_العمليات.md`, `CRM_CONTRACT.md`, `CRM_CONTRACT_QUEUE.md`. Performance and auto-launch are disabled until then. Do not touch the OMS repository without the owner's explicit word "نفّذ العمليات".
4. Ideas, lowest priority: WanGP, video upscaling and auto-upscale after choosing, transitions and advanced montage for the free project, HEIC photos, converting a free project to a launchable mission.

## 8. Where to read more

- `docs/PROJECT_STATE_AR.md`: state and decisions per area, in Arabic.
- `docs/PLAN_free_project_model_library_AR.md`: the approved plan of the free project and model library, with notes on how it was built.
- Specs: `STUDIO_DESIGN.md`, `ui_contract.md`, `ext_contract.md`, `BUILD_SPEC.md` (original pipeline), the Arabic plans `خطة_*.md`, decisions `قرارات_التنفيذ.md`.
- Models and third-party notes: `models/README.md`, `third_party/README.md`.
