Param(
    [string]$JobMatch = "agoda",
    [int]$MaxJobs = 5,
    [string]$Query = "Senior C# Developer Israel",
    [ValidateSet("search", "testing")]
    [string]$EasyApplyRunMode = "testing",
    [switch]$PreviewBeforeSubmit,
    [switch]$MirrorToTelegram,
    [switch]$NoScrape,
    [switch]$Headed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-AgentEngineProcessIds {
    $procs = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match "python" -and $_.CommandLine -match "agent_engine.py"
    }
    return @($procs | Select-Object -ExpandProperty ProcessId)
}

function Stop-NewAgentProcesses {
    param(
        [int[]]$BaselineProcessIds
    )

    $baseline = @{}
    foreach ($pid in ($BaselineProcessIds | Where-Object { $_ -gt 0 })) {
        $baseline[$pid] = $true
    }

    $current = Get-AgentEngineProcessIds
    $launchedByThisRun = @($current | Where-Object { -not $baseline.ContainsKey($_) })
    if (-not $launchedByThisRun -or $launchedByThisRun.Count -eq 0) {
        Write-Host "[RUNNER] Cleanup: no newly launched agent_engine.py process to stop." -ForegroundColor DarkGray
        return
    }

    foreach ($pid in $launchedByThisRun) {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 500

    $remaining = Get-AgentEngineProcessIds | Where-Object { $launchedByThisRun -contains $_ }
    if ($remaining) {
        Write-Host "[RUNNER] Cleanup warning: could not stop agent_engine.py PIDs: $($remaining -join ', ')" -ForegroundColor Yellow
        return
    }
    Write-Host "[RUNNER] Cleanup: stopped launched agent_engine.py PIDs: $($launchedByThisRun -join ', ')" -ForegroundColor Green
}

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
# Use a separate profile file so the auto-test run never writes to the
# production telegram_profile.json.  The file is created automatically
# on first use if it does not exist.
$env:AGENT_PROFILE_PATH = Join-Path $projectRoot "telegram_profile.test.json"

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

$baselineAgentPids = Get-AgentEngineProcessIds
$exitCode = 1
try {
    & $pythonExe @argsList
    $exitCode = $LASTEXITCODE
}
finally {
    Stop-NewAgentProcesses -BaselineProcessIds $baselineAgentPids
}

if ($exitCode -eq 0) {
    Write-Host "[RUNNER] PASS" -ForegroundColor Green
    exit 0
}

Write-Host "[RUNNER] FAIL (exit code $exitCode)" -ForegroundColor Red
exit $exitCode
