import * as vscode from 'vscode';
import { Writable } from 'stream';

// --- JSON-RPC types matching the Go MCP server ---
export interface MCPRequest {
  jsonrpc: '2.0';
  id: number;
  method: string;
  params?: unknown;
}

export interface MCPResponse {
  jsonrpc: '2.0';
  id: number;
  result?: unknown;
  error?: { code: number; message: string };
}

export interface Tool {
  name: string;
  description: string;
  inputSchema: { type: string; properties: Record<string, unknown>; required?: string[] };
}

export interface HealthResult {
  raw: string;
}

export interface StatsResult {
  raw: string;
}

export interface ValidationReport {
  provider: string;
  latencyMs: number;
  validationPassed: boolean;
  validationDetails: Record<string, boolean>;
  failoverCount: number;
}

/**
 * MCP Client — communicates with the Correctover Go server via stdio JSON-RPC.
 */
export class MCPClient {
  private requestId = 1;
  private pending = new Map<number, { resolve: (r: unknown) => void; reject: (e: Error) => void }>();
  private buffer = '';
  private _ready = false;
  private _onReady = new Set<() => void>();

  constructor(private process: { stdin: Writable; stdout: NodeJS.ReadableStream }) {
    this.process.stdout.on('data', (chunk: Buffer) => this.onData(chunk));
  }

  get ready(): boolean {
    return this._ready;
  }

  onReady(cb: () => void): void {
    if (this._ready) {
      cb();
    } else {
      this._onReady.add(cb);
    }
  }

  /** Send a raw JSON-RPC request and wait for the matching response. */
  async request<T = unknown>(method: string, params?: unknown): Promise<T> {
    const id = this.requestId++;
    const req: MCPRequest = { jsonrpc: '2.0', id, method, params };
    this.process.stdin.write(JSON.stringify(req) + '\n');

    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (r: unknown) => void, reject });
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`Request ${method} timed out (15s)`));
        }
      }, 15000);
    });
  }

  /** Initialize the MCP connection (handshake). */
  async initialize(): Promise<void> {
    try {
      const result = await this.request('initialize', {
        protocolVersion: '2025-11-25',
        capabilities: {},
        clientInfo: { name: 'correctover-vscode', version: '1.0.0' },
      });
      this._ready = true;
      this._onReady.forEach(cb => cb());
      this._onReady.clear();
    } catch (e) {
      throw new Error(`MCP initialize failed: ${(e as Error).message}`);
    }
  }

  /** List available tools. */
  async listTools(): Promise<Tool[]> {
    const result = (await this.request('tools/list')) as { tools: Tool[] };
    return result.tools || [];
  }

  /** Call a tool by name. */
  async callTool(name: string, args: Record<string, unknown>): Promise<{ content: { text: string }[] }> {
    const result = await this.request<{ content: { text: string }[] }>('tools/call', {
      name,
      arguments: args,
    });
    return result;
  }

  /** Check health of all providers. */
  async health(): Promise<string> {
    const result = await this.callTool('health', {});
    return result?.content?.[0]?.text || '(empty response)';
  }

  /** Get session statistics. */
  async stats(): Promise<string> {
    const result = await this.callTool('stats', {});
    return result?.content?.[0]?.text || '(empty response)';
  }

  /** Send a chat message with validation. */
  async chat(messages: Array<{ role: string; content: string }>, options?: {
    model?: string; provider?: string; temperature?: number; maxTokens?: number; systemPrompt?: string;
  }): Promise<string> {
    const args: Record<string, unknown> = { messages };
    if (options?.model) args.model = options.model;
    if (options?.provider) args.provider = options.provider;
    if (options?.temperature !== undefined) args.temperature = options.temperature;
    if (options?.maxTokens !== undefined) args.max_tokens = options.maxTokens;
    if (options?.systemPrompt) args.system_prompt = options.systemPrompt;
    const result = await this.callTool('chat', args);
    return result?.content?.[0]?.text || '(empty response)';
  }

  /** Parse a validation report from a chat response. */
  static parseValidationReport(text: string): { passed: boolean; score: number; details: Record<string, boolean>; provider?: string; latencyMs?: number } {
    const passed = text.includes('Passed:   true') || text.includes('✓ All dimensions passed');
    const scoreMatch = text.match(/Score:\s+(\d+)\/6/);
    const score = scoreMatch ? parseInt(scoreMatch[1], 10) : (passed ? 6 : 0);
    const providerMatch = text.match(/Provider:\s+(\S+)/);
    const latencyMatch = text.match(/Latency:\s+(\d+)ms/);

    const details: Record<string, boolean> = {};
    for (const dim of ['structure', 'schema', 'latency', 'cost', 'identity', 'integrity']) {
      const re = new RegExp(`(✅|❌|✓|✗)\\s*${dim}\\s+(PASS|FAIL|pass|fail)`);
      const m = text.match(re);
      details[dim] = m ? (m[2].toUpperCase() === 'PASS') : passed;
    }

    return {
      passed,
      score,
      details,
      provider: providerMatch?.[1],
      latencyMs: latencyMatch ? parseInt(latencyMatch[1], 10) : undefined,
    };
  }

  private onData(chunk: Buffer): void {
    this.buffer += chunk.toString('utf-8');
    const lines = this.buffer.split('\n');
    this.buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const msg = JSON.parse(line) as MCPResponse;
        const pending = this.pending.get(msg.id);
        if (pending) {
          this.pending.delete(msg.id);
          if (msg.error) {
            pending.reject(new Error(`MCP error ${msg.error.code}: ${msg.error.message}`));
          } else {
            pending.resolve(msg.result);
          }
        }
      } catch {
        // Non-JSON line (e.g. log output from stderr redirected to stdout) — ignore
        console.warn('[correctover] Non-JSON output:', line);
      }
    }
  }

  dispose(): void {
    this.pending.forEach((p) => p.reject(new Error('Client disposed')));
    this.pending.clear();
    this._ready = false;
  }
}
