import { ServerStatus } from './serverManager';
/**
 * Manages the Correctover status bar items.
 */
export declare class StatusBarManager {
    private serverItem;
    private statsItem;
    private refreshTimer;
    constructor();
    update(status: ServerStatus): void;
    updateStats(text: string): void;
    private startStatsPolling;
    private stopStatsPolling;
    dispose(): void;
}
