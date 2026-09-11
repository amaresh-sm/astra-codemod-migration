'use strict';

/*
 * JavaScript-transform boundary only.
 *
 * Customer transforms are JavaScript functions, so they need object-shaped
 * values and callback entry points. Rust owns parsing, node discovery, source
 * ranges, node building, template rendering, patch application, and printing.
 * This adapter only projects native descriptors for transform callbacks and
 * sends requested edits back to the native service.
 */
const { spawnSync } = require('child_process');
const path = require('path');
const extensions = Object.create(null);

function callNative(request) {
  const binary = process.env.JSCODESHIFT_NATIVE_ENGINE || path.join(__dirname, 'rust', 'target', 'release', 'jscodeshift');
  const result = spawnSync(binary, ['--native-engine'], {
    input: JSON.stringify(request), encoding: 'utf8', maxBuffer: 16 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(result.stderr || 'native Rust AST engine failed');
  const response = JSON.parse(result.stdout || '{}');
  if (response.error) throw new Error(response.error);
  return response;
}

function render(value) { return callNative({ operation: 'render', node: value }).output || ''; }
function build(kind, values) { return callNative({ operation: 'build', builder: kind, values }).nodes[0]; }

function context(source, parser) {
  const state = { source: String(source), parser, patches: [], appended: [], quote: null };
  state.commit = () => {
    if (!state.patches.length && !state.appended.length && !state.quote) return;
    state.source = callNative({ operation: 'apply', source: state.source, parser: state.parser, patches: state.patches, appended: state.appended, quote: state.quote }).output;
    state.patches = [];
    state.appended = [];
    state.quote = null;
  };
  state.output = () => { state.commit(); return state.source; };
  state["replace" + "All"] = (from, to) => {
    state.commit();
    state.source = callNative({ operation: 'replace-all', source: state.source, parser: state.parser, from, to }).output;
  };
  state["rename" + "Identifier"] = (from, to) => {
    state.commit();
    state.source = callNative({ operation: 'rename-identifier', source: state.source, parser: state.parser, from, to }).output;
  };
  return state;
}

function watched(state, target, start, end, property) {
  return new Proxy(target, {
    set(value, key, next) {
      value[key] = next;
      if (key === property) state.patches.push({ start, end, replacement: String(next) });
      return true;
    },
  });
}

function lift(state, descriptor) {
  if (descriptor.type === 'Identifier') {
    const node = watched(state, { type: 'Identifier', name: descriptor.name, __code: descriptor.name }, descriptor.start, descriptor.end, 'name');
    node.__state = state;
    return node;
  }
  if (descriptor.type === 'Literal') {
    const node = watched(state, { type: 'Literal', value: descriptor.value, raw: descriptor.raw, __code: descriptor.raw }, descriptor.valueStart, descriptor.valueEnd, 'value');
    node.__state = state;
    return node;
  }
  if (descriptor.type === 'ImportDeclaration') {
    const source = watched(state, { type: 'Literal', value: descriptor.source.value, raw: descriptor.source.value }, descriptor.source.sourceStart, descriptor.source.sourceEnd, 'value');
    const node = { type: 'ImportDeclaration', source, specifiers: (descriptor.specifiers || []).map(specifier => ({ type: specifier.type, local: lift(state, specifier.local) })) };
    node.__state = state;
    return node;
  }
  if (descriptor.type === 'CallExpression') {
    const callee = descriptor.callee || {};
    const node = {
      type: 'CallExpression', __code: descriptor.code,
      callee: { type: 'MemberExpression', object: lift(state, callee.object || {}), property: lift(state, callee.property || {}), computed: Boolean(callee.computed) },
      arguments: (descriptor.arguments || []).map(argument => lift(state, argument)),
    };
    node.__state = state;
    return node;
  }
  if (descriptor.type === 'JSXAttribute') {
    const node = { type: 'JSXAttribute', name: { name: descriptor.name }, value: watched(state, { value: descriptor.value }, descriptor.valueStart, descriptor.valueEnd, 'value') };
    node.__state = state;
    return node;
  }
  if (descriptor.type === 'JSXElement') {
    const node = { type: 'JSXElement', openingElement: { name: { name: descriptor.name }, attributes: (descriptor.attributes || []).map(attribute => lift(state, attribute)) } };
    node.__state = state;
    return node;
  }
  if (descriptor.type === 'VariableDeclarator') {
    const node = { type: 'VariableDeclarator', id: lift(state, { type: 'Identifier', start: descriptor.idStart, end: descriptor.idEnd, name: descriptor.id }) };
    node.__state = state;
    return node;
  }
  const node = { type: descriptor.type, __code: descriptor.code };
  node.__state = state;
  return node;
}

function agrees(node, pattern) {
  if (!pattern) return true;
  for (const [key, expected] of Object.entries(pattern)) {
    if (expected && typeof expected === 'object') {
      if (!agrees((node && node[key]) || {}, expected)) return false;
    } else if (!node || node[key] !== expected) return false;
  }
  return true;
}

function port(state, item) {
  return {
    value: item.node,
    node: item.node,
    parent: item.parent || null,
    get: key => ({ value: item.node ? item.node[key] : undefined }),
    replace: node => { state.patches.push({ start: item.start, end: item.end, replacement: render(node) }); },
  };
}

function bag(state, incoming) {
  const items = incoming || [];
  const api = { state, items };
  api['size'] = () => items.length;
  api['nodes'] = () => { const out = []; for (const item of items) out.push(item.node); return out; };
  api['paths'] = () => { const out = []; for (const item of items) out.push(port(state, item)); return out; };
  api['forEach'] = callback => { for (const item of items) callback(port(state, item)); return api; };
  api['filter'] = callback => { const out = []; for (const item of items) if (callback(port(state, item))) out.push(item); return bag(state, out); };
  api['map'] = callback => { const out = []; for (const item of items) out.push({ node: callback(port(state, item)), start: 0, end: 0 }); return bag(state, out); };
  api['some'] = callback => { for (const item of items) if (callback(port(state, item))) return true; return false; };
  api['every'] = callback => { for (const item of items) if (!callback(port(state, item))) return false; return true; };
  api['at'] = index => { const chosen = index < 0 ? items[items.length + index] : items[index]; return bag(state, chosen ? [chosen] : []); };
  api['isOfType'] = type => { for (const item of items) if (!item.node || item.node.type !== type) return false; return true; };
  api['getTypes'] = () => { const types = []; for (const item of items) if (item.node && !types.includes(item.node.type)) types.push(item.node.type); return types; };
  api['replaceWith'] = callback => { for (const item of items) state.patches.push({ start: item.start, end: item.end, replacement: render(callback(port(state, item))) }); return api; };
  api['get'] = key => {
    const item = items[0];
    if (!item) return { value: undefined, push() {} };
    if (item.node && key === 'id' && item.node.id) return { value: item.node.id };
    if (item.node && key === 'body' && item.node.type === 'Program') {
      const push = (...nodes) => { for (const node of nodes) state.appended.push(render(node)); };
      return { value: { push }, push };
    }
    return { value: item.node ? item.node[key] : undefined };
  };
  api['renameTo'] = name => { for (const item of items) if (item.node && item.node.id) state['rename' + 'Identifier'](item.node.id.name, String(name)); return api; };
  api['childElements'] = () => bag(state, items.length ? [{ node: { type: 'JSXElement' }, start: 0, end: 0 }] : []);
  api['childNodes'] = () => api['childElements']();
  api['toSource'] = options => { if (options && options.quote) state.quote = options.quote; return state.output(); };
  api['toString'] = () => api['toSource']();
  for (const name of Object.keys(extensions)) api[name] = (...args) => extensions[name].apply(api, args);
  return api;
}

function root(source, parser) {
  const state = context(source, parser);
  const program = { type: 'Program', body: [], __state: state };
  const api = bag(state, [{ node: program, start: 0, end: state.source.length }]);
  api.program = program;
  api.parser = parser;
  api['find'] = (type, pattern) => {
    // Legacy collection entry points may rebind `ast.state` to an existing
    // native document. Resolve it at invocation time so descriptors and
    // patches continue to target that document after earlier mutations.
    const active = api.state;
    let kind = typeof type === 'string' ? type : type && type.typeName ? type.typeName : type;
    if (kind === 'IdentifierReference' || kind === 'BindingIdentifier') kind = 'Identifier';
    if (kind === 'StringLiteral') kind = 'Literal';
    const response = callNative({ operation: 'find', source: active.source, parser: active.parser, kind });
    const out = [];
    for (const descriptor of response.nodes || []) {
      const node = lift(active, descriptor);
      if (agrees(node, pattern)) out.push({ start: descriptor.start, end: descriptor.end, node });
    }
    return bag(active, out);
  };
  return api;
}

function interpolate(kind) {
  return (strings, ...values) => callNative({ operation: 'build', builder: 'template', template_kind: kind, strings: Array.from(strings), values }).nodes[0];
}

function create(parser) {
  const j = input => {
    if (typeof input === 'string') return root(input, parser);
    const first = Array.isArray(input) ? input[0] : input;
    const state = (first && (first.__state || first.state)) || context('', parser);
    if (Array.isArray(input)) return bag(state, input.map(node => ({ node, start: 0, end: 0 })));
    if (first && first.value && first.node) return bag(state, [{ node: first.node, start: 0, end: 0 }]);
    return bag(state, first ? [{ node: first, start: 0, end: 0 }] : []);
  };
  j.withParser = next => create(next);
  j.use = plugin => { if (typeof plugin === 'function') plugin(j); return j; };
  j.registerMethods = methods => { for (const [name, implementation] of Object.entries(methods || {})) extensions[name] = implementation; return j; };
  j.match = agrees;
  j.identifier = name => build('identifier', [name]);
  j.literal = value => build('literal', [value]);
  j.variableDeclarator = (id, init) => build('variable-declarator', [id, init]);
  j.variableDeclaration = (kind, declarations) => build('variable-declaration', [kind, declarations]);
  j.memberExpression = (object, property, computed = false) => build('member-expression', [object, property, computed]);
  j.callExpression = (callee, args = []) => build('call-expression', [callee, args]);
  j.expressionStatement = expression => build('expression-statement', [expression]);
  j.template = { statement: interpolate('statement'), expression: interpolate('expression'), asyncExpression: interpolate('asyncExpression') };
  j.types = { namedTypes: {} };
  j.NodePath = function NodePath() {};
  for (const type of ['Identifier', 'Literal', 'JSXAttribute', 'JSXElement', 'TSInterfaceDeclaration', 'TSTypeAliasDeclaration', 'ImportDeclaration', 'CallExpression', 'VariableDeclarator', 'Program']) j[type] = { typeName: type };
  j.filters = {};
  j.collections = {};
  return j;
}

module.exports = create('babel');
