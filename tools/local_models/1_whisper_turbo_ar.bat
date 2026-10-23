<# تنزيل موديل ويسبر Turbo المدرب عالعراقي (تفريغ الصوت) — يعمل بلا إنترنت بعد التنزيل
الترخيص: Apache-2.0 · الحجم: ~0.8 غيغا · المصدر: dev-ahmedhany/whisper-large-v3-turbo-arabic-ft-ct2-int8
#>
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$py = "python"
if (Test-Path "$PSScriptRoot\..\..\.venv-studio\Scripts\python.exe") { $py = "$PSScriptRoot\..\..\.venv-studio\Scripts\python.exe" }

Write-Host "◈ ويسبر تيربو (عراقي) — تفريغ الصوت"
Write-Host "  الحجم ~0.8 غيغا، الترخيص Apache-2.0 (تجاري مسموح)"
& $py "$PSScriptRoot\fetch_model.py" `
    --repo "dev-ahmedhany/whisper-large-v3-turbo-arabic-ft-ct2-int8" `
    --dest "models/whisper-turbo-ar-ct2" `
    --allow "*.bin" "*.json" "*.txt" `
    --min-gb 3
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "✓ خلص. من المكتبة: المصنع ← نماذج محلية ← ربط «سيرفر بواجهة OpenAI» على http://127.0.0.1:8000/v1"
Write-Host "  ملاحظة: جرّبه بالمقابل مع large-v3 (الإعداد تفريغ) قبل ما تقلّب عليه — قد يكون أدق باللهجات بس أبطأ."
