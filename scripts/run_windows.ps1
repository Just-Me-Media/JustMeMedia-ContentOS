$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Port = 8765
$Url = "http://127.0.0.1:$Port"

Write-Host "============================================"
Write-Host "  Starting JustMeMedia ContentOS..."
Write-Host "  $Url"
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

# Open the browser shortly after the server starts
Start-Job -ScriptBlock {
    param($Target)
    Start-Sleep -Milliseconds 1200
    Start-Process $Target
} -ArgumentList $Url | Out-Null

python ".\app\server.py"
