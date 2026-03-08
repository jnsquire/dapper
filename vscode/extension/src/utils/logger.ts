import * as vscode from 'vscode';

const LEVELS = ['debug','info','warn','error'] as const;
type LogLevel = typeof LEVELS[number];

export class Logger {
    private outputChannel: vscode.LogOutputChannel;
    private logLevel: LogLevel = 'info';
    private logToConsole = false;

    // keep reference to configuration-change listener so it can be
    // disposed when the logger itself is disposed
    private configListener: vscode.Disposable;

    constructor() {
        // create output channel once
        this.outputChannel = vscode.window.createOutputChannel('Dapper Debugger', { log: true }) as vscode.LogOutputChannel;
        this.reloadConfig();

        this.configListener = vscode.workspace.onDidChangeConfiguration(e => {
            if (e.affectsConfiguration('dapper.logLevel') || e.affectsConfiguration('dapper.logToConsole')) {
                this.reloadConfig();
            }
        });
    }

    private reloadConfig() {
        const cfg = vscode.workspace.getConfiguration('dapper');
        this.setLogLevel(cfg.get<string>('logLevel', 'info'));
        this.logToConsole = cfg.get<boolean>('logToConsole', false);
    }

    private setLogLevel(level: string): void {
        if (LEVELS.includes(level as LogLevel)) {
            this.logLevel = level as LogLevel;
            this.outputChannel.info(`Log level set to: ${level}`);
        }
    }

    private shouldLog(level: LogLevel): boolean {
        return LEVELS.indexOf(level) >= LEVELS.indexOf(this.logLevel);
    }

    private logMessage(level: LogLevel, message: string, data?: any): void {
        const timestamp = new Date().toISOString();
        const line = `[${timestamp}] ${level.toUpperCase()}: ${message}`;
        (this.outputChannel as any)[level](line);

        if (data !== undefined) {
            const writer: (msg: string) => void = (this.outputChannel as any)[level];
            if (data instanceof Error) {
                writer(data.toString());
                if (data.stack) writer(data.stack);
            } else if (typeof data === 'object') {
                try { writer(JSON.stringify(data, null, 2)); }
                catch { writer(String(data)); }
            } else {
                writer(String(data));
            }
        }

        if (this.logToConsole) {
            const map: Record<LogLevel,string> = { debug:'debug', info:'log', warn:'warn', error:'error' };
            (console as any)[map[level]](`[Dapper] ${line}`, data || '');
        }
    }

    public debug(msg: string, data?: any) { if (this.shouldLog('debug')) this.logMessage('debug', msg, data); }
    public log(msg: string, data?: any) { if (this.shouldLog('info')) this.logMessage('info', msg, data); }
    public warn(msg: string, data?: any) { if (this.shouldLog('warn')) this.logMessage('warn', msg, data); }
    public error(msg: string, data?: any) { if (this.shouldLog('error')) this.logMessage('error', msg, data); }

    public show() { this.outputChannel.show(); }
    public getChannel() { return this.outputChannel; }
    public dispose() {
        // clean up the output channel and config listener
        this.outputChannel.dispose();
        this.configListener.dispose();
    }
}

export const logger = new Logger();

// Register command to show logs
export function registerLoggerCommands(context: vscode.ExtensionContext): vscode.Disposable {
    const showLogsCommand = vscode.commands.registerCommand('dapper.showLogs', () => {
        logger.show();
    });
    // Return the disposable so callers can manage subscription lifecycle
    return showLogsCommand;
}
