<# تنزيل Chatterbox Multilingual (صوت بيتكلم عربي) + سيرفر OpenAI-compatible
الأوزان: ResembleAI/chatterbox — MIT · السيرفر: travisvn/chatterbox-tts-api — AGPL-3.0 (سيرفر محلي بالكامل، مافي ربط تجاري خارجي)
#>
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$root = "$PSScriptRoot\..\.."

Write-Host "◈ تشاتربوكس (صوت عربي) — تنزيل الأوزان أولاً"
& python "$PSScriptRoot\fetch_model.py" `
    --repo "ResembleAI/chatterbox" `
    --dest "models/chatterbox" `
    --allow "t3_mtl23ls_v2.safetensors" "s3gen_v3.safetensors" "ve.safetensors" "mtl_tokenizer.json" "grapheme_mtl_merged_expanded_v1.json" "conds.pt" "tokenizer.json" `
    --min-gb 10
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "◈ تشاتربوكس — تجهيز بيئة بايثون (venv) وسيرفر OpenAI-compatible"
if (-not (Test-Path "$root\third_party\chatterbox-tts-api")) {
    & git clone https://github.com/travisvn/chatterbox-tts-api.git "$root\third_party\chatterbox-tts-api"
    if ($LASTEXITCODE -ne 0) { Write-Host "⚠ ما قدر نزّل chatterbox-tts-api — تأكد من الإنترنت وشغّل السكربت من جديد"; exit 1 }
}
if (-not (Test-Path "$root\third_party\chatterbox-tts-api\.venv\Scripts\python.exe")) {
    & python -m venv "$root\third_party\chatterbox-tts-api\.venv"
    & "$root\third_party\chatterbox-tts-api\.venv\Scripts\python.exe" -m pip install -U pip
    & "$root\third_party\chatterbox-tts-api\.venv\Scripts\python.exe" -m pip install -r "$root\third_party\chatterbox-tts-api\requirements.txt"
    if ($LASTEXITCODE -ne 0) { Write-Host "⚠ مشكلة بتثبيت متطلبات chatterbox-tts-api"; exit 1 }
}

Write-Host ""
Write-Host "✓ التنزيل خلص. للتشغيل: افتح ملف «تشغيل الصوت العربي.bat» اللي بجنب هاد السكربت."
Write-Host "  السيرفر بيسمع على http://127.0.0.1:4123/v1 (بس من جهازك، ما مفتوح عالشبكة)."
