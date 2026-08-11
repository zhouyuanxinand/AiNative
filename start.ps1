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
$stdoutLog = Join-Path $logDir "backend-startup.stdout.log"
$stderrLog = Join-Path $logDir "backend-startup.stderr.log"

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
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

if (-not $env:APP_ENV) { $env:APP_ENV = "development" }
Import-DotEnv (Join-Path $serviceRoot ".env")

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path -LiteralPath $venvDir)) {
    Write-Host "[start] 创建虚拟环境 $venvDir"
    py -3.13 -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { python -m venv $venvDir }
}

Write-Host "[start] 安装依赖"
& $venvPython -m pip install -q -r $requirements

$port = if ($env:JTB_PORT) { [int]$env:JTB_PORT } else { 18130 }
Write-Host "[start] 启动后端 http://127.0.0.1:$port (APP_ENV=$env:APP_ENV)"

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $venvPython
$psi.Arguments = "-m uvicorn src.main:app --host 127.0.0.1 --port $port"
$psi.WorkingDirectory = $appDir
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true
$proc = [System.Diagnostics.Process]::Start($psi)
$proc.EnableRaisingEvents = $true

$sb = {
    param($sender, $e)
    if ($sender.HasExited) { return }
}
Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -Action {
    if ($EventArgs.Data) { Add-Content -LiteralPath $stdoutLog -Value $EventArgs.Data -Encoding UTF8 }
} | Out-Null
Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived -Action {
    if ($EventArgs.Data) { Add-Content -LiteralPath $stderrLog -Value $EventArgs.Data -Encoding UTF8 }
} | Out-Null
$proc.BeginOutputReadLine()
$proc.BeginErrorReadLine()

Start-Sleep -Seconds 2
if ($proc.HasExited) {
    Write-Warning "[start] 后端提前退出；诊断日志："
    Write-Warning "  $stdoutLog"
    Write-Warning "  $stderrLog"
    exit $proc.ExitCode
}

Write-Host "[start] 后端 PID=$($proc.Id)，日志："
Write-Host "  $stdoutLog"
Write-Host "  $stderrLog"
Write-Host "[start] 停止服务请运行 .\stop.ps1"
