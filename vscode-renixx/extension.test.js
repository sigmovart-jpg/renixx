const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { resolveRepoSourceDir, buildPythonEnv } = require('./extension.js');

test('finds local src directory in a repo checkout', () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'renixx-workspace-'));
  const srcDir = path.join(workspace, 'src', 'renixx');
  fs.mkdirSync(srcDir, { recursive: true });
  fs.writeFileSync(path.join(srcDir, '__init__.py'), '');

  assert.equal(resolveRepoSourceDir({ fsPath: workspace }), path.join(workspace, 'src'));
});

test('buildPythonEnv prepends repo src without duplicating PYTHONPATH entries', () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'renixx-workspace-'));
  const srcDir = path.join(workspace, 'src', 'renixx');
  fs.mkdirSync(srcDir, { recursive: true });
  fs.writeFileSync(path.join(srcDir, '__init__.py'), '');

  const env = buildPythonEnv('python', { fsPath: workspace });
  const entries = env.PYTHONPATH.split(path.delimiter);

  assert.equal(entries[0], path.join(workspace, 'src'));
  assert.equal(entries.filter((entry) => entry === path.join(workspace, 'src')).length, 1);
});

test('buildPythonEnv returns original env when no src folder exists', () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'renixx-workspace-'));
  const env = buildPythonEnv('python', { fsPath: workspace });
  assert.equal(env.PYTHONPATH, undefined);
});
