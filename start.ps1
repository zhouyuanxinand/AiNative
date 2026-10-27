[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$serviceRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$basicServiceDir = Join-Path $serviceRoot "basic-service"
$appDir = Join-Path $basicServiceDir "app"
$venvDir = Join-Path $basicServiceDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirements = Join-Path $basicServiceDir "requirements.txt"
$logDir = Join-Path $appDir "logs"
$runtimeDir = Join-Path $appDir "runtime"
$processFile = Join-Path $runtimeDir "local-services.json"

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $separator = $trimmed.IndexOf("=")
        if ($separator -lt 1) { continue }
        $name = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1).Trim()
        if ($name -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") { continue }
        if ($value.Length -ge 2) {
            $first = $value[0]; $last = $value[$value.Length - 1]
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        if ($null -eq [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

Import-DotEnv (Join-Path $serviceRoot ".env")
if (-not $env:APP_ENV) { $env:APP_ENV = "development" }
if (-not $env:JTB_HOST) { $env:JTB_HOST = "127.0.0.1" }
if (-not $env:JTB_FEEDBACK_HOST) { $env:JTB_FEEDBACK_HOST = "127.0.0.1" }
$port = if ($env:JTB_PORT) { [int]$env:JTB_PORT } else { 18130 }
$feedbackPort = if ($env:JTB_FEEDBACK_PORT) { [int]$env:JTB_FEEDBACK_PORT } else { 18131 }
if ($port -eq $feedbackPort) { throw "主服务与反馈管理端口不能相同" }
foreach ($listenPort in @($port, $feedbackPort)) {
    if ($listenPort -lt 1 -or $listenPort -gt 65535) { throw "无效端口：$listenPort" }
    if (Get-NetTCPConnection -LocalPort $listenPort -State Listen -ErrorAction SilentlyContinue) {
        throw "端口 $listenPort 已被占用；请先停止对应服务。未终止已有进程。"
    }
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
if (Test-Path -LiteralPath $processFile) {
    foreach ($entry in @(Get-Content -LiteralPath $processFile -Raw | ConvertFrom-Json)) {
        $running = Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.pid)" -ErrorAction SilentlyContinue
        if ($running -and $running.CommandLine -and $running.CommandLine.Contains($venvPython) -and $running.CommandLine.Contains($entry.module)) {
            throw "已有本项目服务 PID=$($entry.pid)，请先运行 .\stop.ps1"
        }
    }
}

if (-not (Test-Path -LiteralPath $venvDir)) {
    Write-Host "[start] 创建虚拟环境 $venvDir"
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3.13 -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { python -m venv $venvDir }
    } else {
        python -m venv $venvDir
    }
    if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败" }
}

Write-Host "[start] 安装依赖"
& $venvPython -m pip install -q -r $requirements
if ($LASTEXITCODE -ne 0) { throw "安装依赖失败" }

$services = @(
    @{ Name = "backend"; Module = "src.main"; Port = $port; HostName = $env:JTB_HOST },
    @{ Name = "feedback"; Module = "src.feedback_main"; Port = $feedbackPort; HostName = $env:JTB_FEEDBACK_HOST }
)
$started = @()
try {
    foreach ($service in $services) {
        $stdoutLog = Join-Path $logDir "$($service.Name)-startup.stdout.log"
        $stderrLog = Join-Path $logDir "$($service.Name)-startup.stderr.log"
        Write-Host "[start] 启动 $($service.Name) http://$($service.HostName):$($service.Port)/ (APP_ENV=$env:APP_ENV)"
        $proc = Start-Process -FilePath $venvPython -ArgumentList @("-m", $service.Module) `
            -WorkingDirectory $appDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
        $started += @{ pid = $proc.Id; module = $service.Module; port = $service.Port }
        Start-Sleep -Seconds 2
        $proc.Refresh()
        if ($proc.HasExited) { throw "$($service.Name) 提前退出；请检查 $stderrLog" }
        Write-Host "[start] $($service.Name) PID=$($proc.Id)，日志：$stdoutLog / $stderrLog"
    }
    $started | ConvertTo-Json | Set-Content -LiteralPath $processFile -Encoding UTF8
} catch {
    foreach ($entry in $started) { Stop-Process -Id $entry.pid -Force -ErrorAction SilentlyContinue }
    throw
}

Write-Host "[start] 反馈管理：http://$($env:JTB_FEEDBACK_HOST):$feedbackPort/feedback"
Write-Host "[start] 停止服务请运行 .\stop.ps1"
