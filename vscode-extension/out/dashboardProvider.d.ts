import * as vscode from 'vscode';
import { ServerManager } from './serverManager';
/**
 * WebView provider for the Correctover dashboard sidebar panel.
 */
export declare class DashboardProvider implements vscode.WebviewViewProvider {
    private readonly _extensionUri;
    private readonly _serverManager;
    private _view?;
    private _refreshTimer;
    constructor(_extensionUri: vscode.Uri, _serverManager: ServerManager);
    resolveWebviewView(webviewView: vscode.WebviewView, _context: vscode.WebviewViewResolveContext, _token: vscode.CancellationToken): void;
    refresh(): void;
    private _refreshData;
    private _startAutoRefresh;
    private _stopAutoRefresh;
    private _getHtml;
}
