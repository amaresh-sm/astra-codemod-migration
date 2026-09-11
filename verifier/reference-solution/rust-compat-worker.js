'use strict';
const fs = require('fs');
const Module = require('module');
const path = require('path');
const compat = require('./rust-compat');
const [transformPath, filePath, parser, optionsJson] = process.argv.slice(2);
const source = fs.readFileSync(0, 'utf8');
let options = {};
try { options = JSON.parse(optionsJson || '{}'); } catch (_) {}
function loadTransform(file) {
  let text = fs.readFileSync(file, 'utf8');
  if (/\.tsx?$/.test(file)) {
    text = text.replace(/:\s*(any|unknown|string|number|boolean)(?=\s*[,)=;{])/g, '')
      .replace(/export\s+default\s+/, 'module.exports = ');
  }
  const mod = new Module(file, module); mod.filename = file; mod.paths = Module._nodeModulePaths(path.dirname(file)); mod._compile(text, file); return mod.exports;
}
function emit(status, output, message) { process.stdout.write(`${status}\n${Buffer.from(output || '', 'utf8').toString('base64')}\n${Buffer.from(message || '', 'utf8').toString('base64')}\n`); }
(async () => {
  try {
    const loaded = loadTransform(transformPath); const fn = typeof loaded === 'function' ? loaded : loaded.default;
    if (typeof fn !== 'function') throw new Error('transform does not export a function');
    // The transform-declared parser is part of jscodeshift's public API.  The
    // Rust engine uses it for native tree-sitter grammar selection.
    const selectedParser = loaded.parser || fn.parser || parser;
    const j = compat.withParser(selectedParser); const reports = []; const stats = {};
    const api = { jscodeshift: j, j, stats: key => { stats[key] = (stats[key] || 0) + 1; }, report: msg => reports.push(String(msg)) };
    const result = await fn({ path: filePath, source }, api, options);
    if (result == null) return emit('skip', '', reports.join('\n'));
    const output = typeof result === 'string' ? result : (result && typeof result.toSource === 'function' ? result.toSource() : String(result));
    const message = [...reports, ...Object.entries(stats).map(([k,v]) => `${k}: ${v}`)];
    if (message.length) message.unshift('Stats:');
    emit(output === source ? 'nochange' : 'ok', output, message.join('\n'));
  } catch (error) { emit('error', '', error && error.stack ? error.stack : String(error)); }
})();
