import * as vscode from 'vscode';

export class Logger {
    private static outputChannel: vscode.OutputChannel;
    private static instance: Logger;
    private static logLevel: 'debug' | 'info' | 'warn' | 'error' = 'info';
    private static logToConsole: boolean = false;

    private constructor() {
        // Private constructor to prevent direct construction calls
    }

    public static getInstance(): Logger {
        if (!Logger.instance) {
            Logger.instance = new Logger();
            Logger.outputChannel = vscode.window.createOutputChannel('Dapper Debugger');
            
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
            Logger.outputChannel.appendLine(`[${new Date().toISOString()}] Log level set to: ${level}`);
        }
    }

    private shouldLog(level: 'debug' | 'info' | 'warn' | 'error'): boolean {
        const levels = ['debug', 'info', 'warn', 'error'];
        return levels.indexOf(level) >= levels.indexOf(Logger.logLevel);
    }

    private logMessage(level: string, message: string, data?: any): void {
        const timestamp = new Date().toISOString();
        const logMessage = `[${timestamp}] ${level}: ${message}`;
        
        // Log to output channel
        Logger.outputChannel.appendLine(logMessage);
        
        // Log additional data if provided
        if (data !== undefined) {
            if (data instanceof Error) {
                Logger.outputChannel.appendLine(data.toString());
                if (data.stack) {
                    Logger.outputChannel.appendLine(data.stack);
                }
            } else if (typeof data === 'object') {
                try {
                    Logger.outputChannel.appendLine(JSON.stringify(data, null, 2));
                } catch (e) {
                    Logger.outputChannel.appendLine(String(data));
                }
            } else {
                Logger.outputChannel.appendLine(String(data));
            }
        }
        
        // Log to console if enabled
        if (Logger.logToConsole) {
            const consoleMethod = level === 'DEBUG' ? 'debug' : 
                               level === 'INFO' ? 'log' : 
                               level === 'WARN' ? 'warn' : 'error';
            (console as any)[consoleMethod](`[Dapper] ${logMessage}`, data || '');
        }
    }

    public debug(message: string, data?: any): void {
        if (!this.shouldLog('debug')) return;
        this.logMessage('DEBUG', message, data);
    }

    public log(message: string, data?: any): void {
        if (!this.shouldLog('info')) return;
        this.logMessage('INFO', message, data);
    }

    public warn(message: string, data?: any): void {
        if (!this.shouldLog('warn')) return;
        this.logMessage('WARN', message, data);
    }

    public error(message: string, error?: Error | unknown): void {
        if (!this.shouldLog('error')) return;
        
        const timestamp = new Date().toISOString();
        const errorMessage = `[${timestamp}] ERROR: ${message}`;
        
        // Log to output channel
        Logger.outputChannel.appendLine(errorMessage);
        
        // Log error details if provided
        if (error instanceof Error) {
            Logger.outputChannel.appendLine(error.toString());
            if (error.stack) {
                Logger.outputChannel.appendLine(error.stack);
            }
        } else if (error) {
            Logger.outputChannel.appendLine(JSON.stringify(error, null, 2));
        }
        
        // Log to console if enabled
        if (Logger.logToConsole) {
            console.error(`[Dapper] ${errorMessage}`, error || '');
        }
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
