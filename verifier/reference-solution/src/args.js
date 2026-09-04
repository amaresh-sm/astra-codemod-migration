'use strict';

function parseArgs(argv) {
  const options = { root: null, extensions: null, ignores: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === '--root') options.root = argv[++index];
    else if (value === '--extensions') options.extensions = argv[++index];
    else if (value === '--ignore') options.ignores.push(argv[++index]);
    else if (value === '--help') {
      process.stdout.write('Usage: codemod-plan --root DIR [--extensions js,ts] [--ignore PATTERN]\n');
      process.exit(0);
    } else throw new Error(`unknown option ${value}`);
  }
  if (!options.root) throw new Error('--root is required');
  if (options.extensions === undefined) throw new Error('--extensions needs a value');
  if (options.ignores.some((rule) => !rule)) throw new Error('--ignore needs a value');
  return options;
}

module.exports = { parseArgs };
