#!/usr/bin/env node
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const platform = process.platform;
const arch = process.arch;
const platformMap = { linux: 'linux', darwin: 'darwin', win32: 'windows' };
const archMap = { x64: 'amd64', arm64: 'arm64' };

const binaryName = `correctover-mcp-server-${platformMap[platform]}-${archMap[arch]}${platform === 'win32' ? '.exe' : ''}`;

// Try multiple paths for the binary
const searchPaths = [
  path.join(__dirname, 'bin', binaryName),
  path.join(__dirname, 'node_modules', 'correctover-mcp-server', 'bin', binaryName),
  path.join(process.cwd(), 'bin', binaryName),
];

let binPath = null;
for (const p of searchPaths) {
  if (fs.existsSync(p)) {
    binPath = p;
    break;
  }
}

if (!binPath) {
  console.error(`[correctover] Binary not found. Searched: ${searchPaths.join(', ')}`);
  console.error(`[correctover] Platform: ${platform}/${arch}, expected: ${binaryName}`);
  process.exit(1);
}

// Ensure binary is executable
try { fs.chmodSync(binPath, 0o755); } catch(e) {}

console.error(`[correctover] Starting binary: ${binPath}`);

const child = spawn(binPath, process.argv.slice(2), {
  stdio: ['inherit', 'inherit', 'inherit'],
  env: { ...process.env }
});

child.on('error', (err) => {
  console.error(`[correctover] Binary error: ${err.message}`);
  process.exit(1);
});

child.on('exit', (code) => {
  process.exit(code || 0);
});
