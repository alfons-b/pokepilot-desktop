<#
.SYNOPSIS
  Build PokePilot.exe on Windows (creates .venv, installs dependencies, runs tests, runs PyInstaller).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
  powershell -ExecutionPolicy Bypass -File .\build_windows.ps1 -SkipTests
#>
param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Exe $($Arguments -join ' ')" }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    Invoke-Checked "py" @("-3.12", "-m", "venv", ".venv")
}
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Invoke-Checked $py @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Checked $py @("-m", "pip", "install", "-r", "requirements-dev.txt", "-r", "requirements-build.txt")

if (-not $SkipTests) {
    Write-Host "Running tests..."
    $env:QT_QPA_PLATFORM = "offscreen"
    try { Invoke-Checked $py @("-m", "pytest", "-q") } finally { Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue }
}

Write-Host "Building with PyInstaller..."
Invoke-Checked $py @("-m", "PyInstaller", "--noconfirm", "--clean", "pokepilot.spec")

$zip = "dist\PokePilot-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\PokePilot" -DestinationPath $zip
Write-Host ""
Write-Host "Done:  dist\PokePilot\PokePilot.exe"
Write-Host "Zip:   $zip"
