const fs = require('fs');
const path = require('path');
const cp = require('child_process');

let vscode;
try {
    vscode = require('vscode');
} catch (err) {
    vscode = null;
}

let LanguageClient;
let TransportKind;
try {
    const lc = require('vscode-languageclient/node');
    LanguageClient = lc.LanguageClient;
    TransportKind = lc.TransportKind;
} catch (err) {
    LanguageClient = null;
    TransportKind = null;
}

let client;

function resolveRepoSourceDir(workspaceFolder) {
    if (!workspaceFolder || !workspaceFolder.fsPath) {
        return undefined;
    }
    const srcDir = path.join(workspaceFolder.fsPath, 'src');
    const candidate = path.join(srcDir, 'renixx', '__init__.py');
    if (fs.existsSync(candidate)) {
        return srcDir;
    }
    return undefined;
}

function buildPythonEnv(pythonPath, workspaceFolder) {
    const env = Object.assign({}, process.env);
    const repoSourceDir = resolveRepoSourceDir(workspaceFolder);
    if (!repoSourceDir) {
        return env;
    }
    const existing = (env.PYTHONPATH || '').split(path.delimiter).filter(Boolean);
    const next = [repoSourceDir].concat(existing.filter((entry) => entry !== repoSourceDir));
    env.PYTHONPATH = Array.from(new Set(next)).join(path.delimiter);
    return env;
}

function pythonAvailable(pythonPath, env) {
    try {
        const r = cp.spawnSync(pythonPath, ['--version'], { encoding: 'utf8', timeout: 5000, env });
        return r.status === 0;
    } catch (e) {
        return false;
    }
}

function renixxAvailable(pythonPath, env) {
    try {
        const r = cp.spawnSync(pythonPath, ['-c', 'import renixx; print("ok")'], { encoding: 'utf8', timeout: 10000, env });
        return r.status === 0 && (r.stdout || '').includes('ok');
    } catch (e) {
        return false;
    }
}

function activate(context) {
    if (!vscode) {
        return;
    }

    const output = vscode.window.createOutputChannel('Renixx');
    context.subscriptions.push(output);

    const workspaceFolder = (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0]) || null;
    const pythonPath = vscode.workspace.getConfiguration('renixx').get('pythonPath') || 'python';
    const env = buildPythonEnv(pythonPath, workspaceFolder);

    if (!pythonAvailable(pythonPath, env)) {
        vscode.window.showErrorMessage(
            'Renixx: Python not found at "' + pythonPath + '". ' +
            'Install Python 3.9+ or set renixx.pythonPath in settings.'
        );
        return;
    }
    if (!renixxAvailable(pythonPath, env)) {
        const repoSourceDir = resolveRepoSourceDir(workspaceFolder);
        const installHint = repoSourceDir ? 'Open a VS Code workspace rooted at the repo or run: PYTHONPATH=' + repoSourceDir + ' python -m renixx lsp' : 'Install it with: pip install -e . (or pip install renixx).';
        vscode.window.showErrorMessage(
            'Renixx: the renixx package is not importable by "' + pythonPath + '". ' +
            installHint
        );
        return;
    }

    const serverOptions = {
        run: { command: pythonPath, args: ['-m', 'renixx', 'lsp'], env, transport: TransportKind.stdio },
        debug: { command: pythonPath, args: ['-m', 'renixx', 'lsp'], env, transport: TransportKind.stdio }
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

module.exports = { activate, deactivate, resolveRepoSourceDir, buildPythonEnv, pythonAvailable, renixxAvailable };