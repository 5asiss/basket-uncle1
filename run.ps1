# 바구니삼촌 로컬 개발 서버 실행 (가상환경)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "가상환경이 없습니다. 먼저 실행하세요:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv" -ForegroundColor Cyan
    Write-Host "  .\.venv\Scripts\pip install -r requirements.txt" -ForegroundColor Cyan
    exit 1
}

Write-Host "패키지 확인 중..." -ForegroundColor Gray
& $python -m pip install -r requirements.txt -q

$port = if ($env:PORT) { $env:PORT } else { 5000 }
$url = "http://127.0.0.1:$port"
Write-Host "브라우저에서 $url 열기" -ForegroundColor Green
Start-Process $url

Write-Host "서버 시작 (종료: Ctrl+C)" -ForegroundColor Green
& $python app.py
