<# تشغيل سيرفر الصوت العربي (Chatterbox) — سيرفر OpenAI-compatible محلي بسمع بس على جهازك
بعد أول تشغيل: من الاستوديو ← المصنع ← نماذج محلية ← ربط «سيرفر بواجهة OpenAI» على http://127.0.0.1:4123/v1
النموذج ResembleAI/chatterbox (MIT) والسيرفر travisvn/chatterbox-tts-api (AGPL-3.0، محلي بالكامل).
#>
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$root = "$PSScriptRoot\..\.."
$api = "$root\third_party\chatterbox-tts-api"

if (-not (Test-Path "$api\.venv\Scripts\python.exe")) {
    Write-Host "⚠ السيرفر مش منثبّت. شغّل أول شي سكربت «2_chatterbox.bat»."
    exit 1
}

Write-Host "◈ شغّال سيرفر الصوت العربي على http://127.0.0.1:4123 (أول طلب بياخد دقايق لأن الموديل بينزل عالكرت)"
$env:PORT = "4123"
$env:HOST = "127.0.0.1"
$env:USE_MULTILINGUAL_MODEL = "true"
$env:DEVICE = "cuda"
& "$api\.venv\Scripts\python.exe" "$api\main.py"
