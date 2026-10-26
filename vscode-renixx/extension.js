const { LanguageClient, TransportKind } = require('vscode-languageclient/node');
const vscode = require('vscode');
const path = require('path');

let client;

function activate(context) {
    const pythonPath = vscode.workspace.getConfiguration('renixx').get('pythonPath') || 'python';
    const serverOptions = {
        run: { command: pythonPath, args: ['-m', 'renixx', 'lsp'], transport: TransportKind.stdio,
               options: { env: { ...process.env, PYTHONPATH: '' } } },
        debug: { command: pythonPath, args: ['-m', 'renixx', 'lsp'], transport: TransportKind.stdio }
    };
    // try to set PYTHONPATH to src if running from repo; otherwise rely on installed package
    const clientOptions = {
        documentSelector: [{ scheme: 'file', language: 'renixx' }],
        synchronize: {
            fileEvents: vscode.workspace.createFileSystemWatcher('**/*.rn')
        }
    };
    client = new LanguageClient('renixx', 'Renixx Language Server', serverOptions, clientOptions);
    client.start();
    context.subscriptions.push(client);
}

function deactivate() {
    if (!client) return undefined;
    return client.stop();
}

module.exports = { activate, deactivate };