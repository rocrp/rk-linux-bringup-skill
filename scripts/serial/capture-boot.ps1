# capture-boot.ps1 —— 纯监听串口：抓启动日志，固定时长后落盘退出（绝不写串口）
#
# 用途：上电/复位时抓完整启动日志。**先启动本脚本，再给板子上电**，
#       否则会错过 DDR 与 U-Boot 的版本串。
#
# 用法：
#   pwsh -File capture-boot.ps1 -Port COM11 -Baud 1500000 -Seconds 60 -Log .\boot.log
#   pwsh -File capture-boot.ps1 -ListPorts
#
# 依赖：无（.NET SerialPort）
# 注意：同一 COM 口只能一个程序打开；先关掉串口助手。
param(
    [string]$Port = "",
    [int]$Baud = 1500000,
    [int]$Seconds = 60,
    [string]$Log = ".\boot.log",
    [switch]$NoEcho,
    [switch]$ListPorts
)

$ErrorActionPreference = "Stop"
$latin1 = [System.Text.Encoding]::GetEncoding(28591)

if ($ListPorts) {
    [System.IO.Ports.SerialPort]::GetPortNames() | ForEach-Object { $_ }
    exit 0
}
if ([string]::IsNullOrWhiteSpace($Port)) {
    Write-Error "必须给 -Port（可用 -ListPorts 查看）"
    exit 2
}

$logPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Log)
$dir = Split-Path -Parent $logPath
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

$sp = New-Object System.IO.Ports.SerialPort($Port, $Baud, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
$sp.Handshake = [System.IO.Ports.Handshake]::None
$sp.ReadBufferSize = 4194304
$sp.ReadTimeout = 100
$sp.DtrEnable = $true
$sp.RtsEnable = $true

$deadline = (Get-Date).AddSeconds($Seconds)
$total = 0
$buf = New-Object byte[] 65536
$stream = $null

try {
    $stream = [System.IO.File]::Open($logPath, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
    $sp.Open()
    Write-Host ("[capture] {0} @ {1} 8N1；监听 {2}s → {3}" -f $Port, $Baud, $Seconds, $logPath)
    Write-Host "[capture] 现在给板子上电（或复位）。"

    while ((Get-Date) -lt $deadline) {
        $n = $sp.BytesToRead
        while ($n -gt 0) {
            $got = $sp.Read($buf, 0, [Math]::Min($n, $buf.Length))
            if ($got -le 0) { break }
            $stream.Write($buf, 0, $got)
            $total += $got
            if (-not $NoEcho) { [Console]::Out.Write($latin1.GetString($buf, 0, $got)) }
            $n = $sp.BytesToRead
        }
        Start-Sleep -Milliseconds 20
    }
}
finally {
    try { if ($sp.IsOpen) { $sp.Close() } } catch { }
    $sp.Dispose()
    if ($stream) { $stream.Flush(); $stream.Dispose() }
    Write-Host ("[capture] 结束：共 {0} B → {1}" -f $total, $logPath)
    if ($total -eq 0) {
        Write-Host "[capture] 一个字节都没收到：先查电平（TTL/RS-232）、接线（TX/RX 交叉）、波特率、端口是否选对。" -ForegroundColor Yellow
    }
}
