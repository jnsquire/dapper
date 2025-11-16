import * as vscode from 'vscode';

export class Logger {
    private static outputChannel: vscode.LogOutputChannel;
    private static instance: Logger;
    private static logLevel: 'debug' | 'info' | 'warn' | 'error' = 'info';

    private constructor() {
        // Private constructor to prevent direct construction calls
    }

    public static getInstance(): Logger {
        if (!Logger.instance) {
            Logger.instance = new Logger();
            Logger.outputChannel = vscode.window.createOutputChannel('Dapper Debugger', { log: true });
            // Load log level from configuration
            const config = vscode.workspace.getConfiguration('dapper');
            Logger.setLogLevel(config.get<string>('logLevel', 'info'));
        }
        return Logger.instance;
    }

    private static setLogLevel(level: string): void {
        const validLevels = ['debug', 'info', 'warn', 'error'];
        if (validLevels.includes(level)) {
            Logger.logLevel = level as 'debug' | 'info' | 'warn' | 'error';
        }
    }

    private shouldLog(level: 'debug' | 'info' | 'warn' | 'error'): boolean {
        const levels = ['debug', 'info', 'warn', 'error'];
        return levels.indexOf(level) >= levels.indexOf(Logger.logLevel);
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
        
        Logger.outputChannel.error(errorMessage);
        
        if (error instanceof Error) {
            Logger.outputChannel.error(error.toString());
            if (error.stack) {
                Logger.outputChannel.error(error.stack);
            }
        } else if (error) {
            Logger.outputChannel.error(JSON.stringify(error, null, 2));
        }
    }

    private logMessage(level: string, message: string, data?: any): void {
        const timestamp = new Date().toISOString();
        const logMessage = `[${timestamp}] ${level}: ${message}`;
        
        switch (level.toLowerCase()) {
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
    }

    public show(): void {
        Logger.outputChannel.show();
    }

    public dispose(): void {
        Logger.outputChannel.dispose();
    }
}

export const logger = Logger.getInstance();
