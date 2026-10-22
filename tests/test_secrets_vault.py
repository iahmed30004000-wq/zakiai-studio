"""الخزنة المشفّرة للسيرفر (secrets_store.EncryptedFileKeyring): تشفير حقيقي، ما بنكتب فوق ملف ما فتحناه، وما بتتركّب إلا لما ما في keyring بالنظام."""

import base64
import json
import os
import stat
import sys
import threading

import keyring
import pytest
from keyring.backends import fail

sys.path.insert(0, os.path.dirname(__file__))

import secrets_store as ss  # noqa: E402

PHRASE = "correct-horse-battery-staple-42"
SECRET = "sk-FAKE-vault-secret-value-1234567890abcdef"


@pytest.fixture
def vault(tmp_path):
    return ss.EncryptedFileKeyring(tmp_path / "secrets" / "vault.enc", PHRASE)


@pytest.fixture
def server_like(tmp_path, monkeypatch):
    """جهاز بلا keyring بالنظام (سيرفر لينكس): الـ backend الفاشل + مجلد خزنة مؤقت، وبدون مفتاح الخزنة."""
    prev = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    monkeypatch.setenv(ss.VAULT_DIR_ENV, str(tmp_path / "secrets"))
    monkeypatch.delenv(ss.VAULT_KEY_ENV, raising=False)
    ss._bump()
    try:
        yield tmp_path / "secrets" / "vault.enc"
    finally:
        ss.restore_backend(prev)


# ── الكلاس نفسه ───────────────────────────────────────────────────────────

def test_round_trip_and_the_file_never_holds_plaintext(vault):
    vault.set_password("vidpattern", "crm_token", SECRET)
    vault.set_password("vidpattern", "اسم_عربي", "قيمة عربية طويلة " * 20)
    assert vault.get_password("vidpattern", "crm_token") == SECRET
    assert vault.get_password("vidpattern", "اسم_عربي").startswith("قيمة عربية")
    assert vault.get_password("vidpattern", "missing") is None and vault.get_password("other", "crm_token") is None
    raw = vault._path.read_bytes()
    assert SECRET.encode() not in raw and b"crm_token" not in raw and "عربية".encode() not in raw and PHRASE.encode() not in raw
    head = json.loads(raw)
    assert head["v"] == 1 and head["kdf"] == "pbkdf2-sha256" and head["rounds"] >= 100_000
    assert len(base64.b64decode(head["salt"])) == 16 and head["data"].startswith("gAAAA")


def test_a_new_instance_with_the_same_phrase_reads_it_and_the_salt_is_kept(tmp_path):
    p = tmp_path / "v" / "vault.enc"
    a = ss.EncryptedFileKeyring(p, PHRASE)
    a.set_password("vidpattern", "a", "1")
    salt1 = json.loads(p.read_bytes())["salt"]
    b = ss.EncryptedFileKeyring(p, PHRASE)
    assert b.get_password("vidpattern", "a") == "1"
    b.set_password("vidpattern", "b", "2")
    assert json.loads(p.read_bytes())["salt"] == salt1                                   # الملح ثابت للخزنة
    assert ss.EncryptedFileKeyring(p, PHRASE).get_password("vidpattern", "b") == "2"


def test_delete_returns_not_found_and_drops_empty_services(vault):
    with pytest.raises(ss.PasswordDeleteError):
        vault.delete_password("vidpattern", "nope")
    vault.set_password("vidpattern", "a", "1")
    vault.delete_password("vidpattern", "a")
    assert vault.get_password("vidpattern", "a") is None
    with pytest.raises(ss.PasswordDeleteError):
        vault.delete_password("vidpattern", "a")


def test_wrong_phrase_is_refused_and_never_overwrites_the_file(tmp_path):
    p = tmp_path / "vault.enc"
    ss.EncryptedFileKeyring(p, PHRASE).set_password("vidpattern", "a", SECRET)
    before = p.read_bytes()
    other = ss.EncryptedFileKeyring(p, "a-totally-different-phrase-99")
    for call in (lambda: other.get_password("vidpattern", "a"),
                 lambda: other.set_password("vidpattern", "b", "x"),
                 lambda: other.delete_password("vidpattern", "a")):
        with pytest.raises(ss.SecretsError, match="غلط أو الملف تالف"):
            call()
    assert p.read_bytes() == before
    assert ss.EncryptedFileKeyring(p, PHRASE).get_password("vidpattern", "a") == SECRET


@pytest.mark.parametrize("content", [b"not json at all", b"[1, 2]", b'{"v": 1}', b'{"v": 2, "salt": "AAAA", "rounds": 200000, "data": "x"}',
                                      b'{"v": 1, "salt": "!!!", "rounds": 200000, "data": "x"}', b"\xff\xfe\x00"])
def test_corrupt_or_foreign_files_are_refused_not_replaced(tmp_path, content):
    p = tmp_path / "vault.enc"
    p.write_bytes(content)
    v = ss.EncryptedFileKeyring(p, PHRASE)
    with pytest.raises(ss.SecretsError):
        v.get_password("vidpattern", "a")
    with pytest.raises(ss.SecretsError):
        v.set_password("vidpattern", "a", "1")
    assert p.read_bytes() == content


def test_a_crafted_file_cannot_make_us_spin_on_a_huge_round_count(tmp_path):
    p = tmp_path / "vault.enc"
    p.write_text(json.dumps({"v": 1, "kdf": "pbkdf2-sha256", "rounds": 10 ** 9, "salt": base64.b64encode(b"s" * 16).decode(), "data": "gAAAA"}))
    with pytest.raises(ss.SecretsError, match="إعدادات التشفير"):
        ss.EncryptedFileKeyring(p, PHRASE).get_password("vidpattern", "a")
    p.write_text(json.dumps({"v": 1, "kdf": "pbkdf2-sha256", "rounds": 200_000, "salt": base64.b64encode(b"s" * 16).decode(), "data": "gAAAA"}))
    p.write_bytes(p.read_bytes() + b" " * (5 * 1024 * 1024))
    with pytest.raises(ss.SecretsError, match="أكبر من المعقول"):
        ss.EncryptedFileKeyring(p, PHRASE).get_password("vidpattern", "a")


def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp_files(vault, monkeypatch):
    vault.set_password("vidpattern", "a", "1")
    before = vault._path.read_bytes()

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(ss.os, "replace", boom)
    with pytest.raises(ss.SecretsError, match="تعذّرت كتابة"):
        vault.set_password("vidpattern", "b", "2")
    monkeypatch.undo()
    assert vault._path.read_bytes() == before
    assert [f.name for f in vault._path.parent.iterdir()] == ["vault.enc"]
    assert vault.get_password("vidpattern", "b") is None


@pytest.mark.skipif(os.name == "nt", reason="صلاحيات POSIX")
def test_the_vault_file_is_owner_only(vault):
    vault.set_password("vidpattern", "a", "1")
    assert stat.S_IMODE(vault._path.stat().st_mode) == 0o600


def test_concurrent_writers_do_not_lose_updates(vault):
    def put(i):
        vault.set_password("vidpattern", f"k{i}", f"v{i}")
    threads = [threading.Thread(target=put, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert {f"k{i}": vault.get_password("vidpattern", f"k{i}") for i in range(12)} == {f"k{i}": f"v{i}" for i in range(12)}


def test_keyring_discovery_never_picks_it_up_by_itself():
    kinds = {type(x).__name__ for x in keyring.backend.get_all_keyring()}
    assert "EncryptedFileKeyring" not in kinds                                           # بيحتاج مسار وعبارة سر بالبناء


# ── التركيب التلقائي بـ secrets_store ─────────────────────────────────────

def test_without_a_phrase_a_serverlike_machine_still_refuses_with_a_hint(server_like):
    with pytest.raises(ss.SecretsError, match="غير متاح على هالجهاز.*VP_SECRETS_KEY"):
        ss.set_secret("crm_token", SECRET)
    with pytest.raises(ss.SecretsError):
        ss.get_secret("crm_token")
    assert not server_like.exists() and "fail" in ss.backend_name().lower()


def test_a_short_phrase_is_rejected_without_echoing_it(server_like, monkeypatch):
    monkeypatch.setenv(ss.VAULT_KEY_ENV, "short-key")
    with pytest.raises(ss.SecretsError, match="16 حرف") as e:
        ss.set_secret("crm_token", SECRET)
    assert "short-key" not in str(e.value) and not server_like.exists()


def test_a_blank_phrase_counts_as_unset(server_like, monkeypatch):
    monkeypatch.setenv(ss.VAULT_KEY_ENV, "   ")
    with pytest.raises(ss.SecretsError, match="غير متاح"):
        ss.get_secret("crm_token")


def test_with_a_phrase_the_vault_takes_over_the_failing_backend(server_like, monkeypatch):
    monkeypatch.setenv(ss.VAULT_KEY_ENV, PHRASE)
    v0 = ss.version()
    ss.set_secret("crm_token", SECRET)
    assert ss.version() > v0 and "EncryptedFileKeyring" in ss.backend_name()
    assert server_like.exists() and SECRET.encode() not in server_like.read_bytes()
    assert ss.get_secret("crm_token") == SECRET and ss.get_secret("nope") is None
    assert ss.delete_secret("crm_token") is True and ss.delete_secret("crm_token") is False
    assert ss.get_secret("crm_token") is None


def test_a_wrong_phrase_at_the_secrets_store_level_is_a_clear_arabic_error(server_like, monkeypatch):
    monkeypatch.setenv(ss.VAULT_KEY_ENV, PHRASE)
    ss.set_secret("crm_token", SECRET)
    before = server_like.read_bytes()
    keyring.set_keyring(fail.Keyring())                                                  # عملية جديدة بعبارة غلط
    monkeypatch.setenv(ss.VAULT_KEY_ENV, "another-passphrase-that-is-long")
    with pytest.raises(ss.SecretsError, match="غلط أو الملف تالف"):
        ss.get_secret("crm_token")
    with pytest.raises(ss.SecretsError):
        ss.set_secret("other", "x")
    assert server_like.read_bytes() == before


def test_a_real_system_keyring_always_wins(tmp_path, monkeypatch):
    mem, prev = ss.use_memory_backend()
    try:
        monkeypatch.setenv(ss.VAULT_KEY_ENV, PHRASE)
        monkeypatch.setenv(ss.VAULT_DIR_ENV, str(tmp_path / "secrets"))
        ss.set_secret("crm_token", SECRET)
        assert mem.store[("vidpattern", "crm_token")] == SECRET and "InMemoryKeyring" in ss.backend_name()
        assert not (tmp_path / "secrets").exists()
    finally:
        ss.restore_backend(prev)


def test_the_default_location_is_outside_library():
    p = ss.vault_path()
    assert p.name == "vault.enc" and p.parent.name == "secrets" and "library" not in p.parts
