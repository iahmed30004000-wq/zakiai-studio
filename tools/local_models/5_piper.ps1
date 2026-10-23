<# تجهيز Piper — صوت عربي خفيف بيشتغل على المعالج (بلا كرت شاشة) · الحجم ~0.2 غيغا
الصوت: rhasspy/piper-voices ← ar_JO/kareem/medium (المستودع MIT، بس بيانات التدريب بلا رخصة معلنة ← لازم تأكّد الرخصة بنفسك بالمصنع).
الأداة: piper-tts (pip، بيئة لحالها بـ third_party\piper\.venv). الأمر اللي بيربطه الاستوديو: tools\local_models\piper_cmd.py
#>
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$root = "$PSScriptRoot\..\.."

Write-Host "◈ Piper — صوت عربي خفيف (معالج بس)"
& python "$PSScriptRoot\fetch_model.py" `
    --repo "rhasspy/piper-voices" `
    --dest "models/piper-ar" `
    --allow "ar/ar_JO/kareem/medium/*" `
    --min-gb 1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path "$root\third_party\piper\.venv\Scripts\python.exe")) {
    New-Item -ItemType Directory -Force "$root\third_party\piper" | Out-Null
    & python -m venv "$root\third_party\piper\.venv"
    & "$root\third_party\piper\.venv\Scripts\python.exe" -m pip install -U pip piper-tts
    if ($LASTEXITCODE -ne 0) { Write-Host "⚠ مشكلة بتثبيت piper-tts"; exit 1 }
}

Write-Host ""
Write-Host "✓ خلص. من الاستوديو: المصنع ← النماذج ← «أمر تشغيل» ← الصوت، والأمر: third_party\piper\.venv\Scripts\python.exe tools\local_models\piper_cmd.py --text-file {text_file} --out {out}"
Write-Host "  (أول تشغيل بينسخ بيانات espeak لمسار إنجليزي بـ ~\.cache\zakiai-piper لأن المكتبة ما بتفتح مسار فيه حروف عربية.)"
