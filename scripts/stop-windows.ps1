$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} elseif ($env:ASTRA_PYTHON) {
    $Python = $env:ASTRA_PYTHON
} else {
    throw "未找到 Astra 虚拟环境。"
}
& $Python (Join-Path $ProjectRoot "scripts\process_manager.py") stop
exit $LASTEXITCODE
