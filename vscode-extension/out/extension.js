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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const serverManager_1 = require("./serverManager");
const statusBar_1 = require("./statusBar");
const dashboardProvider_1 = require("./dashboardProvider");
let serverManager;
let statusBar;
let dashboardProvider;
let outputChannel;
function activate(context) {
    outputChannel = vscode.window.createOutputChannel('Correctover');
    outputChannel.appendLine('[correctover] Activating extension...');
    // Initialize managers
    serverManager = new serverManager_1.ServerManager(outputChannel);
    statusBar = new statusBar_1.StatusBarManager();
    // Register dashboard WebView provider
    dashboardProvider = new dashboardProvider_1.DashboardProvider(context.extensionUri, serverManager);
    context.subscriptions.push(vscode.window.registerWebviewViewProvider('correctover.dashboard', dashboardProvider, {
        webviewOptions: { retainContextWhenHidden: true },
    }));
    // Register commands
    context.subscriptions.push(vscode.commands.registerCommand('correctover.start', async () => {
        try {
            await serverManager.start();
            vscode.window.showInformationMessage('Correctover MCP Server started');
        }
        catch (err) {
            const msg = err.message;
            vscode.window.showErrorMessage(`Failed to start Correctover: ${msg}`);
            outputChannel.appendLine(`[correctover] start error: ${msg}`);
        }
    }));
    context.subscriptions.push(vscode.commands.registerCommand('correctover.stop', async () => {
        await serverManager.stop();
        vscode.window.showInformationMessage('Correctover MCP Server stopped');
    }));
    context.subscriptions.push(vscode.commands.registerCommand('correctover.restart', async () => {
        try {
            vscode.window.showInformationMessage('Restarting Correctover MCP Server...');
            await serverManager.restart();
            vscode.window.showInformationMessage('Correctover MCP Server restarted');
        }
        catch (err) {
            const msg = err.message;
            vscode.window.showErrorMessage(`Failed to restart Correctover: ${msg}`);
        }
    }));
    context.subscriptions.push(vscode.commands.registerCommand('correctover.dashboard', () => {
        vscode.commands.executeCommand('workbench.view.extension.correctover-sidebar');
    }));
    context.subscriptions.push(vscode.commands.registerCommand('correctover.health', async () => {
        if (!serverManager.mcpClient) {
            vscode.window.showWarningMessage('Correctover server is not running. Use "Correctover: Start" first.');
            return;
        }
        try {
            const result = await serverManager.mcpClient.health();
            const doc = await vscode.workspace.openTextDocument({
                content: result,
                language: 'plaintext',
            });
            vscode.window.showTextDocument(doc, { preview: true });
        }
        catch (err) {
            vscode.window.showErrorMessage(`Health check failed: ${err.message}`);
        }
    }));
    context.subscriptions.push(vscode.commands.registerCommand('correctover.stats', async () => {
        if (!serverManager.mcpClient) {
            return;
        }
        try {
            const result = await serverManager.mcpClient.stats();
            statusBar.updateStats(result);
            return result;
        }
        catch {
            // Silently fail for polling
        }
    }));
    context.subscriptions.push(vscode.commands.registerCommand('correctover.configureProviders', () => {
        vscode.commands.executeCommand('workbench.action.openSettings', '@ext:correctover-vscode');
    }));
    // Listen to server status changes for status bar updates
    context.subscriptions.push(serverManager.onStatusChange((status) => {
        statusBar.update(status);
        dashboardProvider?.refresh();
    }));
    // Register MCP integration with VS Code's built-in MCP system
    const enableMcp = vscode.workspace.getConfiguration('correctover').get('enableMcpIntegration');
    if (enableMcp) {
        registerBuiltInMcp(context);
    }
    // Auto-start if configured
    const autoStart = vscode.workspace.getConfiguration('correctover').get('autoStart');
    if (autoStart) {
        setTimeout(() => {
            vscode.commands.executeCommand('correctover.start');
        }, 1000);
    }
    outputChannel.appendLine('[correctover] Extension activated');
}
function deactivate() {
    outputChannel?.appendLine('[correctover] Deactivating extension...');
    if (serverManager) {
        serverManager.stop();
        serverManager.dispose();
    }
    if (statusBar) {
        statusBar.dispose();
    }
    outputChannel?.appendLine('[correctover] Extension deactivated');
}
/**
 * Register Correctover with VS Code's built-in MCP tool system (VS Code 1.95+).
 * The MCP API is not yet in the stable @types/vscode, so we access it dynamically.
 */
function registerBuiltInMcp(context) {
    try {
        const vscodeAny = vscode;
        if (!vscodeAny.mcp?.createMcpServer) {
            outputChannel?.appendLine('[correctover] Built-in MCP API not available (VS Code <1.95?)');
            return;
        }
        const disposable = vscodeAny.mcp.createMcpServer('correctover', {
            name: 'Correctover',
            version: '1.0.0',
            tools: async () => {
                if (!serverManager?.mcpClient?.ready) {
                    return [];
                }
                try {
                    const tools = await serverManager.mcpClient.listTools();
                    return tools.map((t) => ({
                        name: t.name,
                        description: t.description,
                        inputSchema: t.inputSchema,
                    }));
                }
                catch {
                    return [];
                }
            },
            executeTool: async (toolName, args) => {
                if (!serverManager?.mcpClient?.ready) {
                    return { content: [{ type: 'text', text: 'Correctover server not running' }], isError: true };
                }
                const result = await serverManager.mcpClient.callTool(toolName, args);
                return {
                    content: (result.content || []).map((c) => ({ type: 'text', text: c.text })),
                };
            },
        });
        if (disposable) {
            context.subscriptions.push(disposable);
            outputChannel?.appendLine('[correctover] Registered with VS Code built-in MCP system');
        }
    }
    catch (e) {
        outputChannel?.appendLine(`[correctover] Built-in MCP registration failed: ${e}`);
    }
}
//# sourceMappingURL=extension.js.map