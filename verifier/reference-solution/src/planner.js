'use strict';

const fs = require('node:fs');
const path = require('node:path');
const childProcess = require('node:child_process');

function plannerBinary() {
  const binary = path.resolve(__dirname, '../native/planner/target/release/codemod-planner');
  if (!fs.existsSync(binary)) throw new Error('native planner is not built; run npm run build');
  return binary;
}

function plan({ root, extensions, ignores }) {
  const args = ['--root', path.resolve(root), '--extensions', extensions || ''];
  for (const rule of ignores) args.push('--ignore', rule);
  const result = childProcess.spawnSync(plannerBinary(), args, { encoding: 'utf8' });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error((result.stderr || 'native planner failed').trim());
  try { return JSON.parse(result.stdout); } catch { throw new Error('native planner returned invalid JSON'); }
}

module.exports = { plan };
