<# تنزيل ACE-Step (توليد موسيقى وأغاني) — الترخيص Apache-2.0، الحجم ~8.3 غيغا
النموذج: ACE-Step/ACE-Step-v1-3.5B · الكود: pip install ace-step (Apache-2.0)
التشغيل: واجهة Gradio على http://127.0.0.1:7865
#>
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$root = "$PSScriptRoot\..\.."

Write-Host "◈ إيس-ستيب (موسيقى وأغاني) — تنزيل الأوزان (~8.3 غيغا، Apache-2.0)"
& python "$PSScriptRoot\fetch_model.py" `
    --repo "ACE-Step/ACE-Step-v1-3.5B" `
    --dest "models/ACE-Step-v1-3.5B" `
    --allow "*.safetensors" "*.json" `
    --min-gb 20
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "◈ إيس-ستيب — تجهيز بيئة بايثون (venv) وواجهة Gradio"
if (-not (Test-Path "$root\third_party\ace-step\.venv\Scripts\python.exe")) {
    & python -m venv "$root\third_party\ace-step\.venv"
    & "$root\third_party\ace-step\.venv\Scripts\python.exe" -m pip install -U pip
    & "$root\third_party\ace-step\.venv\Scripts\python.exe" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
    if ($LASTEXITCODE -ne 0) { Write-Host "⚠ مشكلة بتثبيت PyTorch بالـ cu126"; exit 1 }
    & "$root\third_party\ace-step\.venv\Scripts\python.exe" -m pip install ace-step
    if ($LASTEXITCODE -ne 0) { Write-Host "⚠ مشكلة بتثبيت ace-step"; exit 1 }
}

Write-Host ""
Write-Host "✓ التنزيل خلص. للتشغيل: افتح ملف «تشغيل الموسيقى.bat» اللي بجنب هاد السكربت."
