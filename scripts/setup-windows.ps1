$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Test-Python311([string]$Command, [string[]]$Prefix = @()) {
    try {
        & $Command @Prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

if (Test-Path $VenvPython) {
    $PythonCommand = $VenvPython
    $PythonPrefix = @()
} elseif ($env:ASTRA_PYTHON -and (Test-Python311 $env:ASTRA_PYTHON)) {
    $PythonCommand = $env:ASTRA_PYTHON
    $PythonPrefix = @()
} elseif ((Get-Command py.exe -ErrorAction SilentlyContinue) -and (Test-Python311 "py.exe" @("-3.11"))) {
    $PythonCommand = "py.exe"
    $PythonPrefix = @("-3.11")
} elseif ((Get-Command python.exe -ErrorAction SilentlyContinue) -and (Test-Python311 "python.exe")) {
    $PythonCommand = "python.exe"
    $PythonPrefix = @()
} else {
    throw "未找到 Python 3.11+。请安装后重试，或把 ASTRA_PYTHON 设为 python.exe 的完整路径。"
}

Write-Host "使用 Python："
& $PythonCommand @PythonPrefix --version

if (-not (Test-Path $VenvPython)) {
    & $PythonCommand @PythonPrefix -m venv (Join-Path $ProjectRoot ".venv")
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e (Join-Path $ProjectRoot "backend")

$Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $Npm) {
    throw "未找到 npm.cmd。请安装 Node.js 20+ 并加入 PATH。"
}
Push-Location (Join-Path $ProjectRoot "frontend")
try {
    & $Npm.Source ci
    $NpmExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($NpmExitCode -ne 0) {
    throw "前端依赖安装失败（npm ci 退出码：$NpmExitCode）。"
}
Push-Location (Join-Path $ProjectRoot "frontend")
try {
    & $Npm.Source run build
    $BuildExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($BuildExitCode -ne 0) {
    throw "前端生产构建失败（npm run build 退出码：$BuildExitCode）。"
}

$EnvironmentFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $EnvironmentFile)) {
    Copy-Item (Join-Path $ProjectRoot "deploy\astra.env.windows.example") $EnvironmentFile
    Write-Host "已生成 .env，请先填写 MySQL、Redis 和 OpenCode 配置：$EnvironmentFile"
}
Write-Host "安装完成。编辑 .env 后运行 scripts\check-windows.ps1。"
