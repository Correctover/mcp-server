#!/usr/bin/env bash
# Correctover MCP Server — 一键启动全部服务
# 用法: bash start-all.sh

set -e

echo "=== Correctover MCP Server Startup ==="
cd "$(dirname "$0")"

# 1. Kill any stale processes
echo "[1/4] Cleaning up stale processes..."
taskkill -f -im node.exe 2>/dev/null || true
sleep 2

# 2. Start MCP Server
echo "[2/4] Starting MCP Server on port 8080..."
node smithery-server.js > /c/Users/Administrator/Desktop/server_log.txt 2>&1 &
sleep 3
if curl -s http://localhost:8080/health > /dev/null 2>&1; then
    echo "  ✅ Server health OK"
else
    echo "  ❌ Server failed to start"
    exit 1
fi

# 3. Start SSH Tunnel
echo "[3/4] Starting SSH tunnel (localhost.run)..."
# Kill stale SSH tunnels
ps aux 2>/dev/null | grep "localhost.run" | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null || true
sleep 1

ssh -o ServerAliveInterval=30 -o StrictHostKeyChecking=no -o ExitOnForwardFailure=yes \
    -R 80:localhost:8080 nokey@localhost.run > /c/Users/Administrator/Desktop/tunnel_url.txt 2>&1 &
sleep 8

TUNNEL_URL=$(grep -oP 'https://[a-z0-9]+\.lhr\.life' /c/Users/Administrator/Desktop/tunnel_url.txt | head -1)
if [ -n "$TUNNEL_URL" ]; then
    echo "  ✅ Tunnel URL: $TUNNEL_URL"
else
    echo "  ❌ Tunnel failed - check /c/Users/Administrator/Desktop/tunnel_url.txt"
fi

# 4. Start Watchdog
echo "[4/4] Starting watchdog..."
powershell.exe -Command "Start-Process -WindowStyle Hidden -FilePath powershell.exe -ArgumentList '-File C:\d\workspace\correctover\watchdog.ps1'" 2>/dev/null
echo "  ✅ Watchdog started"

echo ""
echo "=== Summary ==="
echo "Server:   http://localhost:8080"
echo "Health:   http://localhost:8080/health"
echo "MCP:      POST http://localhost:8080/mcp"
echo "Tunnel:   $TUNNEL_URL"
echo "Smithery: https://smithery.ai/servers/correctover/mcp-server/releases"
echo "Logs:     /c/Users/Administrator/Desktop/server_log.txt"
echo ""
echo "To check tunnel URL later: grep -oP 'https://[a-z0-9]+\.lhr\.life' /c/Users/Administrator/Desktop/tunnel_url.txt"
