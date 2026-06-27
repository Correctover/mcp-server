import { Writable } from 'stream';
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
    error?: {
        code: number;
        message: string;
    };
}
export interface Tool {
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: Record<string, unknown>;
        required?: string[];
    };
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
export declare class MCPClient {
    private process;
    private requestId;
    private pending;
    private buffer;
    private _ready;
    private _onReady;
    constructor(process: {
        stdin: Writable;
        stdout: NodeJS.ReadableStream;
    });
    get ready(): boolean;
    onReady(cb: () => void): void;
    /** Send a raw JSON-RPC request and wait for the matching response. */
    request<T = unknown>(method: string, params?: unknown): Promise<T>;
    /** Initialize the MCP connection (handshake). */
    initialize(): Promise<void>;
    /** List available tools. */
    listTools(): Promise<Tool[]>;
    /** Call a tool by name. */
    callTool(name: string, args: Record<string, unknown>): Promise<{
        content: {
            text: string;
        }[];
    }>;
    /** Check health of all providers. */
    health(): Promise<string>;
    /** Get session statistics. */
    stats(): Promise<string>;
    /** Send a chat message with validation. */
    chat(messages: Array<{
        role: string;
        content: string;
    }>, options?: {
        model?: string;
        provider?: string;
        temperature?: number;
        maxTokens?: number;
        systemPrompt?: string;
    }): Promise<string>;
    /** Parse a validation report from a chat response. */
    static parseValidationReport(text: string): {
        passed: boolean;
        score: number;
        details: Record<string, boolean>;
        provider?: string;
        latencyMs?: number;
    };
    private onData;
    dispose(): void;
}
