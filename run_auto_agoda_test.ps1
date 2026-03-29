Param(
    [string]$JobMatch = "agoda",
    [int]$MaxJobs = 5,
    [string]$Query = "Senior C# Developer Israel",
    [ValidateSet("normal", "testing")]
    [string]$EasyApplyRunMode = "testing",
    [switch]$PreviewBeforeSubmit,
    [switch]$MirrorToTelegram,
    [switch]$NoScrape,
    [switch]$Headed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}

$chatId = [Environment]::GetEnvironmentVariable("TELEGRAM_CHAT_ID", "User")
if ([string]::IsNullOrWhiteSpace($chatId)) {
    throw "TELEGRAM_CHAT_ID (User env var) is not set."
}

$env:AGENT_DISABLE_JITTER = "1"
$env:AGENT_ENABLE_AGODA_FALLBACK = "1"
$env:TELEGRAM_CHAT_ID = $chatId

$argsList = @(
    "auto_agoda_test_agent.py",
    "--chat-id", "$chatId",
    "--job-match", "$JobMatch",
    "--max-jobs", "$MaxJobs",
    "--query", "$Query",
    "--easy-apply-run-mode", "$EasyApplyRunMode"
)

if (-not $NoScrape) {
    $argsList += "--run-scrape"
    if (-not $Headed) {
        $argsList += "--headless-scrape"
    }
}

if ($MirrorToTelegram) {
    $argsList += "--mirror-to-telegram"
}

if ($PreviewBeforeSubmit) {
    $argsList += "--preview-before-submit"
}

Write-Host "[RUNNER] Starting auto test..." -ForegroundColor Cyan
Write-Host "[RUNNER] Job match: $JobMatch | Scrape: $($NoScrape -eq $false) | Headed scrape: $($Headed.IsPresent)" -ForegroundColor Cyan

& $pythonExe @argsList
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "[RUNNER] PASS" -ForegroundColor Green
    exit 0
}

Write-Host "[RUNNER] FAIL (exit code $exitCode)" -ForegroundColor Red
exit $exitCode
