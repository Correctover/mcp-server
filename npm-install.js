const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');

const version = '1.0.2';
const repo = 'Correctover/mcp-server';

const platform = process.platform;
const arch = process.arch;

const platformMap = { linux: 'linux', darwin: 'darwin', win32: 'windows' };
const archMap = { x64: 'amd64', arm64: 'arm64' };

const osName = platformMap[platform];
const archName = archMap[arch];

if (!osName || !archName) {
  console.error(`Unsupported platform: ${platform}/${arch}`);
  process.exit(1);
}

const binaryName = `correctover-mcp-server-${osName}-${archName}${platform === 'win32' ? '.exe' : ''}`;
const url = `https://github.com/${repo}/releases/download/v${version}/${binaryName}`;
const binDir = path.join(__dirname, 'bin');
const binPath = path.join(binDir, binaryName);

if (!fs.existsSync(binDir)) fs.mkdirSync(binDir, { recursive: true });

console.log(`Downloading ${binaryName} from GitHub Releases...`);

https.get(url, (res) => {
  if (res.statusCode === 302 || res.statusCode === 301) {
    https.get(res.headers.location, downloadBinary);
  } else {
    downloadBinary(res);
  }
}).on('error', (err) => {
  console.error('Download failed:', err.message);
  process.exit(1);
});

function downloadBinary(res) {
  if (res.statusCode !== 200) {
    console.error(`Failed to download binary (HTTP ${res.statusCode})`);
    process.exit(1);
  }
  const file = fs.createWriteStream(binPath);
  res.pipe(file);
  file.on('finish', () => {
    file.close();
    fs.chmodSync(binPath, 0o755);
    console.log(`Binary downloaded to ${binPath}`);
  });
}
