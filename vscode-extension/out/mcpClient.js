"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.MCPClient = void 0;
/**
 * MCP Client — communicates with the Correctover Go server via stdio JSON-RPC.
 */
class MCPClient {
    process;
    requestId = 1;
    pending = new Map();
    buffer = '';
    _ready = false;
    _onReady = new Set();
    constructor(process) {
        this.process = process;
        this.process.stdout.on('data', (chunk) => this.onData(chunk));
    }
    get ready() {
        return this._ready;
    }
    onReady(cb) {
        if (this._ready) {
            cb();
        }
        else {
            this._onReady.add(cb);
        }
    }
    /** Send a raw JSON-RPC request and wait for the matching response. */
    async request(method, params) {
        const id = this.requestId++;
        const req = { jsonrpc: '2.0', id, method, params };
        this.process.stdin.write(JSON.stringify(req) + '\n');
        return new Promise((resolve, reject) => {
            this.pending.set(id, { resolve: resolve, reject });
            setTimeout(() => {
                if (this.pending.has(id)) {
                    this.pending.delete(id);
                    reject(new Error(`Request ${method} timed out (15s)`));
                }
            }, 15000);
        });
    }
    /** Initialize the MCP connection (handshake). */
    async initialize() {
        try {
            const result = await this.request('initialize', {
                protocolVersion: '2025-11-25',
                capabilities: {},
                clientInfo: { name: 'correctover-vscode', version: '1.0.0' },
            });
            this._ready = true;
            this._onReady.forEach(cb => cb());
            this._onReady.clear();
        }
        catch (e) {
            throw new Error(`MCP initialize failed: ${e.message}`);
        }
    }
    /** List available tools. */
    async listTools() {
        const result = (await this.request('tools/list'));
        return result.tools || [];
    }
    /** Call a tool by name. */
    async callTool(name, args) {
        const result = await this.request('tools/call', {
            name,
            arguments: args,
        });
        return result;
    }
    /** Check health of all providers. */
    async health() {
        const result = await this.callTool('health', {});
        return result?.content?.[0]?.text || '(empty response)';
    }
    /** Get session statistics. */
    async stats() {
        const result = await this.callTool('stats', {});
        return result?.content?.[0]?.text || '(empty response)';
    }
    /** Send a chat message with validation. */
    async chat(messages, options) {
        const args = { messages };
        if (options?.model)
            args.model = options.model;
        if (options?.provider)
            args.provider = options.provider;
        if (options?.temperature !== undefined)
            args.temperature = options.temperature;
        if (options?.maxTokens !== undefined)
            args.max_tokens = options.maxTokens;
        if (options?.systemPrompt)
            args.system_prompt = options.systemPrompt;
        const result = await this.callTool('chat', args);
        return result?.content?.[0]?.text || '(empty response)';
    }
    /** Parse a validation report from a chat response. */
    static parseValidationReport(text) {
        const passed = text.includes('Passed:   true') || text.includes('✓ All dimensions passed');
        const scoreMatch = text.match(/Score:\s+(\d+)\/6/);
        const score = scoreMatch ? parseInt(scoreMatch[1], 10) : (passed ? 6 : 0);
        const providerMatch = text.match(/Provider:\s+(\S+)/);
        const latencyMatch = text.match(/Latency:\s+(\d+)ms/);
        const details = {};
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
    onData(chunk) {
        this.buffer += chunk.toString('utf-8');
        const lines = this.buffer.split('\n');
        this.buffer = lines.pop() || '';
        for (const line of lines) {
            if (!line.trim())
                continue;
            try {
                const msg = JSON.parse(line);
                const pending = this.pending.get(msg.id);
                if (pending) {
                    this.pending.delete(msg.id);
                    if (msg.error) {
                        pending.reject(new Error(`MCP error ${msg.error.code}: ${msg.error.message}`));
                    }
                    else {
                        pending.resolve(msg.result);
                    }
                }
            }
            catch {
                // Non-JSON line (e.g. log output from stderr redirected to stdout) — ignore
                console.warn('[correctover] Non-JSON output:', line);
            }
        }
    }
    dispose() {
        this.pending.forEach((p) => p.reject(new Error('Client disposed')));
        this.pending.clear();
        this._ready = false;
    }
}
exports.MCPClient = MCPClient;
//# sourceMappingURL=mcpClient.js.map