[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$serviceRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$basicServiceDir = Join-Path $serviceRoot "basic-service"
$venvDir = Join-Path $basicServiceDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$processFile = Join-Path $basicServiceDir "app\runtime\local-services.json"
$candidates = @()
if (Test-Path -LiteralPath $processFile) {
    $candidates += @(Get-Content -LiteralPath $processFile -Raw | ConvertFrom-Json)
}

# 支持停止旧版脚本启动的服务；同时读取 .env 中的端口，避免环境变化漏停。
$ports = @{ JTB_PORT = 18130; JTB_FEEDBACK_PORT = 18131 }
$envFile = Join-Path $serviceRoot ".env"
if (Test-Path -LiteralPath $envFile) {
    foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
        if ($line -match '^\s*(JTB_PORT|JTB_FEEDBACK_PORT)\s*=\s*["'']?(\d+)["'']?\s*$') {
            $ports[$Matches[1]] = [int]$Matches[2]
        }
    }
}
foreach ($name in @("JTB_PORT", "JTB_FEEDBACK_PORT")) {
    $configured = [Environment]::GetEnvironmentVariable($name, "Process")
    if ($configured) { $ports[$name] = [int]$configured }
    foreach ($connection in @(Get-NetTCPConnection -LocalPort $ports[$name] -State Listen -ErrorAction SilentlyContinue)) {
        $module = if ($name -eq "JTB_PORT") { "src.main" } else { "src.feedback_main" }
        $candidates += @{ pid = $connection.OwningProcess; module = $module; port = $ports[$name] }
    }
}

$stopped = 0
$seen = @{}
foreach ($entry in $candidates) {
    $procId = [int]$entry.pid
    if ($seen.ContainsKey($procId)) { continue }
    $seen[$procId] = $true
    if ($entry.module -notin @("src.main", "src.feedback_main")) { continue }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    $commandLine = $process.CommandLine
    # 同时校验本项目虚拟环境与入口模块；不停止其他占用端口的程序。
    if ($commandLine -and $commandLine.Contains($venvPython) -and $commandLine.Contains($entry.module)) {
        Write-Host "[stop] 终止 $($entry.module) PID=$procId (端口 $($entry.port))"
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        $stopped++
    } else {
        Write-Host "[stop] PID=$procId 属于其他程序，未终止"
    }
}

if (Test-Path -LiteralPath $processFile) {
    Remove-Item -LiteralPath $processFile
}
Write-Host "[stop] 已终止 $stopped 个本项目服务进程"
