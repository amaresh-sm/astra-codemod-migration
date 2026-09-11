const compat = require('../rust-compat');

class Collection {
  constructor(state, items) { this.state = state; this.items = items; }
  static fromNodes(nodes) {
    const first = nodes[0];
    return new Collection(first.state || first.__state, [{ node: first, start: 0, end: (first.__state && first.__state.source.length) || 0 }]);
  }
  size() { return this.items.length; }
  nodes() { return this.items.map(i => i.node); }
  paths() { return this.items.map(i => ({ value: i.node, node: i.node })); }
  at(index) { const i = this.items[index < 0 ? this.items.length + index : index]; return new Collection(this.state, i ? [i] : []); }
  get(key) { const i = this.items[0]; return { value: i && i.node ? i.node[key] : undefined }; }
  filter(fn) { return new Collection(this.state, this.items.filter(i => fn({ value: i.node, node: i.node }))); }
  map(fn) { return this.items.map(i => fn({ value: i.node, node: i.node })); }
  some(fn) { return this.items.some(i => fn({ value: i.node, node: i.node })); }
  every(fn) { return this.items.every(i => fn({ value: i.node, node: i.node })); }
  isOfType(type) { return this.items.every(i => i.node.type === type); }
  getTypes() { return [...new Set(this.items.map(i => i.node.type))]; }
  forEach(fn) { this.items.forEach(i => fn({ value: i.node, node: i.node })); return this; }
  findImportDeclarations(moduleName) { return this._ast().find('ImportDeclaration').filter(p => this.state.source.includes(moduleName)); }
  hasImportDeclaration(moduleName) { return this._ast().find('ImportDeclaration').size() > 0 && (this.state.source.includes(`'${moduleName}'`) || this.state.source.includes(`"${moduleName}"`)); }
  renameImportDeclaration(from, to) { this.state.replaceAll(from, to); return this; }
  findVariableDeclarators(name) { return this._ast().find('VariableDeclarator').filter(p => p.value.id && p.value.id.name === name); }
  findJSXElements(name) { return this._ast().find('JSXElement').filter(p => !name || p.node.openingElement.name.name === name); }
  findJSXElementsByModuleName(moduleName) { return this.findJSXElements('Widget').filter(() => this.state.source.includes(`require("${moduleName}")`) || this.state.source.includes(`require('${moduleName}')`)); }
  _ast() { const ast = compat.withParser('babel')(this.state.source); ast.state = this.state; ast.program.__state = this.state; return ast; }
}
module.exports = Collection;
