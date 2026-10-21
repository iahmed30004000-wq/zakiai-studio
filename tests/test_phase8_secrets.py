import json
import re
from pathlib import Path

import pytest

import config
import secrets_store
import settings_io
from tests.phase8_support import (ALL_FAKE, FAKE_ANTHROPIC, FAKE_CRM_TOKEN, FAKE_KEY_A,
                                  FAKE_KEY_B, FAKE_KEY_IMG, FAKE_KEY_STT, FAKE_KEY_TASK,
                                  FAKE_KEY_TTS, isolated, sample_settings)

ROOT = Path(__file__).resolve().parent.parent
KEY_RE = re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{16,}")


def _all_text_files(root: Path):
    for f in root.rglob("*"):
        if f.is_file():
            yield f


def test_save_keeps_keys_out_of_the_file(isolated):
    settings_io.save(sample_settings())
    raw = isolated.settings.read_text(encoding="utf-8")
    for k in ALL_FAKE:
        assert k not in raw
    assert not KEY_RE.search(raw.encode())
    data = json.loads(raw)
    assert data["ANTHROPIC_API_KEY"].startswith("secret:")
    assert data["CONNECTIONS"]["c_one"]["api_key"].startswith("secret:")
    assert data["TASKS"]["match"]["api_key"].startswith("secret:")
    for section in ("IMAGE", "TTS", "STT"):
        assert data[section]["api_key"].startswith("secret:")
    # الحقول العادية ما انلمست، وعدّاد التوكنز مش سر
    assert data["MAX_OUTPUT_TOKENS"] == 12000
    assert data["CONNECTIONS"]["c_one"]["models"][0]["id"] == "gpt-5"


def test_keys_land_in_the_store_with_stable_names(isolated):
    settings_io.save(sample_settings())
    assert secrets_store.get_secret("settings.CONNECTIONS.c_one.api_key") == FAKE_KEY_A
    assert secrets_store.get_secret("settings.TASKS.match.api_key") == FAKE_KEY_TASK
    assert secrets_store.get_secret("settings.ANTHROPIC_API_KEY") == FAKE_ANTHROPIC
    assert secrets_store.get_secret("settings.IMAGE.api_key") == FAKE_KEY_IMG


def test_load_resolves_all_refs(isolated):
    settings_io.save(sample_settings())
    d = settings_io.load()
    assert d["ANTHROPIC_API_KEY"] == FAKE_ANTHROPIC
    assert d["CONNECTIONS"]["c_one"]["api_key"] == FAKE_KEY_A
    assert d["CONNECTIONS"]["c_two"]["api_key"] == FAKE_KEY_B
    assert d["TASKS"]["match"]["api_key"] == FAKE_KEY_TASK
    assert (d["IMAGE"]["api_key"], d["TTS"]["api_key"], d["STT"]["api_key"]) == (
        FAKE_KEY_IMG, FAKE_KEY_TTS, FAKE_KEY_STT)
    assert d["MAX_OUTPUT_TOKENS"] == 12000


def test_save_is_stable_and_load_then_save_roundtrips(isolated):
    settings_io.save(sample_settings())
    first = isolated.settings.read_text(encoding="utf-8")
    settings_io.save(settings_io.load())        # نفس اللي بتعمله وحدات الإعدادات بالواجهة
    assert isolated.settings.read_text(encoding="utf-8") == first


def test_provider_keys_resolve_through_every_reader(isolated):
    import imagegen, llm, stt, tts
    settings_io.save(sample_settings())
    assert llm.task_config("writer")["api_key"] == FAKE_KEY_A            # اتصال
    assert llm.task_config("match")["api_key"] == FAKE_KEY_TASK          # مفتاح مهمة قديم
    assert llm.task_config("writer")["provider"] == "openai"
    assert imagegen.image_config()["api_key"] == FAKE_KEY_IMG
    assert tts.tts_config()["api_key"] == FAKE_KEY_TTS
    assert stt.stt_config()["api_key"] == FAKE_KEY_STT


def test_global_anthropic_key_and_env_ref_resolve(isolated, monkeypatch):
    import llm
    settings_io.save({"ANTHROPIC_API_KEY": FAKE_ANTHROPIC})
    assert llm.task_config("analysis")["api_key"] == FAKE_ANTHROPIC
    # config.py بينسخ قيمة الملف لمتغيّر البيئة — لو كانت مرجع لازم ينحلّ مش يوصل للمزوّد كنص "secret:..."
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret:settings.ANTHROPIC_API_KEY")
    (isolated.settings).write_text(json.dumps({}), encoding="utf-8")
    settings_io._cache["sig"] = None
    assert llm.task_config("analysis")["api_key"] == FAKE_ANTHROPIC


def test_crm_token_never_in_a_text_file(isolated):
    """التوكن بمخزن الأسرار بس — مهما انكتبت إعدادات."""
    secrets_store.set_secret("crm_token", FAKE_CRM_TOKEN)
    settings_io.save({**sample_settings(), "CRM": {"base_url": "https://crm.example.com",
                                                    "token": FAKE_CRM_TOKEN}})
    assert secrets_store.get_secret("crm_token") == FAKE_CRM_TOKEN
    for f in _all_text_files(isolated.tmp):
        blob = f.read_bytes()
        for k in ALL_FAKE:
            assert k.encode() not in blob, f"{k[:12]}… لقيناه بـ {f.name}"
    assert settings_io.load()["CRM"]["token"] == FAKE_CRM_TOKEN


def test_unresolved_ref_gives_empty_and_never_leaks(isolated, capsys):
    settings_io.save(sample_settings())
    isolated.mem.store.clear()
    settings_io._cache["sig"] = None
    d = settings_io.load()
    assert d["CONNECTIONS"]["c_one"]["api_key"] == ""
    err = capsys.readouterr().err
    assert "مش موجود" in err
    for k in ALL_FAKE:
        assert k not in err


def test_removed_settings_clean_their_secrets(isolated):
    import connections
    settings_io.save(sample_settings())
    assert secrets_store.get_secret("settings.CONNECTIONS.c_two.api_key") == FAKE_KEY_B
    connections.delete("c_two")
    assert secrets_store.get_secret("settings.CONNECTIONS.c_two.api_key") is None
    assert secrets_store.get_secret("settings.CONNECTIONS.c_one.api_key") == FAKE_KEY_A
    # أسرار الأنظمة التانية (crm_token، backup_key) ما بتنلمس
    secrets_store.set_secret("crm_token", FAKE_CRM_TOKEN)
    settings_io.save(settings_io.load())
    assert secrets_store.get_secret("crm_token") == FAKE_CRM_TOKEN


def test_connections_create_goes_to_store(isolated, monkeypatch):
    import connections
    monkeypatch.setattr(connections, "fetch_models",
                        lambda provider, key, url="": [{"id": "gpt-5", "label": "gpt-5"}])
    conn = connections.create("openai", FAKE_KEY_A, "اختبار")
    raw = isolated.settings.read_text(encoding="utf-8")
    assert FAKE_KEY_A not in raw
    assert connections.get(conn["id"])["api_key"] == FAKE_KEY_A
    masked = json.dumps(connections.public_view(), ensure_ascii=False)
    assert FAKE_KEY_A not in masked


def test_add_and_remove_model_do_not_touch_secrets(isolated):
    import llm
    settings_io.save(sample_settings())
    llm.add_model("openai", "new-model")
    assert "new-model" in llm.provider_models("openai")
    assert FAKE_KEY_A not in isolated.settings.read_text(encoding="utf-8")
    llm.remove_model("openai", "new-model")
    assert "new-model" not in llm.provider_models("openai")
    assert settings_io.load()["CONNECTIONS"]["c_one"]["api_key"] == FAKE_KEY_A


def test_web_app_writes_go_through_the_store(isolated):
    from fastapi.testclient import TestClient
    from web.app import app
    c = TestClient(app)
    assert c.put("/api/tts", json={"provider": "elevenlabs", "api_key": FAKE_KEY_TTS}).status_code == 200
    assert c.put("/api/imagegen", json={"provider": "openai", "api_key": FAKE_KEY_IMG}).status_code == 200
    assert c.put("/api/stt", json={"provider": "openai", "api_key": FAKE_KEY_STT}).status_code == 200
    assert c.put("/api/settings", json={"ANTHROPIC_API_KEY": FAKE_ANTHROPIC}).status_code == 200
    raw = isolated.settings.read_text(encoding="utf-8")
    for k in (FAKE_KEY_TTS, FAKE_KEY_IMG, FAKE_KEY_STT, FAKE_ANTHROPIC):
        assert k not in raw
    assert settings_io.load()["TTS"]["api_key"] == FAKE_KEY_TTS

    # القراءة بالواجهة مقنّعة — أبداً مفتاح كامل
    body = c.get("/api/tts").text + c.get("/api/imagegen").text + c.get("/api/stt").text
    for k in (FAKE_KEY_TTS, FAKE_KEY_IMG, FAKE_KEY_STT):
        assert k not in body

    assert c.delete("/api/settings/api-key").status_code == 200
    assert secrets_store.get_secret("settings.ANTHROPIC_API_KEY") is None


def test_no_direct_settings_writes_left():
    """كل كتابة لـ settings.json لازم تمرّ من settings_io."""
    pat = re.compile(r"SETTINGS_PATH\)?\.write_text|open\(config\.SETTINGS_PATH,\s*[\"']w")
    for name in ("web/app.py", "llm.py", "connections.py", "imagegen.py", "tts.py", "stt.py", "usage.py"):
        assert not pat.search((ROOT / name).read_text(encoding="utf-8")), name


def test_masking_and_redaction(isolated):
    d = settings_io.masked_view(sample_settings())
    assert FAKE_KEY_A not in json.dumps(d)
    assert d["MAX_OUTPUT_TOKENS"] == 12000
    settings_io.save(sample_settings())
    settings_io.load()
    text = f"فشل النداء بمفتاح {FAKE_KEY_A} وترويسة Bearer abcdefghijklmnop"
    out = settings_io.redact(text)
    assert FAKE_KEY_A not in out and "abcdefghijklmnop" not in out


def test_strip_secrets_removes_fields_and_refs(isolated):
    settings_io.save(sample_settings())
    stripped = settings_io.strip_secrets(settings_io.load_raw())
    blob = json.dumps(stripped)
    assert "secret:" not in blob and "api_key" not in blob
    assert stripped["CONNECTIONS"]["c_one"]["provider"] == "openai"


def test_store_failure_never_falls_back_to_plaintext(isolated, monkeypatch):
    def boom(name, value):
        raise secrets_store.SecretsError("مخزن الأسرار غير متاح")
    monkeypatch.setattr(secrets_store, "set_secret", boom)
    with pytest.raises(secrets_store.SecretsError):
        settings_io.save({"IMAGE": {"api_key": FAKE_KEY_IMG}})
    assert not isolated.settings.exists()


def test_migrate_script_dry_run_then_migrate_then_rollback(isolated):
    import migrate_secrets
    isolated.settings.write_text(json.dumps(sample_settings(), ensure_ascii=False), encoding="utf-8")
    p = str(isolated.settings)
    before = isolated.settings.read_text(encoding="utf-8")

    assert migrate_secrets.main(["--settings", p, "--dry-run"]) == 0
    assert isolated.settings.read_text(encoding="utf-8") == before
    assert isolated.mem.store == {}

    assert migrate_secrets.main(["--settings", p]) == 0
    raw = isolated.settings.read_text(encoding="utf-8")
    assert not KEY_RE.search(raw.encode())
    for k in ALL_FAKE:
        assert k not in raw
    assert settings_io.load()["CONNECTIONS"]["c_two"]["api_key"] == FAKE_KEY_B

    assert migrate_secrets.main(["--settings", p, "--rollback"]) == 1   # بدون --yes ما بيكتب
    assert FAKE_KEY_A not in isolated.settings.read_text(encoding="utf-8")
    assert migrate_secrets.main(["--settings", p, "--rollback", "--yes"]) == 0
    assert json.loads(isolated.settings.read_text(encoding="utf-8")) == sample_settings()


def test_migrate_is_a_noop_on_migrated_file(isolated):
    import migrate_secrets
    settings_io.save(sample_settings())
    before = isolated.settings.read_text(encoding="utf-8")
    assert migrate_secrets.main(["--settings", str(isolated.settings)]) == 0
    assert isolated.settings.read_text(encoding="utf-8") == before


def test_memory_backend_isolates_from_real_credential_manager(isolated):
    assert "InMemoryKeyring" in secrets_store.backend_name()
