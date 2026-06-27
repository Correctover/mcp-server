"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.ServerManager = void 0;
const vscode = __importStar(require("vscode"));
const child_process_1 = require("child_process");
const path = __importStar(require("path"));
const fs = __importStar(require("fs"));
const mcpClient_1 = require("./mcpClient");
class ServerManager {
    process = null;
    client = null;
    _state = 'stopped';
    _error = '';
    outputChannel;
    _onStatusChange = new Set();
    constructor(outputChannel) {
        this.outputChannel = outputChannel;
    }
    get state() {
        return this._state;
    }
    get mcpClient() {
        return this.client;
    }
    onStatusChange(cb) {
        this._onStatusChange.add(cb);
        return { dispose: () => this._onStatusChange.delete(cb) };
    }
    notifyState() {
        const status = {
            state: this._state,
            pid: this.process?.pid,
            error: this._error || undefined,
        };
        this._onStatusChange.forEach(cb => cb(status));
    }
    /** Find the Correctover binary. */
    findBinary() {
        // Check configured path first
        const configPath = vscode.workspace.getConfiguration('correctover').get('serverPath');
        if (configPath && fs.existsSync(configPath)) {
            return configPath;
        }
        // Known locations relative to extension
        const extDir = __dirname; // .../vscode-extension/out/
        const projectRoot = path.resolve(extDir, '..', '..');
        const candidates = [
            path.join(projectRoot, 'correctover-server.exe'),
            path.join(projectRoot, 'correctover-server'),
            path.join(projectRoot, 'bin', 'correctover-server.exe'),
            path.join(projectRoot, 'bin', 'correctover-server'),
        ];
        for (const c of candidates) {
            if (fs.existsSync(c))
                return c;
        }
        // Search PATH
        const isWin = process.platform === 'win32';
        const name = isWin ? 'correctover-server.exe' : 'correctover-server';
        const pathDirs = (process.env.PATH || '').split(path.delimiter);
        for (const dir of pathDirs) {
            const full = path.join(dir, name);
            try {
                if (fs.existsSync(full))
                    return full;
            }
            catch { /* ignore */ }
        }
        return undefined;
    }
    /** Build the environment variables for the child process from VS Code settings. */
    buildEnv() {
        const config = vscode.workspace.getConfiguration('correctover');
        const env = { ...process.env };
        const keyMap = {
            openaiKey: 'OPENAI_API_KEY',
            anthropicKey: 'ANTHROPIC_API_KEY',
            deepseekKey: 'DEEPSEEK_API_KEY',
            moonshotKey: 'MOONSHOT_API_KEY',
            zhipuKey: 'ZHIPU_API_KEY',
            dashscopeKey: 'DASHSCOPE_API_KEY',
            siliconflowKey: 'SILICONFLOW_API_KEY',
            groqKey: 'GROQ_API_KEY',
            togetherKey: 'TOGETHER_API_KEY',
        };
        for (const [setting, envVar] of Object.entries(keyMap)) {
            const val = config.get(setting);
            if (val && val.trim()) {
                env[envVar] = val.trim();
            }
        }
        // Base URL overrides
        const urlMap = {
            openaiBaseUrl: 'OPENAI_BASE_URL',
            anthropicBaseUrl: 'ANTHROPIC_BASE_URL',
            deepseekBaseUrl: 'DEEPSEEK_BASE_URL',
        };
        for (const [setting, envVar] of Object.entries(urlMap)) {
            const val = config.get(setting);
            if (val && val.trim()) {
                env[envVar] = val.trim();
            }
        }
        return env;
    }
    /** Start the Correctover MCP server. */
    async start() {
        if (this._state === 'running' || this._state === 'starting') {
            this.outputChannel.appendLine('[correctover] Server is already running or starting');
            return;
        }
        const binary = this.findBinary();
        if (!binary) {
            this._state = 'error';
            this._error = 'Correctover binary not found. Set "correctover.serverPath" or build the Go server first.';
            this.outputChannel.appendLine(`[correctover] ERROR: ${this._error}`);
            this.notifyState();
            throw new Error(this._error);
        }
        this._state = 'starting';
        this._error = '';
        this.notifyState();
        return new Promise((resolve, reject) => {
            try {
                const env = this.buildEnv();
                this.outputChannel.appendLine(`[correctover] Starting server: ${binary}`);
                this.outputChannel.appendLine(`[correctover] Providers configured: ${Object.keys(env).filter(k => k.endsWith('_API_KEY')).length}`);
                this.process = (0, child_process_1.spawn)(binary, [], {
                    env,
                    stdio: ['pipe', 'pipe', 'pipe'],
                });
                const pid = this.process.pid;
                this.outputChannel.appendLine(`[correctover] Server started (PID: ${pid})`);
                // Pipe stderr to output channel
                this.process.stderr?.on('data', (data) => {
                    this.outputChannel.append(data.toString('utf-8'));
                });
                // Pipe stdout to MCP client
                if (!this.process.stdout || !this.process.stdin) {
                    throw new Error('No stdio on child process');
                }
                this.client = new mcpClient_1.MCPClient({
                    stdin: this.process.stdin,
                    stdout: this.process.stdout,
                });
                // Initialize MCP connection
                this.client
                    .initialize()
                    .then(() => {
                    this._state = 'running';
                    this.outputChannel.appendLine('[correctover] Server initialized and ready');
                    this.notifyState();
                    resolve();
                })
                    .catch((err) => {
                    this._state = 'error';
                    this._error = `Initialization failed: ${err.message}`;
                    this.outputChannel.appendLine(`[correctover] ERROR: ${this._error}`);
                    this.notifyState();
                    reject(err);
                });
                // Handle process exit
                this.process.on('exit', (code, signal) => {
                    this.outputChannel.appendLine(`[correctover] Server exited (code: ${code}, signal: ${signal})`);
                    this.cleanup();
                    if (this._state === 'running') {
                        this._state = 'stopped';
                        this.notifyState();
                    }
                });
                this.process.on('error', (err) => {
                    this.outputChannel.appendLine(`[correctover] Process error: ${err.message}`);
                    this._state = 'error';
                    this._error = err.message;
                    this.cleanup();
                    this.notifyState();
                    reject(err);
                });
            }
            catch (err) {
                this._state = 'error';
                this._error = err.message;
                this.notifyState();
                reject(err);
            }
        });
    }
    /** Stop the Correctover MCP server. */
    async stop() {
        if (!this.process) {
            this.outputChannel.appendLine('[correctover] No server running');
            return;
        }
        this.outputChannel.appendLine('[correctover] Stopping server...');
        this.process.kill('SIGTERM');
        // Wait up to 3s for graceful shutdown
        await new Promise((resolve) => {
            const timeout = setTimeout(() => {
                if (this.process) {
                    this.outputChannel.appendLine('[correctover] Force killing server');
                    this.process.kill('SIGKILL');
                }
                resolve();
            }, 3000);
            if (this.process) {
                this.process.on('exit', () => {
                    clearTimeout(timeout);
                    resolve();
                });
            }
            else {
                clearTimeout(timeout);
                resolve();
            }
        });
        this.cleanup();
        this._state = 'stopped';
        this.notifyState();
        this.outputChannel.appendLine('[correctover] Server stopped');
    }
    /** Restart the server. */
    async restart() {
        await this.stop();
        await this.start();
    }
    cleanup() {
        if (this.client) {
            this.client.dispose();
            this.client = null;
        }
        this.process = null;
    }
    dispose() {
        this.cleanup();
        if (this.process) {
            this.process.kill('SIGKILL');
            this.process = null;
        }
        this._state = 'stopped';
        this._onStatusChange.clear();
    }
}
exports.ServerManager = ServerManager;
//# sourceMappingURL=serverManager.js.map