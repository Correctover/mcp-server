import * as vscode from 'vscode';
import { MCPClient } from './mcpClient';
export type ServerState = 'stopped' | 'starting' | 'running' | 'error';
export interface ServerStatus {
    state: ServerState;
    pid?: number;
    error?: string;
}
export declare class ServerManager {
    private process;
    private client;
    private _state;
    private _error;
    private outputChannel;
    private _onStatusChange;
    constructor(outputChannel: vscode.OutputChannel);
    get state(): ServerState;
    get mcpClient(): MCPClient | null;
    onStatusChange(cb: (status: ServerStatus) => void): vscode.Disposable;
    private notifyState;
    /** Find the Correctover binary. */
    private findBinary;
    /** Build the environment variables for the child process from VS Code settings. */
    private buildEnv;
    /** Start the Correctover MCP server. */
    start(): Promise<void>;
    /** Stop the Correctover MCP server. */
    stop(): Promise<void>;
    /** Restart the server. */
    restart(): Promise<void>;
    private cleanup;
    dispose(): void;
}
