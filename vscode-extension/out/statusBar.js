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
exports.StatusBarManager = void 0;
const vscode = __importStar(require("vscode"));
/**
 * Manages the Correctover status bar items.
 */
class StatusBarManager {
    serverItem;
    statsItem;
    refreshTimer = null;
    constructor() {
        this.serverItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
        this.serverItem.command = 'correctover.dashboard';
        this.serverItem.tooltip = 'Correctover MCP Server — Click to open dashboard';
        this.statsItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 99);
        this.statsItem.command = 'correctover.stats';
        this.statsItem.tooltip = 'Correctover Session Stats — Click to view';
        this.statsItem.hide();
    }
    update(status) {
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
    updateStats(text) {
        // Parse stats and show concise summary
        const callsMatch = text.match(/Total Calls:\s+(\d+)/);
        const passMatch = text.match(/Validation Passed:\s+(\d+)/);
        const failoverMatch = text.match(/Failovers:\s+(\d+)/);
        if (callsMatch) {
            const parts = [`$(graph) ${callsMatch[1]} calls`];
            if (passMatch)
                parts.push(`$(pass) ${passMatch[1]} passed`);
            if (failoverMatch && parseInt(failoverMatch[1]) > 0) {
                parts.push(`$(warning) ${failoverMatch[1]} failovers`);
            }
            this.statsItem.text = parts.join(' | ');
            this.statsItem.show();
        }
    }
    startStatsPolling() {
        this.stopStatsPolling();
        this.refreshTimer = setInterval(() => {
            vscode.commands.executeCommand('correctover.stats');
        }, 30000); // Poll every 30s
    }
    stopStatsPolling() {
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = null;
        }
    }
    dispose() {
        this.stopStatsPolling();
        this.serverItem.dispose();
        this.statsItem.dispose();
    }
}
exports.StatusBarManager = StatusBarManager;
//# sourceMappingURL=statusBar.js.map