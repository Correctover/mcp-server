#!/usr/bin/env node
// Optional: download prebuilt Go binary for stdio mode
// Gracefully skips in hosted environments (Smithery, etc.)

const fs = require('fs');
const path = require('path');
const https = require('https');

// Skip in hosted environments
if (process.env.SMITHERY || process.env.VERCEL || process.env.NETLIFY || process.env.RENDER) {
  console.log('[correctover] Hosted environment detected, skipping binary download');
  process.exit(0);
}

const version = '1.0.5';
const repo = 'Correctover/mcp-server';
const platform = process.platform;
const arch = process.arch;

const platformMap = { linux: 'linux', darwin: 'darwin', win32: 'windows' };
const archMap = { x64: 'amd64', arm64: 'arm64' };
const osName = platformMap[platform];
const archName = archMap[arch];

if (!osName || !archName) {
  console.log(`[correctover] Unsupported platform ${platform}/${arch}, using Node.js server`);
  process.exit(0);
}

const binaryName = `correctover-mcp-server-${osName}-${archName}${platform === 'win32' ? '.exe' : ''}`;
const url = `https://github.com/${repo}/releases/download/v${version}/${binaryName}`;
const binDir = path.join(__dirname, 'bin');
const binPath = path.join(binDir, binaryName);

try {
  if (!fs.existsSync(binDir)) fs.mkdirSync(binDir, { recursive: true });
  console.log(`[correctover] Downloading ${binaryName}...`);

  https.get(url, (res) => {
    if (res.statusCode === 302 || res.statusCode === 301) {
      https.get(res.headers.location, doDownload).on('error', warnSkip);
    } else {
      doDownload(res);
    }
  }).on('error', warnSkip);
} catch (err) {
  console.log(`[correctover] Binary download skipped: ${err.message}`);
  console.log('[correctover] Node.js server available via smithery-server.js');
}

function warnSkip(err) {
  console.log(`[correctover] Binary download skipped: ${err.message}`);
  console.log('[correctover] Node.js server available via smithery-server.js');
}

function doDownload(res) {
  if (res.statusCode !== 200) {
    console.log(`[correctover] Binary not available (HTTP ${res.statusCode}), using Node.js server`);
    res.resume();
    return;
  }
  const file = fs.createWriteStream(binPath);
  res.pipe(file);
  file.on('finish', () => {
    file.close();
    fs.chmodSync(binPath, 0o755);
    console.log(`[correctover] Binary ready: ${binPath}`);
  });
  file.on('error', warnSkip);
}
