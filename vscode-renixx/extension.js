const { LanguageClient, TransportKind } = require('vscode-languageclient/node');
const vscode = require('vscode');
const cp = require('child_process');

let client;

function pythonAvailable(pythonPath) {
    try {
        const r = cp.spawnSync(pythonPath, ['--version'], { encoding: 'utf8', timeout: 5000 });
        return r.status === 0;
    } catch (e) {
        return false;
    }
}

function renixxAvailable(pythonPath) {
    try {
        const r = cp.spawnSync(pythonPath, ['-c', 'import renixx; print("ok")'], { encoding: 'utf8', timeout: 10000 });
        return r.status === 0 && (r.stdout || '').includes('ok');
    } catch (e) {
        return false;
    }
}

function activate(context) {
    const output = vscode.window.createOutputChannel('Renixx');
    context.subscriptions.push(output);

    const pythonPath = vscode.workspace.getConfiguration('renixx').get('pythonPath') || 'python';

    if (!pythonAvailable(pythonPath)) {
        vscode.window.showErrorMessage(
            'Renixx: Python not found at "' + pythonPath + '". ' +
            'Install Python 3.9+ or set renixx.pythonPath in settings.'
        );
        return;
    }
    if (!renixxAvailable(pythonPath)) {
        vscode.window.showErrorMessage(
            'Renixx: the renixx package is not importable by "' + pythonPath + '". ' +
            'Install it with: pip install -e . (or pip install renixx).'
        );
        return;
    }

    const serverOptions = {
        run: { command: pythonPath, args: ['-m', 'renixx', 'lsp'], transport: TransportKind.stdio },
        debug: { command: pythonPath, args: ['-m', 'renixx', 'lsp'], transport: TransportKind.stdio }
    };
    const clientOptions = {
        documentSelector: [{ scheme: 'file', language: 'renixx' }],
        synchronize: {
            fileEvents: vscode.workspace.createFileSystemWatcher('**/*.rn')
        },
        outputChannel: output,
        errorHandler: {
            error: () => ({ action: 1 }), // Continue
            closed: () => ({ action: 2, handled: true }) // Restart
        }
    };

    client = new LanguageClient('renixx', 'Renixx Language Server', serverOptions, clientOptions);

    client.onDidChangeState((e) => {
        output.appendLine('LSP state changed: ' + e.newState);
    });

    client.start().then(() => {
        output.appendLine('Renixx language server started.');
    }).catch((err) => {
        vscode.window.showErrorMessage('Renixx: failed to start language server: ' + (err && err.message ? err.message : err));
        output.appendLine('Start error: ' + (err && err.stack ? err.stack : String(err)));
    });

    context.subscriptions.push(client);
}

function deactivate() {
    if (!client) return undefined;
    return client.stop();
}

module.exports = { activate, deactivate };