param(
    [string]$SshUser = "arieluser",
    [ValidateSet("", "Processes", "Memory", "Disk", "Service")]
    [string]$Option = ""
)

$ServerIp = "49.13.199.61"
$SshTarget = "$SshUser@$ServerIp"
$SshOptions = @(
    "-o", "StrictHostKeyChecking=accept-new"
)

function Invoke-RemoteCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command
    )

    $output = & ssh @SshOptions $SshTarget $Command 2>&1
    return @($output | ForEach-Object { "$($_)" })
}

function Normalize-RemoteOutput {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Output
    )

    $clean = New-Object System.Collections.Generic.List[string]
    foreach ($item in @($Output)) {
        $text = "$item"
        $lines = $text -split "`r?`n"
        foreach ($line in $lines) {
            if (-not [string]::IsNullOrWhiteSpace($line)) {
                $clean.Add($line)
            }
        }
    }

    return $clean.ToArray()
}

function Show-Processes {
    Write-Host "`n[Processes] Fetching running process details from $SshTarget ..." -ForegroundColor Cyan

    $remote = "ps -eo pid=,comm=,user=,stat=,rss=,pcpu= --no-headers"

    $result = Invoke-RemoteCommand -Command $remote

    if (-not $result -or (($result -join "`n") -match "Permission denied|Could not resolve|Connection timed out|ssh:")) {
        Write-Host "Failed to retrieve processes." -ForegroundColor Red
        $result | ForEach-Object { Write-Host $_ }
        return
    }

    $lines = Normalize-RemoteOutput -Output $result
    $rows = foreach ($line in $lines) {
        $parts = ($line -replace "^\s+", "") -split "\s+"
        if ($parts.Count -lt 6) {
            continue
        }

        $pidVal = 0
        $rssVal = 0.0
        $cpuVal = 0.0

        if (-not [int]::TryParse($parts[0], [ref]$pidVal)) {
            continue
        }
        if (-not [double]::TryParse($parts[4], [ref]$rssVal)) {
            continue
        }
        if (-not [double]::TryParse($parts[5], [ref]$cpuVal)) {
            continue
        }

        [PSCustomObject]@{
            PID         = $pidVal
            ProcessName = $parts[1]
            ServiceName = "-"
            MemoryMB    = [math]::Round(($rssVal / 1024.0), 2)
            CPUPercent  = $cpuVal
            Owner       = $parts[2]
            Status      = $parts[3]
        }
    }

    $rows | Sort-Object -Property MemoryMB -Descending | Format-Table -AutoSize
}

function Show-MemoryOverview {
    Write-Host "`n[Memory] Fetching memory usage overview from $SshTarget ..." -ForegroundColor Cyan

    $summaryCmd = @'
free -m | awk 'NR==1{print "Metric\tTotalMB\tUsedMB\tFreeMB\tSharedMB\tBuffCacheMB\tAvailableMB"}
NR==2{printf "RAM\t%s\t%s\t%s\t%s\t%s\t%s\n", $2,$3,$4,$5,$6,$7}
NR==3{printf "SWAP\t%s\t%s\t%s\t-\t-\t-\n", $2,$3,$4}'
'@

    $topCmd = @'
ps -eo pid,comm,user,rss --sort=-rss --no-headers | head -n 20 | awk '{printf "%s\t%s\t%s\t%.2f\n", $1,$2,$3,$4/1024}'
'@

    $summary = Invoke-RemoteCommand -Command $summaryCmd
    $topMem = Invoke-RemoteCommand -Command $topCmd

    Write-Host "`nSystem Memory Summary:" -ForegroundColor Yellow
    $summaryRows = (Normalize-RemoteOutput -Output $summary) | ConvertFrom-Csv -Delimiter "`t"
    $summaryRows | Format-Table -AutoSize

    Write-Host "`nTop 20 Processes by Memory (MB):" -ForegroundColor Yellow
    $topRows = (Normalize-RemoteOutput -Output $topMem) | ForEach-Object {
        $p = $_ -split "`t"
        if ($p.Count -ge 4) {
            [PSCustomObject]@{
                PID         = [int]$p[0]
                ProcessName = $p[1]
                Owner       = $p[2]
                MemoryMB    = [double]$p[3]
            }
        }
    }
    $topRows | Format-Table -AutoSize
}

function Show-DiskOverview {
    Write-Host "`n[Disk] Fetching disk usage overview from $SshTarget ..." -ForegroundColor Cyan

    $cmd = @'
df -h --output=source,size,used,avail,pcent,target -x tmpfs -x devtmpfs | awk 'NR==1{print "Filesystem\tSize\tUsed\tAvail\tUsePercent\tMountedOn"} NR>1{printf "%s\t%s\t%s\t%s\t%s\t%s\n", $1,$2,$3,$4,$5,$6}'
'@

    $result = Invoke-RemoteCommand -Command $cmd
    $rows = (Normalize-RemoteOutput -Output $result) | ConvertFrom-Csv -Delimiter "`t"
    $rows | Format-Table -AutoSize
}

function Show-ServicesOverview {
    Write-Host "`n[Service] Fetching service overview from $SshTarget ..." -ForegroundColor Cyan

    $cmd = @'
echo -e "Name\tDescription\tStatus"
systemctl list-units --type=service --all --no-legend --no-pager | awk '{
  name=$1
  load=$2
  active=$3
  sub=$4
  $1=$2=$3=$4=""
  desc=$0
  sub(/^ +/, "", desc)
  status=active
  printf "%s\t%s\t%s\n", name, desc, status
}'
'@

    $result = Invoke-RemoteCommand -Command $cmd

    $rows = (Normalize-RemoteOutput -Output $result) | ConvertFrom-Csv -Delimiter "`t"

    $rows | Sort-Object -Property Name | Format-Table -Wrap -AutoSize
}

function Show-Menu {
    Write-Host "`n===== Hetzner Server Menu ($ServerIp) =====" -ForegroundColor Green
    Write-Host "1) Processes"
    Write-Host "2) Memory"
    Write-Host "3) Disk"
    Write-Host "4) Service"
    Write-Host "5) Exit"
}

Write-Host "Target SSH: $SshTarget" -ForegroundColor Gray
Write-Host "Tip: If not using SSH keys, you may be prompted for password per action." -ForegroundColor Gray

if ($Option) {
    switch ($Option) {
        "Processes" { Show-Processes }
        "Memory" { Show-MemoryOverview }
        "Disk" { Show-DiskOverview }
        "Service" { Show-ServicesOverview }
    }
    return
}

while ($true) {
    Show-Menu
    $choice = Read-Host "Select an option"

    switch ($choice) {
        "1" { Show-Processes }
        "2" { Show-MemoryOverview }
        "3" { Show-DiskOverview }
        "4" { Show-ServicesOverview }
        "5" {
            Write-Host "Exiting." -ForegroundColor Green
            return
        }
        default {
            Write-Host "Invalid option. Choose 1-5." -ForegroundColor Red
        }
    }
}
