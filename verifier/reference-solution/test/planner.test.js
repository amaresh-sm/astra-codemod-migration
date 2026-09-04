'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { plan } = require('../src/planner');

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'codemod-plan-'));
  fs.mkdirSync(path.join(root, 'src'), { recursive: true });
  fs.mkdirSync(path.join(root, 'node_modules/pkg'), { recursive: true });
  fs.mkdirSync(path.join(root, 'dist'), { recursive: true });
  fs.writeFileSync(path.join(root, 'src/z.ts'), 'export const z = 1;');
  fs.writeFileSync(path.join(root, 'src/a.js'), 'export const a = 1;');
  fs.writeFileSync(path.join(root, 'README.md'), '# sample');
  fs.writeFileSync(path.join(root, 'node_modules/pkg/index.js'), 'ignored');
  fs.writeFileSync(path.join(root, 'dist/out.js'), 'ignored');
  return root;
}

test('plans sorted source files and applies default ignores', () => {
  const root = fixture();
  assert.deepEqual(plan({ root, extensions: 'js,ts', ignores: [] }), {
    files: ['src/a.js', 'src/z.ts'], count: 2,
  });
});

test('empty extension list selects every regular file', () => {
  const root = fixture();
  assert.equal(plan({ root, extensions: '', ignores: [] }).count, 3);
});

test('missing roots fail clearly', () => {
  assert.throws(() => plan({ root: '/definitely/not-here', extensions: 'js', ignores: [] }), /does not exist/);
});
