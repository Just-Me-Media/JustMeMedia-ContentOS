$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "Starting JustMeMedia ContentOS..."
python ".\app\server.py"
