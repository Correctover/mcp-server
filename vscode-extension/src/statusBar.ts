import * as vscode from 'vscode';
import { ServerStatus } from './serverManager';

/**
 * Manages the Correctover status bar items.
 */
export class StatusBarManager {
  private serverItem: vscode.StatusBarItem;
  private statsItem: vscode.StatusBarItem;
  private refreshTimer: NodeJS.Timeout | null = null;

  constructor() {
    this.serverItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    this.serverItem.command = 'correctover.dashboard';
    this.serverItem.tooltip = 'Correctover MCP Server — Click to open dashboard';

    this.statsItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 99);
    this.statsItem.command = 'correctover.stats';
    this.statsItem.tooltip = 'Correctover Session Stats — Click to view';
    this.statsItem.hide();
  }

  update(status: ServerStatus): void {
    switch (status.state) {
      case 'running':
        this.serverItem.text = '$(check) Correctover: Running';
        this.serverItem.backgroundColor = undefined;
        this.statsItem.show();
        this.startStatsPolling();
        break;
      case 'starting':
        this.serverItem.text = '$(sync~spin) Correctover: Starting...';
        this.serverItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
        this.statsItem.hide();
        break;
      case 'error':
        this.serverItem.text = '$(error) Correctover: Error';
        this.serverItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
        this.serverItem.tooltip = `Correctover MCP Server Error: ${status.error || 'Unknown error'}`;
        this.statsItem.hide();
        break;
      case 'stopped':
      default:
        this.serverItem.text = '$(circle-slash) Correctover: Stopped';
        this.serverItem.backgroundColor = undefined;
        this.statsItem.hide();
        break;
    }
    this.serverItem.show();
  }

  updateStats(text: string): void {
    // Parse stats and show concise summary
    const callsMatch = text.match(/Total Calls:\s+(\d+)/);
    const passMatch = text.match(/Validation Passed:\s+(\d+)/);
    const failoverMatch = text.match(/Failovers:\s+(\d+)/);

    if (callsMatch) {
      const parts: string[] = [`$(graph) ${callsMatch[1]} calls`];
      if (passMatch) parts.push(`$(pass) ${passMatch[1]} passed`);
      if (failoverMatch && parseInt(failoverMatch[1]) > 0) {
        parts.push(`$(warning) ${failoverMatch[1]} failovers`);
      }
      this.statsItem.text = parts.join(' | ');
      this.statsItem.show();
    }
  }

  private startStatsPolling(): void {
    this.stopStatsPolling();
    this.refreshTimer = setInterval(() => {
      vscode.commands.executeCommand('correctover.stats');
    }, 30000); // Poll every 30s
  }

  private stopStatsPolling(): void {
    if (this.refreshTimer) {
      clearInterval(this.refreshTimer);
      this.refreshTimer = null;
    }
  }

  dispose(): void {
    this.stopStatsPolling();
    this.serverItem.dispose();
    this.statsItem.dispose();
  }
}
