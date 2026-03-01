import * as vscode from 'vscode';

export class Logger {
    // use the newer LogOutputChannel so we get convenience methods
    private static outputChannel: vscode.LogOutputChannel;
    private static instance: Logger;
    private static logLevel: 'debug' | 'info' | 'warn' | 'error' = 'info';
    private static logToConsole: boolean = false;

    private constructor() {
        // Private constructor to prevent direct construction calls
    }

    public static getInstance(): Logger {
        if (!Logger.instance) {
            Logger.instance = new Logger();
            // with our minimum VS Code target the `{ log: true }` option returns a
            // LogOutputChannel; tests also provide a fake channel with the same
            // methods.  we no longer need to massage the object.
            Logger.outputChannel = vscode.window.createOutputChannel('Dapper Debugger', { log: true }) as vscode.LogOutputChannel;
            
            // Load configuration
            const config = vscode.workspace.getConfiguration('dapper');
            Logger.setLogLevel(config.get<string>('logLevel', 'info'));
            Logger.logToConsole = config.get<boolean>('logToConsole', false);
            
            // Listen for configuration changes
            vscode.workspace.onDidChangeConfiguration((e: vscode.ConfigurationChangeEvent) => {
                if (e.affectsConfiguration('dapper.logLevel')) {
                    const newLevel = vscode.workspace.getConfiguration('dapper').get<string>('logLevel', 'info');
                    Logger.setLogLevel(newLevel);
                }
                if (e.affectsConfiguration('dapper.logToConsole')) {
                    Logger.logToConsole = vscode.workspace.getConfiguration('dapper').get<boolean>('logToConsole', false);
                }
            });
        }
        return Logger.instance;
    }

    private static setLogLevel(level: string): void {
        const validLevels = ['debug', 'info', 'warn', 'error'];
        if (validLevels.includes(level)) {
            Logger.logLevel = level as 'debug' | 'info' | 'warn' | 'error';
            // log the change via the log output channel
            Logger.outputChannel.info(`Log level set to: ${level}`);
        }
    }

    private shouldLog(level: 'debug' | 'info' | 'warn' | 'error'): boolean {
        const levels = ['debug', 'info', 'warn', 'error'];
        return levels.indexOf(level) >= levels.indexOf(Logger.logLevel);
    }

    /**
     * Core helper that writes a message (and optional data) at a given level.
     * Uses the dedicated LogOutputChannel methods rather than appendLine.
     */
    private logMessage(level: 'debug' | 'info' | 'warn' | 'error', message: string, data?: any): void {
        const timestamp = new Date().toISOString();
        const logMessage = `[${timestamp}] ${level.toUpperCase()}: ${message}`;

        // send the main line using the appropriate method
        switch (level) {
            case 'debug':
                Logger.outputChannel.debug(logMessage);
                break;
            case 'info':
                Logger.outputChannel.info(logMessage);
                break;
            case 'warn':
                Logger.outputChannel.warn(logMessage);
                break;
            case 'error':
                Logger.outputChannel.error(logMessage);
                break;
        }

        // log any attached data using the same level method
        if (data !== undefined) {
            const writer = Logger.outputChannel[level];
            if (data instanceof Error) {
                writer.call(Logger.outputChannel, data.toString());
                if (data.stack) {
                    writer.call(Logger.outputChannel, data.stack);
                }
            } else if (typeof data === 'object') {
                try {
                    writer.call(Logger.outputChannel, JSON.stringify(data, null, 2));
                } catch {
                    writer.call(Logger.outputChannel, String(data));
                }
            } else {
                writer.call(Logger.outputChannel, String(data));
            }
        }

        if (Logger.logToConsole) {
            const consoleMap: Record<string, string> = {
                debug: 'debug',
                info: 'log',
                warn: 'warn',
                error: 'error',
            };
            (console as any)[consoleMap[level]](`[Dapper] ${logMessage}`, data || '');
        }
    }

    public debug(message: string, data?: any): void {
        if (!this.shouldLog('debug')) return;
        this.logMessage('debug', message, data);
    }

    public log(message: string, data?: any): void {
        if (!this.shouldLog('info')) return;
        this.logMessage('info', message, data);
    }

    public warn(message: string, data?: any): void {
        if (!this.shouldLog('warn')) return;
        this.logMessage('warn', message, data);
    }

    public error(message: string, error?: Error | unknown): void {
        if (!this.shouldLog('error')) return;
        this.logMessage('error', message, error);
    }

    public show(): void {
        Logger.outputChannel.show();
    }

    public dispose(): void {
        Logger.outputChannel.dispose();
    }
}

export const logger = Logger.getInstance();

// Register command to show logs
export function registerLoggerCommands(context: vscode.ExtensionContext): vscode.Disposable {
    const showLogsCommand = vscode.commands.registerCommand('dapper.showLogs', () => {
        logger.show();
    });
    // Return the disposable so callers can manage subscription lifecycle
    return showLogsCommand;
}
