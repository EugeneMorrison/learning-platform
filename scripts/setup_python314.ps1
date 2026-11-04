# Install an official, project-local Python for development without Docker.
# No system installation, PATH changes, or changes to the Django venv.
param(
    [ValidatePattern('^3\.14\.\d+$')]
    [string]$Version = '3.14.10'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePath = Join-Path $projectRoot '.venv\runtimes\python3.14'
$archivePath = Join-Path $projectRoot ".venv\runtimes\python-$Version-embed-amd64.zip"
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
    throw 'This setup script requires 64-bit Windows on x86-64.'
}

New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
$downloadUrl = "https://www.python.org/ftp/python/$Version/python-$Version-embed-amd64.zip"
Write-Output "Downloading official Python $Version..."
Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath -UseBasicParsing
Expand-Archive -LiteralPath $archivePath -DestinationPath $runtimePath -Force
$pythonPath = Join-Path $runtimePath 'python.exe'
& $pythonPath -I -B -c 'import sys; from compression import zstd; assert sys.version_info[:2] == (3, 14); print(sys.version)'
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.14 runtime verification failed.'
}
Remove-Item -LiteralPath $archivePath
Write-Output "Python 3.14 is ready at $pythonPath"
