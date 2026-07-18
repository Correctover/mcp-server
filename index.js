#!/usr/bin/env node
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const platform = process.platform;
const arch = process.arch;
const platformMap = { linux: 'linux', darwin: 'darwin', win32: 'windows' };
const archMap = { x64: 'amd64', arm64: 'arm64' };

const binaryName = `correctover-mcp-server-${platformMap[platform]}-${archMap[arch]}${platform === 'win32' ? '.exe' : ''}`;
const binPath = path.join(__dirname, 'bin', binaryName);

if (!fs.existsSync(binPath)) {
  console.error(`Binary not found at ${binPath}. Run postinstall to download.`);
  process.exit(1);
}

const child = spawn(binPath, process.argv.slice(2), {
  stdio: ['inherit', 'inherit', 'inherit']
});

child.on('exit', (code) => process.exit(code || 0));
