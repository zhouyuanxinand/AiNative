[CmdletBinding()]
param([int]$Port = 18130)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$rdDemoRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$rdDemoApp = Join-Path $rdDemoRoot 'basic-service/app'
$rdDemoPython = Join-Path $rdDemoRoot 'basic-service/.venv/Scripts/python.exe'
if ($Port -lt 1 -or $Port -gt 65535) { throw '无效端口' }
if (-not (Test-Path -LiteralPath $rdDemoPython)) { throw '请先安装 basic-service 的 Python 虚拟环境和依赖。' }
if (-not (Test-Path -LiteralPath (Join-Path $rdDemoRoot 'web/dist/index.html'))) { throw '请先在 web 目录执行 npm run build。' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "端口 $Port 已有服务，请先运行 .\stop.ps1 或使用 -Port 指定其他端口。" }

# Reuse private model configuration without printing any credential values.
$rdDemoEnvFile = Join-Path $rdDemoRoot '.env'
if (Test-Path -LiteralPath $rdDemoEnvFile) {
    foreach ($rdDemoLine in Get-Content -LiteralPath $rdDemoEnvFile -Encoding UTF8) {
        if ($rdDemoLine -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') { continue }
        $rdDemoEnvName = $Matches[1]
        $rdDemoEnvValue = $Matches[2].Trim().Trim('"').Trim("'")
        if ($null -eq [Environment]::GetEnvironmentVariable($rdDemoEnvName, 'Process')) { [Environment]::SetEnvironmentVariable($rdDemoEnvName, $rdDemoEnvValue, 'Process') }
    }
}
$env:APP_ENV = 'development'
$env:JTB_DEMO_MODE = 'true'
$env:JTB_HOST = '127.0.0.1'
$env:JTB_PORT = [string]$Port
$rdDemoLogs = Join-Path $rdDemoApp 'logs'
$rdDemoRuntime = Join-Path $rdDemoApp 'runtime'
New-Item -ItemType Directory -Force -Path $rdDemoLogs,$rdDemoRuntime | Out-Null
$rdDemoProcess = Start-Process -FilePath $rdDemoPython -ArgumentList @('-m','src.main') -WorkingDirectory $rdDemoApp -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $rdDemoLogs 'backend-startup.stdout.log') -RedirectStandardError (Join-Path $rdDemoLogs 'backend-startup.stderr.log')
$rdDemoRecords = @()
$rdDemoProcessFile = Join-Path $rdDemoRuntime 'local-services.json'
if (Test-Path -LiteralPath $rdDemoProcessFile) { $rdDemoRecords = @(Get-Content -LiteralPath $rdDemoProcessFile -Raw | ConvertFrom-Json) }
$rdDemoRecords += @{ pid=$rdDemoProcess.Id; module='src.main'; port=$Port }
$rdDemoRecords | ConvertTo-Json | Set-Content -LiteralPath $rdDemoProcessFile -Encoding UTF8
$rdDemoReady = $false
for ($rdDemoAttempt = 0; $rdDemoAttempt -lt 30; $rdDemoAttempt++) {
    try {
        $rdDemoIdentity = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/current-user" -TimeoutSec 1
        if ($rdDemoIdentity.demo_mode -and $rdDemoIdentity.authenticated) { $rdDemoReady = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (-not $rdDemoReady) { throw "服务尚未就绪，请检查 $rdDemoLogs/backend-startup.stderr.log。" }
Write-Host "研发管理平台演示版已启动：http://127.0.0.1:$Port/"
Write-Host '默认演示负责人，可在页面切换角色。停止服务：.\stop.ps1'
