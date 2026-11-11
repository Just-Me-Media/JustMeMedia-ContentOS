param(
    [switch]$Detached
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Port = 8765
$Url = "http://127.0.0.1:$Port"

Write-Host "============================================"
Write-Host "  Starting JustMeMedia ContentOS..."
Write-Host "  $Url"
if ($Detached) {
    Write-Host "  Mode: detached (server keeps running after this returns)"
}
Write-Host "============================================"

# Clear any previous instance holding the port (Windows parity with run_mac.sh)
$oldPids = @()
try {
    $oldPids = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
} catch {
    $oldPids = @()
}
foreach ($procId in $oldPids) {
    if ($procId -and $procId -ne 0) {
        Write-Host "  Clearing previous instance (PID: $procId)..."
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Milliseconds 500

if ($Detached) {
    # Start the server as an independent process, capture logs, and return
    # immediately so an automated/background launch never holds a shell open.
    $logDir = Join-Path $env:TEMP "contentos"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $stdout = Join-Path $logDir "server.out.log"
    $stderr = Join-Path $logDir "server.err.log"

    # Launch through WMI so the server is not a child of this shell/job and
    # survives after the launcher returns (crucial for automation/background runs).
    $python = (Get-Command python).Source
    $cmdLine = 'cmd.exe /c ""' + $python + '" ".\app\server.py" 1>"' + $stdout + '" 2>"' + $stderr + '""'
    $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine      = $cmdLine
        CurrentDirectory = $Root
    }
    if ($result.ReturnValue -ne 0) {
        Write-Host "  Failed to start server (WMI return $($result.ReturnValue))."
        exit 1
    }
    Write-Host "  Logs: $stdout"

    $ready = $false
    for ($i = 0; $i -lt 25; $i++) {
        Start-Sleep -Milliseconds 400
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            # server not up yet
        }
    }
    if ($ready) {
        $owner = $null
        try {
            $owner = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                Where-Object { $_.OwningProcess -and $_.OwningProcess -ne 0 } |
                Select-Object -First 1 -ExpandProperty OwningProcess
        } catch { }
        if ($owner) { Write-Host "  Server PID: $owner" }
        Write-Host "  Server is up."
    } else {
        Write-Host "  Warning: server did not respond yet. Check $stderr"
    }

    Start-Process $Url
    return
}

# Foreground mode (default): parity with run_mac.sh for double-click use.
# Open the browser shortly after the server starts, then block on the server.
Start-Job -ScriptBlock {
    param($Target)
    Start-Sleep -Milliseconds 1200
    Start-Process $Target
} -ArgumentList $Url | Out-Null

python ".\app\server.py"
