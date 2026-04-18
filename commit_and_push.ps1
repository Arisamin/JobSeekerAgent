param(
    [Parameter(Position = 0)]
    [string]$Message = "chore: update workspace changes"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

git add -A

git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "No staged changes to commit."
    exit 0
}

git commit -m $Message
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$branch = (git branch --show-current).Trim()
if ([string]::IsNullOrWhiteSpace($branch)) {
    Write-Error "Unable to determine current branch for push."
    exit 1
}

git push origin $branch
exit $LASTEXITCODE
