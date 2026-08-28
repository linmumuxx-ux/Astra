$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} elseif ($env:ASTRA_PYTHON) {
    $Python = $env:ASTRA_PYTHON
} else {
    throw "未找到 Astra 虚拟环境。请先运行 scripts\setup-windows.ps1。"
}

Write-Host "Astra 启动环境："
& $Python --version
Push-Location (Join-Path $ProjectRoot "backend")
try {
    & $Python -m alembic upgrade head
    $MigrationExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($MigrationExitCode -ne 0) {
    throw "数据库迁移失败（退出码：$MigrationExitCode），请检查 .env 中的 MySQL 配置。"
}
& $Python (Join-Path $ProjectRoot "scripts\preflight.py")
if ($LASTEXITCODE -ne 0) {
    throw "环境自检未通过，请按上方建议处理后重试。"
}
& $Python (Join-Path $ProjectRoot "scripts\process_manager.py") start
exit $LASTEXITCODE
