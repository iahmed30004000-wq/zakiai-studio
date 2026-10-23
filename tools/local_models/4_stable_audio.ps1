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

Write-Host ""
Write-Host "✓ خلص. من الاستوديو: المصنع ← نماذج محلية ← ربط «أمر تشغيل» بـ tools\local_models\stable_audio_cmd.py"
