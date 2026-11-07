# serial-console.ps1 —— 独占串口：收字节落盘 + 按命令文件注入（Windows 开发机）
#
# 为什么需要它：同一个 COM 口同一时刻只能被一个程序打开。用一个进程独占，
#  既可以持续抓日志，又能通过"往命令文件追加一行"来发命令，不用第二个程序抢口。
#
# 用法：
#   pwsh -File serial-console.ps1 -Port COM11 -Baud 1500000 -Log .\serial.log -CmdFile .\cmd.txt -Seconds 3600
#   # 另开窗口发命令（一行一条）：
#   Add-Content .\cmd.txt 'printenv'
#   # 读日志：
#   Get-Content .\serial.log -Tail 40
#
# 命令文件语法（发送后默认自动补 CR）：
#   普通行                     → 原样发送 + CR
#   !raw=<内容>                → 原样发送，不补 CR（例：!raw=\x03）
#   !spam=<间隔ms>:<时长ms>    → 按间隔喷 CTRL-C（打断 U-Boot autoboot）
#   !wait=<ms>                 → 暂停发送，期间照常收字节
#   转义：\xNN / \r / \n，其余字面
#
# 依赖：无（.NET SerialPort；PowerShell 5.1 / 7 均可）
# 注意：
#   * 打开失败通常是别的串口软件还开着，或需要更高权限（部分沙箱会拒绝 COM 访问）。
#   * 日志按 500 ms flush；进程被杀最多丢半秒。
#   * 只发命令文件里的内容，不会自己发字符。
param(
    [string]$Port = "",
    [int]$Baud = 1500000,
    [string]$Log = ".\serial.log",
    [string]$CmdFile = ".\serial-cmd.txt",
    [int]$Seconds = 3600,
    [switch]$NoEcho,
    [switch]$ListPorts
)

$ErrorActionPreference = "Stop"
$latin1 = [System.Text.Encoding]::GetEncoding(28591)   # 字节保真

if ($ListPorts) {
    [System.IO.Ports.SerialPort]::GetPortNames() | ForEach-Object { $_ }
    exit 0
}
if ([string]::IsNullOrWhiteSpace($Port)) {
    Write-Error "必须给 -Port（可用 -ListPorts 查看可用端口）"
    exit 2
}

$logPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Log)
$cmdPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($CmdFile)
foreach ($p in @($logPath, $cmdPath)) {
    $dir = Split-Path -Parent $p
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
}
if (-not (Test-Path $cmdPath)) { New-Item -ItemType File -Force -Path $cmdPath | Out-Null }

function Expand-Escapes([string]$s) {
    $out = New-Object System.Collections.Generic.List[byte]
    $i = 0
    while ($i -lt $s.Length) {
        $c = $s[$i]
        if ($c -eq '\' -and ($i + 1) -lt $s.Length) {
            $n = $s[$i + 1]
            if ($n -eq 'x' -and ($i + 3) -lt $s.Length) {
                $hex = $s.Substring($i + 2, 2)
                try { $out.Add([Convert]::ToByte($hex, 16)); $i += 4; continue } catch { }
            }
            if ($n -eq 'r') { $out.Add(0x0D); $i += 2; continue }
            if ($n -eq 'n') { $out.Add(0x0A); $i += 2; continue }
        }
        $out.Add([byte][char]$c); $i++
    }
    return $out.ToArray()
}

$sp = New-Object System.IO.Ports.SerialPort($Port, $Baud, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
$sp.Handshake = [System.IO.Ports.Handshake]::None
$sp.ReadBufferSize = 4194304
$sp.WriteBufferSize = 4096
$sp.ReadTimeout = 100
$sp.WriteTimeout = 1000
$sp.DtrEnable = $true
$sp.RtsEnable = $true
$sp.Encoding = $latin1

$deadline = (Get-Date).AddSeconds($Seconds)
$rxTotal = 0
$txItems = 0
$buf = New-Object byte[] 65536
$logStream = $null
$lastFlush = Get-Date
$spamUntil = [datetime]::MinValue
$spamNext = [datetime]::MinValue
$spamInterval = 100

$cmdStream = [System.IO.File]::Open($cmdPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
$cmdReader = New-Object System.IO.StreamReader($cmdStream, [System.Text.Encoding]::UTF8)

try {
    $logStream = [System.IO.File]::Open($logPath, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
    $sp.Open()
    Write-Host ("[serial] {0} @ {1} 8N1 打开成功；日志={2}；命令={3}；超时 {4}s" -f $Port, $Baud, $logPath, $cmdPath, $Seconds)

    $drainRx = {
        $n = $sp.BytesToRead
        while ($n -gt 0) {
            $got = $sp.Read($buf, 0, [Math]::Min($n, $buf.Length))
            if ($got -le 0) { break }
            $logStream.Write($buf, 0, $got)
            $script:rxTotal += $got
            if (-not $NoEcho) {
                [Console]::Out.Write($latin1.GetString($buf, 0, $got))
                [Console]::Out.Flush()
            }
            $n = $sp.BytesToRead
        }
    }

    while ((Get-Date) -lt $deadline) {
        & $drainRx

        while (-not $cmdReader.EndOfStream) {
            $line = $cmdReader.ReadLine()
            if ($null -eq $line) { break }
            $now = Get-Date
            if ($line.StartsWith('!spam=')) {
                $parts = $line.Substring(6).Split(':')
                $spamInterval = [int]$parts[0]
                $ms = if ($parts.Length -gt 1) { [int]$parts[1] } else { 5000 }
                $spamUntil = $now.AddMilliseconds($ms)
                $spamNext = $now
                Write-Host ("[serial] SPAM 每 {0} ms 发 ^C，持续 {1} ms" -f $spamInterval, $ms)
                continue
            }
            if ($line.StartsWith('!wait=')) {
                $ms = [int]$line.Substring(6)
                $waitUntil = (Get-Date).AddMilliseconds($ms)
                while ((Get-Date) -lt $waitUntil) {
                    & $drainRx
                    $nw = Get-Date
                    if ($nw -lt $spamUntil -and $nw -ge $spamNext) {
                        $sp.Write([byte[]]@(0x03), 0, 1)
                        $spamNext = $nw.AddMilliseconds($spamInterval)
                    }
                    if (($nw - $lastFlush).TotalMilliseconds -ge 500) {
                        $logStream.Flush(); $lastFlush = $nw
                    }
                    Start-Sleep -Milliseconds 20
                }
                Write-Host ("[serial] WAIT {0} ms" -f $ms)
                continue
            }
            $raw = $false
            if ($line.StartsWith('!raw=')) { $raw = $true; $line = $line.Substring(5) }
            $out = New-Object System.Collections.Generic.List[byte]
            $esc = Expand-Escapes $line
            if ($null -ne $esc) { $out.AddRange([byte[]]$esc) }
            if (-not $raw) { $out.Add([byte]0x0D) }
            $arr = $out.ToArray()
            $sp.Write($arr, 0, $arr.Length)
            $txItems++
            Write-Host ("[serial] TX #{0}  {1}  ({2} B)" -f $txItems, ($line -replace '\\x03', '<^C>'), $arr.Length)
        }

        $now = Get-Date
        if ($now -lt $spamUntil -and $now -ge $spamNext) {
            $sp.Write([byte[]]@(0x03), 0, 1)
            $spamNext = $now.AddMilliseconds($spamInterval)
        }
        if (($now - $lastFlush).TotalMilliseconds -ge 500) {
            $logStream.Flush(); $lastFlush = $now
        }
        Start-Sleep -Milliseconds 20
    }
}
finally {
    try { if ($sp.IsOpen) { $sp.Close() } } catch { }
    $sp.Dispose()
    $cmdReader.Dispose()
    if ($logStream) { $logStream.Flush(); $logStream.Dispose() }
    Write-Host ("[serial] 退出：收 {0} B，发 {1} 条，日志 {2}" -f $rxTotal, $txItems, $logPath)
}
