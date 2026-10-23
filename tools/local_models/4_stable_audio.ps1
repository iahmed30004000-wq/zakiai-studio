<# تنزيل Stable Audio Open 1.0 (موسيقى ومؤثرات صوتية) — Stability AI Community License
مقيّد: بدّه حساب HuggingFace وقبول الترخيص هون: https://huggingface.co/stabilityai/stable-audio-open-1.0
الحجم: ~5.3 غيغا (ترتيب diffusers اللي بيقرأه stable_audio_cmd.py) · الأوزان بتنزّل تحت models/stable-audio-open-1.0
#>
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "◈ ستايل إوديو (موسيقى ومؤثرات) — مقيّد: بدّك تسجّل دخول عالحساب أول"
Write-Host "  (1) افتح https://huggingface.co/stabilityai/stable-audio-open-1.0 وسجّل دخول واكبس «Agree» عالترخيص."
Write-Host "  (2) افتح CMD واكتب:  hf auth login   وافتح الرابط واكتب الكود اللي بيطلعلك."
Write-Host "  (3) هيّا شغّل هالسكربت من ثاني."
& python "$PSScriptRoot\fetch_model.py" `
    --repo "stabilityai/stable-audio-open-1.0" `
    --dest "models/stable-audio-open-1.0" `
    --allow "model_index.json" "scheduler/*" "transformer/*" "vae/*" "text_encoder/*" "projection_model/*" "tokenizer/*" `
    --min-gb 12 `
    --gated `
    --done-files 14
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$root = "$PSScriptRoot\..\.."
if (-not (Test-Path "$root\third_party\stable-audio\.venv\Scripts\python.exe")) {
    New-Item -ItemType Directory -Force "$root\third_party\stable-audio" | Out-Null
    & python -m venv "$root\third_party\stable-audio\.venv"
    $py = "$root\third_party\stable-audio\.venv\Scripts\python.exe"
    & $py -m pip install -U pip
    & $py -m pip install "torch==2.6.0" "torchaudio==2.6.0" --index-url https://download.pytorch.org/whl/cu124
    if ($LASTEXITCODE -ne 0) { Write-Host "⚠ مشكلة بتثبيت PyTorch"; exit 1 }
    & $py -m pip install diffusers transformers accelerate scipy soundfile sentencepiece safetensors torchsde
    if ($LASTEXITCODE -ne 0) { Write-Host "⚠ مشكلة بتثبيت مكتبات النموذج"; exit 1 }
}

Write-Host ""
Write-Host "✓ خلص. من الاستوديو: المصنع ← نماذج محلية ← ربط «أمر تشغيل» بـ tools\local_models\stable_audio_cmd.py"
