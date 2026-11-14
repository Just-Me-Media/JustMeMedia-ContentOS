# Distribution script - builds and packages ContentOS for Windows release
param(
    [switch]$IncludeFrontEnd
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "============================================"
Write-Host "  Building ContentOS Distribution (Windows)"
Write-Host "============================================"

$DistDir = Join-Path $env:TEMP "contentos-dist-windows"
if (Test-Path $DistDir) { Remove-Item -Recurse -Force $DistDir }
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

Write-Host ""
Write-Host "[1/4] Building frontend..."
Push-Location "$Root\frontend"
if (Test-Path "node_modules") {
    Write-Host "   node_modules exists, skipping npm install"
} else {
    npm install --quiet 2>$null
}
npm run build
Write-Host "   ✓ Frontend built"
Pop-Location

Write-Host ""
Write-Host "[2/4] Copying files..."
# Copy Python backend files
Copy-Item "$Root\app\*.py" -Destination $DistDir
Copy-Item "$Root\app\platforms" -Destination $DistDir -Recurse
New-Item -ItemType Directory -Force -Path "$DistDir\data" | Out-Null

# Copy built frontend
Copy-Item "$Root\static" -Destination $DistDir -Recurse

# Copy config, scripts, and docs
Copy-Item "$Root\config" -Destination $DistDir -Recurse
Copy-Item "$Root\scripts" -Destination $DistDir -Recurse
Copy-Item "$Root\brand" -Destination $DistDir -Recurse
Copy-Item "$Root\prompts" -Destination $DistDir -Recurse
Copy-Item "$Root\workflows" -Destination $DistDir -Recurse

Copy-Item "$Root\README.md" -Destination $DistDir
Copy-Item "$Root\SECURITY.md" -Destination $DistDir
if (Test-Path "$Root\LICENSE") {
    Copy-Item "$Root\LICENSE" -Destination $DistDir
} else {
    "MIT License" | Out-File "$DistDir\LICENSE" -Encoding utf8
}

Write-Host "   ✓ Files copied"

Write-Host ""
Write-Host "[3/4] Creating run scripts..."
# Create simple run script
$runContent = @"`n# ContentOS run script
Write-Host "Starting JustMeMedia ContentOS..."
Write-Host "Visit http://127.0.0.1:8765"
Set-Location (Split-Path -Parent `$MyInvocation.MyCommand.Path)
python ".\app\server.py"
"@
$runContent | Out-File "$DistDir\run.ps1" -Encoding utf8

# Windows batch file for double-click
$batContent = @"`n@echo off
echo Starting JustMeMedia ContentOS...
echo Visit http://127.0.0.1:8765
cd /d "%~dp0"
python "app\server.py"
"@
$batContent | Out-File "$DistDir\run.bat" -Encoding ascii

Write-Host "   ✓ Run scripts created"

Write-Host ""
Write-Host "[4/4] Creating distribution archive..."
Compress-Archive -Path "$DistDir\*" -DestinationPath "$env:TEMP\contentos-dist.zip" -Force
$DistFile = "$env:TEMP\contentos-dist.zip"

# Cleanup
Remove-Item -Recurse -Force $DistDir

# Get file size
$size = (Get-Item $DistFile).Length / 1MB

Write-Host ""
Write-Host "============================================"
Write-Host "  Distribution package created!"
Write-Host "  Location: $DistFile"
Write-Host "  Size: $([math]::Round($size, 2)) MB"
Write-Host "============================================"
Write-Host ""
Write-Host "To install:"
Write-Host "  Expand-Archive contentos-dist.zip -DestinationPath C:\your\install\dir"
Write-Host ""
Write-Host "Then run: .\run.ps1 or run.bat"