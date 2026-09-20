# Restarts the Life Transition Navigator dev server on port 8010.
# Run from anywhere: right-click > "Run with PowerShell", or in a terminal:
#   powershell -ExecutionPolicy Bypass -File restart.ps1

$port = 8010
$projectDir = $PSScriptRoot

Write-Host "Checking for anything already running on port $port..."
$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

foreach ($procId in $existing) {
    Write-Host "Stopping process tree $procId..."
    taskkill /F /T /PID $procId | Out-Null
}

Start-Sleep -Seconds 1

Write-Host "Starting server on http://localhost:$port ..."
Set-Location $projectDir
& "$projectDir\.venv\Scripts\python.exe" -m uvicorn backend.main:app --reload --port $port
