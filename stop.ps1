[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$basicServiceDir = Join-Path $PSScriptRoot "basic-service"
$venvDir = Join-Path $basicServiceDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$port = if ($env:JTB_PORT) { [int]$env:JTB_PORT } else { 18130 }

# 只终止监听目标端口、且由本项目虚拟环境启动的 uvicorn 进程。
$connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $connections) {
    Write-Host "[stop] 端口 $port 上没有监听进程"
    return
}

$stopped = 0
foreach ($conn in $connections) {
    $procId = $conn.OwningProcess
    try {
        $proc = Get-Process -Id $procId -ErrorAction Stop
    } catch {
        continue
    }
    # 校验进程命令行属于本项目虚拟环境，避免误杀其他程序。
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue).CommandLine
    if ($cmd -and ($cmd -like "*$venvPython*") -and ($cmd -like "*src.main*")) {
        Write-Host "[stop] 终止 PID=$procId (端口 $port)"
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        $stopped++
    }
}

if ($stopped -eq 0) {
    Write-Host "[stop] 端口 $port 由其他程序占用，未终止"
} else {
    Write-Host "[stop] 已终止 $stopped 个进程"
}
