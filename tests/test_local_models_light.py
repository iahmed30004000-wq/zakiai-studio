"""النماذج الخفيفة على جهاز المالك (24/10): Piper (صوت عربي بالمعالج) وStable Audio (بيئته وأمره). فحص ثابت — بلا تشغيل ولا تنزيل."""
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools" / "local_models"


def _t(name: str) -> str:
    return (TOOLS / name).read_text(encoding="utf-8-sig")


def test_piper_script_has_bom_launcher_and_asks_for_the_licence_confirmation():
    raw = (TOOLS / "5_piper.ps1").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    t = _t("5_piper.ps1")
    assert "rhasspy/piper-voices" in t and "ar/ar_JO/kareem/medium/*" in t and "piper-tts" in t and "piper_cmd.py" in t
    assert "بلا رخصة معلنة" in t                                              # الرخصة غير معروفة ← تأكيد المالك
    bat = (TOOLS / "5_piper.bat").read_bytes()
    assert bat.isascii() and b'-File "%~dp0%~n0.ps1"' in bat


def test_piper_command_uses_tashkeel_and_ascii_espeak_copy():
    t = _t("piper_cmd.py")
    assert "use_tashkeel" in t and "espeak_data_dir" in t and "zakiai-piper" in t       # مسار إنجليزي لأن espeak ما بيفتح مسار عربي
    assert "--text-file" in t and "wave.open" in t


def test_stable_audio_command_matches_the_diffusers_api_and_has_an_environment_step():
    t = _t("stable_audio_cmd.py")
    assert "audio_end_in_s=" in t and "audio_end_in_seconds" not in t                    # اسم الوسيط الصحيح بـ diffusers
    assert "audio[0].T" in t and "pipe.vae.sampling_rate" in t                           # ستيريو (عينات، قنوات) وبمعدّل النموذج
    s = _t("4_stable_audio.ps1")
    assert "third_party\stable-audio\.venv" in s and "torchsde" in s and "cu124" in s
