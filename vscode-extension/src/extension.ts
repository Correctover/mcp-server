import * as vscode from 'vscode';
import { ServerManager } from './serverManager';
import { StatusBarManager } from './statusBar';
import { DashboardProvider } from './dashboardProvider';

let serverManager: ServerManager | undefined;
let statusBar: StatusBarManager | undefined;
let dashboardProvider: DashboardProvider | undefined;
let outputChannel: vscode.OutputChannel | undefined;

export function activate(context: vscode.ExtensionContext) {
  outputChannel = vscode.window.createOutputChannel('Correctover');
  outputChannel.appendLine('[correctover] Activating extension...');

  // Initialize managers
  serverManager = new ServerManager(outputChannel);
  statusBar = new StatusBarManager();

  // Register dashboard WebView provider
  dashboardProvider = new DashboardProvider(context.extensionUri, serverManager);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('correctover.dashboard', dashboardProvider, {
      webviewOptions: { retainContextWhenHidden: true },
    })
  );

  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand('correctover.start', async () => {
      try {
        await serverManager!.start();
        vscode.window.showInformationMessage('Correctover MCP Server started');
      } catch (err) {
        const msg = (err as Error).message;
        vscode.window.showErrorMessage(`Failed to start Correctover: ${msg}`);
        outputChannel!.appendLine(`[correctover] start error: ${msg}`);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('correctover.stop', async () => {
      await serverManager!.stop();
      vscode.window.showInformationMessage('Correctover MCP Server stopped');
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('correctover.restart', async () => {
      try {
        vscode.window.showInformationMessage('Restarting Correctover MCP Server...');
        await serverManager!.restart();
        vscode.window.showInformationMessage('Correctover MCP Server restarted');
      } catch (err) {
        const msg = (err as Error).message;
        vscode.window.showErrorMessage(`Failed to restart Correctover: ${msg}`);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('correctover.dashboard', () => {
      vscode.commands.executeCommand('workbench.view.extension.correctover-sidebar');
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('correctover.health', async () => {
      if (!serverManager!.mcpClient) {
        vscode.window.showWarningMessage('Correctover server is not running. Use "Correctover: Start" first.');
        return;
      }
      try {
        const result = await serverManager!.mcpClient.health();
        const doc = await vscode.workspace.openTextDocument({
          content: result,
          language: 'plaintext',
        });
        vscode.window.showTextDocument(doc, { preview: true });
      } catch (err) {
        vscode.window.showErrorMessage(`Health check failed: ${(err as Error).message}`);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('correctover.stats', async () => {
      if (!serverManager!.mcpClient) {
        return;
      }
      try {
        const result = await serverManager!.mcpClient.stats();
        statusBar!.updateStats(result);
        return result;
      } catch {
        // Silently fail for polling
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('correctover.configureProviders', () => {
      vscode.commands.executeCommand('workbench.action.openSettings', '@ext:correctover-vscode');
    })
  );

  // Listen to server status changes for status bar updates
  context.subscriptions.push(
    serverManager.onStatusChange((status) => {
      statusBar!.update(status);
      dashboardProvider?.refresh();
    })
  );

  // Register MCP integration with VS Code's built-in MCP system
  const enableMcp = vscode.workspace.getConfiguration('correctover').get<boolean>('enableMcpIntegration');
  if (enableMcp) {
    registerBuiltInMcp(context);
  }

  // Auto-start if configured
  const autoStart = vscode.workspace.getConfiguration('correctover').get<boolean>('autoStart');
  if (autoStart) {
    setTimeout(() => {
      vscode.commands.executeCommand('correctover.start');
    }, 1000);
  }

  outputChannel.appendLine('[correctover] Extension activated');
}

export function deactivate() {
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
function registerBuiltInMcp(context: vscode.ExtensionContext): void {
  try {
    const vscodeAny = vscode as any;
    if (!vscodeAny.mcp?.createMcpServer) {
      outputChannel?.appendLine('[correctover] Built-in MCP API not available (VS Code <1.95?)');
      return;
    }
    const disposable = vscodeAny.mcp.createMcpServer(
      'correctover',
      {
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
          } catch {
            return [];
          }
        },
        executeTool: async (toolName: string, args: unknown) => {
          if (!serverManager?.mcpClient?.ready) {
            return { content: [{ type: 'text' as const, text: 'Correctover server not running' }], isError: true };
          }
          const result = await serverManager.mcpClient.callTool(toolName, args as Record<string, unknown>);
          return {
            content: (result.content || []).map((c) => ({ type: 'text' as const, text: c.text })),
          };
        },
      }
    );

    if (disposable) {
      context.subscriptions.push(disposable);
      outputChannel?.appendLine('[correctover] Registered with VS Code built-in MCP system');
    }
  } catch (e) {
    outputChannel?.appendLine(`[correctover] Built-in MCP registration failed: ${e}`);
  }
}
