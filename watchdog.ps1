# Correctover MCP Server Watchdog
# 每 60 秒检查一次服务器和 SSH 隧道，挂了自动重启
# 用法: PowerShell -File watchdog.ps1 (后台运行)

$ServerDir = "C:\d\workspace\correctover"
$LogFile = "C:\d\workspace\correctover\watchdog.log"
$ServerLog = "C:\Users\Administrator\Desktop\server_log.txt"
$TunnelLog = "C:\Users\Administrator\Desktop\tunnel_url.txt"
$CheckInterval = 60  # seconds

function Log {
    param([string]$Msg)
    $Time = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$Time $Msg" | Out-File -FilePath $LogFile -Append -Encoding UTF8
    Write-Host "$Time $Msg"
}

function Start-Server {
    $proc = Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "smithery-server" }
    if (-not $proc) {
        Log "Server DOWN - starting..."
        Start-Process -FilePath "node" -ArgumentList "smithery-server.js" -WorkingDirectory $ServerDir -WindowStyle Hidden -RedirectStandardOutput $ServerLog
        Start-Sleep -Seconds 3
        Log "Server started"
    } else {
        Log "Server OK (PID $($proc.Id))"
    }
}

function Start-Tunnel {
    # Check if any SSH tunnel to localhost.run exists
    $sshProc = Get-WmiObject Win32_Process -Filter "Name='ssh.exe' AND CommandLine LIKE '%localhost.run%'" -ErrorAction SilentlyContinue
    if (-not $sshProc) {
        Log "Tunnel DOWN - starting..."
        $urlFile = "C:\Users\Administrator\Desktop\tunnel_url.txt"
        Start-Process -FilePath "C:\Program Files\Git\usr\bin\ssh.exe" -ArgumentList "-o ServerAliveInterval=30 -o StrictHostKeyChecking=no -o ExitOnForwardFailure=yes -R 80:localhost:8080 nokey@localhost.run" -WindowStyle Hidden -RedirectStandardOutput $urlFile
        Start-Sleep -Seconds 10
        Log "Tunnel started - check $urlFile for URL"
    } else {
        $pid = $sshProc.ProcessId
        Log "Tunnel OK (PID $pid)"
    }
}

function Test-Endpoint {
    try {
        $result = Invoke-WebRequest -Uri "http://localhost:8080/health" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        if ($result.Content -match '"status":"ok"') {
            return $true
        }
    } catch {}
    return $false
}

Log "=== Watchdog started (interval: ${CheckInterval}s) ==="

while ($true) {
    # 1. Check endpoint locally
    $ok = Test-Endpoint
    if (-not $ok) {
        Log "Local endpoint UNREACHABLE"
        Start-Server
        Start-Sleep -Seconds 5
    }

    # 2. Ensure server process is running
    Start-Server

    # 3. Ensure tunnel is running
    Start-Tunnel

    Start-Sleep -Seconds $CheckInterval
}
