$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
& $pythonPath -m pip install -r backend\requirements.lock --quiet
if ($LASTEXITCODE -ne 0) { throw 'Could not install backend dependencies.' }
Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
try {
    if (-not (Test-Path -LiteralPath 'node_modules')) {
        npm.cmd ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'Could not install frontend dependencies.' }
    }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Host "`nHookscope: http://127.0.0.1:8787  (Ctrl+C to stop)`n" -ForegroundColor Green
Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
& $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --no-access-log
