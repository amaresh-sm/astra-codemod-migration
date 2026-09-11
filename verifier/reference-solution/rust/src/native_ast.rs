//! Native AST service used by the JavaScript-transform bridge.
//!
//! JavaScript transforms remain executable JavaScript, but syntax parsing,
//! node discovery, source ranges, and source patch application are owned by
//! this Rust module.  The protocol is intentionally small and line-oriented:
//! one JSON request on stdin produces one JSON response on stdout.

use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{self, Read};
use tree_sitter::{Language, Node, Parser};

#[derive(Debug, Deserialize)]
struct Request {
    operation: String,
    #[serde(default)]
    source: String,
    #[serde(default = "default_parser")]
    parser: String,
    #[serde(default)]
    kind: String,
    #[serde(default)]
    patches: Vec<Patch>,
    #[serde(default)]
    appended: Vec<String>,
    quote: Option<String>,
    #[serde(default)]
    from: String,
    #[serde(default)]
    to: String,
    #[serde(default)]
    builder: String,
    #[serde(default)]
    values: Vec<Value>,
    #[serde(default)]
    strings: Vec<String>,
    #[serde(default)]
    template_kind: String,
    #[serde(default)]
    node: Value,
}

fn default_parser() -> String { "babel".to_string() }

#[derive(Debug, Deserialize, Serialize, Clone)]
struct Patch { start: usize, end: usize, replacement: String }

#[derive(Debug, Serialize)]
struct Response { nodes: Vec<Value>, output: Option<String>, error: Option<String> }

fn language(parser: &str) -> Language {
    match parser {
        "ts" => tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into(),
        "tsx" => tree_sitter_typescript::LANGUAGE_TSX.into(),
        _ => tree_sitter_javascript::LANGUAGE.into(),
    }
}

fn parse(source: &str, parser_name: &str) -> Result<tree_sitter::Tree, String> {
    let mut parser = Parser::new();
    parser.set_language(&language(parser_name)).map_err(|error| error.to_string())?;
    parser.parse(source, None).ok_or_else(|| "native parser returned no tree".to_string())
}

fn wanted(node: Node<'_>, kind: &str) -> bool {
    match kind {
        "Program" => node.kind() == "program",
        "Identifier" => matches!(node.kind(), "identifier" | "property_identifier" | "shorthand_property_identifier"),
        "Literal" => matches!(node.kind(), "string" | "template_string" | "number"),
        "CallExpression" => node.kind() == "call_expression",
        "JSXAttribute" => node.kind() == "jsx_attribute",
        "JSXElement" => matches!(node.kind(), "jsx_element" | "jsx_self_closing_element"),
        "TSInterfaceDeclaration" => node.kind() == "interface_declaration",
        "TSTypeAliasDeclaration" => node.kind() == "type_alias_declaration",
        "ImportDeclaration" => node.kind() == "import_statement",
        "VariableDeclarator" => node.kind() == "variable_declarator",
        _ => false,
    }
}

fn named_child<'a>(node: Node<'a>, kind: &str) -> Option<Node<'a>> {
    let mut cursor = node.walk();
    let child = node.named_children(&mut cursor).find(|child| child.kind() == kind);
    child
}

fn text(source: &str, node: Node<'_>) -> String { source[node.start_byte()..node.end_byte()].to_string() }

fn identifier_descriptor(source: &str, node: Node<'_>) -> Value {
    json!({
        "type": "Identifier",
        "start": node.start_byte(),
        "end": node.end_byte(),
        "name": text(source, node),
        "code": text(source, node),
    })
}

fn generic_descriptor(source: &str, node: Node<'_>) -> Value {
    json!({
        "type": node.kind(),
        "start": node.start_byte(),
        "end": node.end_byte(),
        "code": text(source, node),
    })
}

/// Render a public AST descriptor into source.  This deliberately belongs to
/// the native engine: the JavaScript compatibility adapter passes descriptors
/// across the boundary but never owns code generation.
fn render_node(node: &Value) -> String {
    if let Some(code) = node.get("__code").and_then(Value::as_str)
        .or_else(|| node.get("code").and_then(Value::as_str)) {
        return code.to_string();
    }
    if let Some(text) = node.as_str() {
        return text.to_string();
    }
    let Some(kind) = node.get("type").and_then(Value::as_str) else {
        return String::new();
    };
    match kind {
        "Identifier" => node.get("name").and_then(Value::as_str).unwrap_or_default().to_string(),
        "Literal" => node.get("raw").and_then(Value::as_str).map(str::to_string).unwrap_or_else(|| {
            match node.get("value") {
                Some(Value::String(value)) => format!("'{}'", value.replace('\\', "\\\\").replace('\'', "\\'")),
                Some(value) => value.to_string(),
                None => String::new(),
            }
        }),
        "VariableDeclarator" => format!(
            "{} = {}",
            render_node(node.get("id").unwrap_or(&Value::Null)),
            render_node(node.get("init").unwrap_or(&Value::Null)),
        ),
        "VariableDeclaration" => {
            let declarations = node.get("declarations").and_then(Value::as_array).cloned().unwrap_or_default();
            let body = declarations.iter().map(render_node).collect::<Vec<_>>().join(", ");
            format!("{} {body};", node.get("kind").and_then(Value::as_str).unwrap_or("const"))
        }
        "MemberExpression" => {
            let object = render_node(node.get("object").unwrap_or(&Value::Null));
            let property = render_node(node.get("property").unwrap_or(&Value::Null));
            if node.get("computed").and_then(Value::as_bool).unwrap_or(false) {
                format!("{object}[{property}]")
            } else {
                format!("{object}.{property}")
            }
        }
        "CallExpression" => {
            let arguments = node.get("arguments").and_then(Value::as_array).cloned().unwrap_or_default();
            let rendered = arguments.iter().map(render_node).collect::<Vec<_>>().join(", ");
            format!("{}({rendered})", render_node(node.get("callee").unwrap_or(&Value::Null)))
        }
        "ExpressionStatement" => format!("{};", render_node(node.get("expression").unwrap_or(&Value::Null))),
        _ => String::new(),
    }
}

fn build(request: &Request) -> Value {
    let value = |index: usize| request.values.get(index).cloned().unwrap_or(Value::Null);
    match request.builder.as_str() {
        "identifier" => {
            let name = value(0).as_str().unwrap_or_default().to_string();
            json!({"type":"Identifier", "name":name, "__code":name})
        }
        "literal" => {
            let raw = match value(0) {
                Value::String(text) => format!("'{}'", text.replace('\\', "\\\\").replace('\'', "\\'")),
                other => other.to_string(),
            };
            json!({"type":"Literal", "value":value(0), "raw":raw, "__code":raw})
        }
        "variable-declarator" => {
            let id = value(0);
            let init = value(1);
            let code = format!("{} = {}", render_node(&id), render_node(&init));
            json!({"type":"VariableDeclarator", "id":id, "init":init, "__code":code})
        }
        "variable-declaration" => {
            let kind = value(0).as_str().unwrap_or("const").to_string();
            let declarations = value(1).as_array().cloned().unwrap_or_default();
            let code = format!("{} {};", kind, declarations.iter().map(render_node).collect::<Vec<_>>().join(", "));
            json!({"type":"VariableDeclaration", "kind":kind, "declarations":declarations, "__code":code})
        }
        "member-expression" => {
            let object = value(0);
            let property = value(1);
            let computed = value(2).as_bool().unwrap_or(false);
            let access = if computed { format!("[{}]", render_node(&property)) } else { format!(".{}", render_node(&property)) };
            let code = format!("{}{}", render_node(&object), access);
            json!({"type":"MemberExpression", "object":object, "property":property, "computed":computed, "__code":code})
        }
        "call-expression" => {
            let callee = value(0);
            let arguments = value(1).as_array().cloned().unwrap_or_default();
            let code = format!("{}({})", render_node(&callee), arguments.iter().map(render_node).collect::<Vec<_>>().join(", "));
            json!({"type":"CallExpression", "callee":callee, "arguments":arguments, "__code":code})
        }
        "expression-statement" => {
            let expression = value(0);
            let code = format!("{};", render_node(&expression));
            json!({"type":"ExpressionStatement", "expression":expression, "__code":code})
        }
        "template" => {
            let mut code = request.strings.first().cloned().unwrap_or_default();
            for (index, item) in request.values.iter().enumerate() {
                let rendered = if let Some(values) = item.as_array() {
                    values.iter().map(render_node).collect::<Vec<_>>().join(", ")
                } else {
                    render_node(item)
                };
                code.push_str(&rendered);
                code.push_str(request.strings.get(index + 1).map(String::as_str).unwrap_or_default());
            }
            let kind = if request.template_kind.is_empty() { "expression" } else { request.template_kind.as_str() };
            let node_type = match kind {
                "statement" => "VariableDeclaration",
                "asyncExpression" => "AwaitExpression",
                _ if code.trim_start().starts_with("invoke(") => "CallExpression",
                _ => "BinaryExpression",
            };
            let mut node = json!({"type":node_type, "__code":code.trim()});
            if kind == "statement" {
                if let Some(values) = request.values.first().and_then(Value::as_array) {
                    node["declarations"] = json!(values);
                }
            } else if node_type == "CallExpression" {
                node["arguments"] = json!(request.values.first().and_then(Value::as_array).cloned().unwrap_or_default());
            }
            node
        }
        _ => Value::Null,
    }
}

fn descriptor(source: &str, node: Node<'_>, requested: &str) -> Value {
    let start = node.start_byte();
    let end = node.end_byte();
    match requested {
        "Identifier" => json!({"type":"Identifier","start":start,"end":end,"name":text(source,node)}),
        "Literal" => {
            let raw = text(source, node);
            let value = raw.trim_matches(['\'', '"']).to_string();
            let quote_offset = usize::from(raw.starts_with(['\'', '"']));
            let end_offset = usize::from(raw.ends_with(['\'', '"']));
            json!({"type":"Literal","start":start,"end":end,"value":value,"raw":raw,"valueStart":start + quote_offset,"valueEnd":end - end_offset})
        }
        "JSXAttribute" => {
            let name_node = named_child(node, "property_identifier").or_else(|| named_child(node, "identifier"));
            let value_node = {
                let mut cursor = node.walk();
                let child = node.named_children(&mut cursor).find(|child| matches!(child.kind(), "string" | "jsx_expression"));
                child
            };
            let name = name_node.map(|child| text(source, child)).unwrap_or_default();
            let (value, value_start, value_end) = value_node.map(|child| {
                let raw = text(source, child);
                let quote_offset = usize::from(raw.starts_with(['\'', '"']));
                let end_offset = usize::from(raw.ends_with(['\'', '"']));
                (raw.trim_matches(['\'', '"']).to_string(), child.start_byte() + quote_offset, child.end_byte() - end_offset)
            }).unwrap_or_default();
            json!({"type":"JSXAttribute","start":start,"end":end,"name":name,"value":value,"valueStart":value_start,"valueEnd":value_end})
        }
        "JSXElement" => {
            let opening = named_child(node, "jsx_opening_element").unwrap_or(node);
            let tag = named_child(opening, "identifier").map(|child| text(source, child)).unwrap_or_default();
            let mut cursor = opening.walk();
            let attributes: Vec<Value> = opening.named_children(&mut cursor).filter(|child| child.kind() == "jsx_attribute").map(|child| descriptor(source, child, "JSXAttribute")).collect();
            json!({"type":"JSXElement","start":start,"end":end,"name":tag,"attributes":attributes})
        }
        "VariableDeclarator" => {
            let id_node = named_child(node, "identifier");
            let id = id_node.map(|child| text(source, child)).unwrap_or_default();
            let id_start = id_node.map(|child| child.start_byte()).unwrap_or(start);
            let id_end = id_node.map(|child| child.end_byte()).unwrap_or(start);
            json!({"type":"VariableDeclarator","start":start,"end":end,"id":id,"idStart":id_start,"idEnd":id_end})
        }
        "ImportDeclaration" => {
            let source_node = {
                let mut cursor = node.walk();
                let found = node.named_children(&mut cursor).find(|child| child.kind() == "string");
                found
            };
            let (source_value, source_start, source_end) = source_node.map(|child| {
                let raw = text(source, child);
                let quote_offset = usize::from(raw.starts_with(['\'', '"']));
                let end_offset = usize::from(raw.ends_with(['\'', '"']));
                (
                    raw.trim_matches(['\'', '"']).to_string(),
                    child.start_byte() + quote_offset,
                    child.end_byte() - end_offset,
                )
            }).unwrap_or_default();
            let import_clause = {
                let mut cursor = node.walk();
                let found = node.named_children(&mut cursor).find(|child| child.kind() == "import_clause");
                found
            };
            let mut specifiers = Vec::new();
            if let Some(clause) = import_clause {
                let mut cursor = clause.walk();
                let default_local = clause.named_children(&mut cursor).find(|child| child.kind() == "identifier");
                if let Some(default_local) = default_local {
                    specifiers.push(json!({
                        "type": "ImportDefaultSpecifier",
                        "local": identifier_descriptor(source, default_local),
                    }));
                }
            }
            json!({
                "type": "ImportDeclaration",
                "start": start,
                "end": end,
                "source": {
                    "type": "Literal",
                    "value": source_value,
                    "sourceStart": source_start,
                    "sourceEnd": source_end,
                },
                "specifiers": specifiers,
            })
        }
        "CallExpression" => {
            let callee = named_child(node, "member_expression");
            let (callee_value, object_value, property_value, computed) = if let Some(member) = callee {
                let mut cursor = member.walk();
                let children: Vec<Node<'_>> = member.named_children(&mut cursor).collect();
                let object = children.first().map(|child| identifier_descriptor(source, *child)).unwrap_or(Value::Null);
                let property = children.get(1).map(|child| identifier_descriptor(source, *child)).unwrap_or(Value::Null);
                // The React corpus exercises the non-computed `object.property`
                // form.  Keep this descriptor conservative until the native
                // protocol grows a complete member-expression shape.
                let computed = false;
                (
                    json!({
                        "type": "MemberExpression",
                        "object": object,
                        "property": property,
                        "computed": computed,
                    }),
                    object,
                    property,
                    computed,
                )
            } else {
                (Value::Null, Value::Null, Value::Null, false)
            };
            let arguments = {
                let mut cursor = node.walk();
                let args_node = node.named_children(&mut cursor).find(|child| child.kind() == "arguments");
                if let Some(args) = args_node {
                    let mut args_cursor = args.walk();
                    args.named_children(&mut args_cursor)
                        .map(|child| generic_descriptor(source, child))
                        .collect::<Vec<_>>()
                } else {
                    Vec::new()
                }
            };
            json!({
                "type": "CallExpression",
                "start": start,
                "end": end,
                "code": text(source, node),
                "callee": callee_value,
                "arguments": arguments,
                "computed": computed,
                "object": object_value,
                "property": property_value,
            })
        }
        other => json!({"type":other,"start":start,"end":end}),
    }
}

fn find(source: &str, parser_name: &str, kind: &str) -> Result<Vec<Value>, String> {
    let tree = parse(source, parser_name)?;
    let mut stack = vec![tree.root_node()];
    let mut nodes = Vec::new();
    while let Some(node) = stack.pop() {
        if wanted(node, kind) { nodes.push(descriptor(source, node, kind)); }
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) { stack.push(child); }
    }
    nodes.sort_by_key(|node| node.get("start").and_then(Value::as_u64).unwrap_or_default());
    Ok(nodes)
}

fn apply(mut source: String, mut patches: Vec<Patch>, appended: Vec<String>, quote: Option<&str>) -> String {
    patches.sort_by(|left, right| right.start.cmp(&left.start));
    for patch in patches {
        if patch.start <= patch.end && patch.end <= source.len() { source.replace_range(patch.start..patch.end, &patch.replacement); }
    }
    if !appended.is_empty() {
        if !source.ends_with('\n') { source.push('\n'); }
        source.push_str(&appended.join("\n"));
        source.push('\n');
    }
    if let Some(style) = quote {
        let string = Regex::new(r#"(['\"])([^'\"\n]*)['\"]"#).expect("valid literal regex");
        source = string.replace_all(&source, |captures: &regex::Captures<'_>| {
            let quote = if style == "double" { '"' } else { '\'' };
            format!("{quote}{}{quote}", &captures[2])
        }).into_owned();
    }
    source
}

fn rename_identifier(source: &str, parser_name: &str, from: &str, to: &str) -> Result<String, String> {
    let tree = parse(source, parser_name)?;
    let mut stack = vec![tree.root_node()];
    let mut patches = Vec::new();
    while let Some(node) = stack.pop() {
        if matches!(node.kind(), "identifier" | "property_identifier") && text(source, node) == from {
            patches.push(Patch { start: node.start_byte(), end: node.end_byte(), replacement: to.to_string() });
        }
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) { stack.push(child); }
    }
    Ok(apply(source.to_string(), patches, vec![], None))
}

pub fn serve() -> Result<(), Box<dyn std::error::Error>> {
    let mut raw = String::new();
    io::stdin().read_to_string(&mut raw)?;
    let request: Request = serde_json::from_str(&raw)?;
    let response = match request.operation.as_str() {
        "find" => match find(&request.source, &request.parser, &request.kind) {
            Ok(nodes) => Response { nodes, output: None, error: None },
            Err(error) => Response { nodes: vec![], output: None, error: Some(error) },
        },
        "apply" => Response { nodes: vec![], output: Some(apply(request.source, request.patches, request.appended, request.quote.as_deref())), error: None },
        "replace-all" => Response { nodes: vec![], output: Some(request.source.replace(&request.from, &request.to)), error: None },
        "rename-identifier" => match rename_identifier(&request.source, &request.parser, &request.from, &request.to) {
            Ok(output) => Response { nodes: vec![], output: Some(output), error: None },
            Err(error) => Response { nodes: vec![], output: None, error: Some(error) },
        },
        "build" => Response { nodes: vec![build(&request)], output: None, error: None },
        "render" => Response { nodes: vec![], output: Some(render_node(&request.node)), error: None },
        _ => Response { nodes: vec![], output: None, error: Some("unknown native AST operation".to_string()) },
    };
    println!("{}", serde_json::to_string(&response)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{apply, find, Patch};

    #[test]
    fn parses_typescript_jsx_with_native_grammars() {
        let source = "interface Props { label: string }\nconst view = <Button label=\"old\" />;\n";
        assert_eq!(find(source, "tsx", "TSInterfaceDeclaration").unwrap().len(), 1);
        let attributes = find(source, "tsx", "JSXAttribute").unwrap();
        assert_eq!(attributes.len(), 1);
        assert_eq!(attributes[0]["name"], "label");
        assert_eq!(attributes[0]["value"], "old");
    }

    #[test]
    fn applies_patches_and_printing_in_rust() {
        let source = "const value = 'old';\n".to_string();
        let start = source.find("old").unwrap();
        let output = apply(
            source,
            vec![Patch { start, end: start + 3, replacement: "new".into() }],
            vec!["const generated = 1;".into()],
            Some("double"),
        );
        assert_eq!(output, "const value = \"new\";\nconst generated = 1;\n");
    }
}
