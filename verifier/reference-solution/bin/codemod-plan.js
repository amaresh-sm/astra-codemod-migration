#!/usr/bin/env node
'use strict';

const { parseArgs } = require('../src/args');
const { plan } = require('../src/planner');

try {
  const options = parseArgs(process.argv.slice(2));
  const result = plan(options);
  process.stdout.write(JSON.stringify(result) + '\n');
} catch (error) {
  process.stderr.write(`codemod-plan: ${error.message}\n`);
  process.exitCode = 1;
}
