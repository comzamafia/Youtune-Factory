# ============================================================
# run_novel.ps1  –  รัน quick_test_thai.py กับนิยายที่ระบุ
# Usage:  .\run_novel.ps1
#     หรือ .\run_novel.ps1 "input/novels/ชื่อไฟล์.txt"
# ============================================================

param(
    [string]$NovelPath = ""
)

if (-not $NovelPath) {
    # Auto-find the first .txt novel in input/novels/
    $found = Get-ChildItem -Path (Join-Path $PSScriptRoot "input\novels") -Filter "*.txt" |
             Select-Object -First 1
    if ($found) {
        $NovelPath = $found.FullName
    } else {
        Write-Error "No .txt file found in input/novels/. Please pass the path as argument."
        exit 1
    }
}

# เพิ่ม PATH ให้ครบ (Ollama, ffmpeg, ฯลฯ)
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","User")

# เปิดใช้ venv ถ้ายังไม่ได้เปิด
$venvActivate = Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    & $venvActivate
}

# เปลี่ยน directory ไปที่โปรเจกต์
Set-Location $PSScriptRoot

# ลบ DB เก่าทิ้ง (ถ้ามี) เพื่อเริ่มใหม่สะอาด
Remove-Item aiyoutube.db -ErrorAction SilentlyContinue

Write-Host "==> Running pipeline with: $NovelPath" -ForegroundColor Cyan

# รัน Python แล้วเซฟ output ลงไฟล์ + แสดงบน console พร้อมกัน
python quick_test_thai.py $NovelPath 2>&1 | ForEach-Object {
    $line = $_.ToString()
    Write-Host $line
    $line
} | Out-File -FilePath user_novel_output.txt -Encoding utf8

Write-Host ""
Write-Host "==> Done! Output saved to user_novel_output.txt" -ForegroundColor Green
