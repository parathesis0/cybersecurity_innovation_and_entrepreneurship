$ErrorActionPreference = 'Stop'
$AssignmentDir = Split-Path -Parent $PSScriptRoot

Push-Location $AssignmentDir
try {
    python .\scripts\parse_bitcoin.py
    python .\scripts\build_report.py
} finally {
    Pop-Location
}
