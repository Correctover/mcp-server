import * as vscode from 'vscode';
import { spawn, ChildProcess } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import { MCPClient } from './mcpClient';

export type ServerState = 'stopped' | 'starting' | 'running' | 'error';

export interface ServerStatus {
  state: ServerState;
  pid?: number;
  error?: string;
}

export class ServerManager {
  private process: ChildProcess | null = null;
  private client: MCPClient | null = null;
  private _state: ServerState = 'stopped';
  private _error = '';
  private outputChannel: vscode.OutputChannel;
  private _onStatusChange = new Set<(status: ServerStatus) => void>();

  constructor(outputChannel: vscode.OutputChannel) {
    this.outputChannel = outputChannel;
  }

  get state(): ServerState {
    return this._state;
  }

  get mcpClient(): MCPClient | null {
    return this.client;
  }

  onStatusChange(cb: (status: ServerStatus) => void): vscode.Disposable {
    this._onStatusChange.add(cb);
    return { dispose: () => this._onStatusChange.delete(cb) };
  }

  private notifyState(): void {
    const status: ServerStatus = {
      state: this._state,
      pid: this.process?.pid,
      error: this._error || undefined,
    };
    this._onStatusChange.forEach(cb => cb(status));
  }

  /** Find the Correctover binary. */
  private findBinary(): string | undefined {
    // Check configured path first
    const configPath = vscode.workspace.getConfiguration('correctover').get<string>('serverPath');
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
      if (fs.existsSync(c)) return c;
    }

    // Search PATH
    const isWin = process.platform === 'win32';
    const name = isWin ? 'correctover-server.exe' : 'correctover-server';
    const pathDirs = (process.env.PATH || '').split(path.delimiter);
    for (const dir of pathDirs) {
      const full = path.join(dir, name);
      try {
        if (fs.existsSync(full)) return full;
      } catch { /* ignore */ }
    }

    return undefined;
  }

  /** Build the environment variables for the child process from VS Code settings. */
  private buildEnv(): Record<string, string> {
    const config = vscode.workspace.getConfiguration('correctover');
    const env: Record<string, string> = { ...process.env as Record<string, string> };

    const keyMap: Record<string, string> = {
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
      const val = config.get<string>(setting);
      if (val && val.trim()) {
        env[envVar] = val.trim();
      }
    }

    // Base URL overrides
    const urlMap: Record<string, string> = {
      openaiBaseUrl: 'OPENAI_BASE_URL',
      anthropicBaseUrl: 'ANTHROPIC_BASE_URL',
      deepseekBaseUrl: 'DEEPSEEK_BASE_URL',
    };
    for (const [setting, envVar] of Object.entries(urlMap)) {
      const val = config.get<string>(setting);
      if (val && val.trim()) {
        env[envVar] = val.trim();
      }
    }

    return env;
  }

  /** Start the Correctover MCP server. */
  async start(): Promise<void> {
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

    return new Promise<void>((resolve, reject) => {
      try {
        const env = this.buildEnv();
        this.outputChannel.appendLine(`[correctover] Starting server: ${binary}`);
        this.outputChannel.appendLine(`[correctover] Providers configured: ${Object.keys(env).filter(k => k.endsWith('_API_KEY')).length}`);

        this.process = spawn(binary, [], {
          env,
          stdio: ['pipe', 'pipe', 'pipe'],
        });

        const pid = this.process.pid;
        this.outputChannel.appendLine(`[correctover] Server started (PID: ${pid})`);

        // Pipe stderr to output channel
        this.process.stderr?.on('data', (data: Buffer) => {
          this.outputChannel.append(data.toString('utf-8'));
        });

        // Pipe stdout to MCP client
        if (!this.process.stdout || !this.process.stdin) {
          throw new Error('No stdio on child process');
        }

        this.client = new MCPClient({
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
      } catch (err) {
        this._state = 'error';
        this._error = (err as Error).message;
        this.notifyState();
        reject(err);
      }
    });
  }

  /** Stop the Correctover MCP server. */
  async stop(): Promise<void> {
    if (!this.process) {
      this.outputChannel.appendLine('[correctover] No server running');
      return;
    }

    this.outputChannel.appendLine('[correctover] Stopping server...');
    this.process.kill('SIGTERM');

    // Wait up to 3s for graceful shutdown
    await new Promise<void>((resolve) => {
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
      } else {
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
  async restart(): Promise<void> {
    await this.stop();
    await this.start();
  }

  private cleanup(): void {
    if (this.client) {
      this.client.dispose();
      this.client = null;
    }
    this.process = null;
  }

  dispose(): void {
    this.cleanup();
    if (this.process) {
      this.process.kill('SIGKILL');
      this.process = null;
    }
    this._state = 'stopped';
    this._onStatusChange.clear();
  }
}
