<# تشغيل واجهة ACE-Step (موسيقى وأغاني) — Gradio على http://127.0.0.1:7865
النموذج ACE-Step/ACE-Step-v1-3.5B (Apache-2.0). الأوزان تحت models/ACE-Step-v1-3.5B.
#>
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$root = "$PSScriptRoot\..\.."
$venv = "$root\third_party\ace-step\.venv"

if (-not (Test-Path "$venv\Scripts\python.exe")) {
    Write-Host "⚠ ACE-Step مش منثبّت. شغّل أول شي سكربت «3_ace_step.bat»."
    exit 1
}

Write-Host "◈ شغّال ACE-Step على http://127.0.0.1:7865 (بس من جهازك، ما مفتوح عالشبكة)"
$env:ACE_CHECKPOINT_DIR = "$root\models\ACE-Step-v1-3.5B"
& "$venv\Scripts\python.exe" -m acestep.gui --server_name 127.0.0.1 --port 7865 --checkpoint_path "$root\models\ACE-Step-v1-3.5B"
