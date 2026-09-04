use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process;

const DEFAULT_IGNORES: [&str; 4] = [".git", "node_modules", "dist", "coverage"];

fn fail(message: &str) -> ! {
    eprintln!("codemod-planner: {message}");
    process::exit(1);
}

fn glob_matches(pattern: &str, value: &str) -> bool {
    let pattern_parts: Vec<&str> = pattern.split('*').collect();
    if pattern_parts.len() == 1 { return pattern == value; }
    let mut cursor = 0usize;
    if !value.starts_with(pattern_parts[0]) { return false; }
    cursor += pattern_parts[0].len();
    for part in pattern_parts.iter().skip(1) {
        if part.is_empty() { continue; }
        match value[cursor..].find(part) {
            Some(position) => cursor += position + part.len(),
            None => return false,
        }
    }
    pattern.ends_with('*') || cursor == value.len()
}

fn ignored(relative: &str, rules: &[String]) -> bool {
    let parts: Vec<&str> = relative.split('/').collect();
    rules.iter().any(|rule| parts.iter().any(|part| *part == rule) || glob_matches(rule, relative))
}

fn visit(current: &Path, root: &Path, extensions: &[String], rules: &[String], files: &mut Vec<String>) {
    let entries = fs::read_dir(current).unwrap_or_else(|err| fail(&format!("cannot read {}: {err}", current.display())));
    let mut entries: Vec<_> = entries.filter_map(Result::ok).collect();
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        let absolute = entry.path();
        let relative_path = absolute.strip_prefix(root).expect("root prefix");
        let relative = relative_path.to_string_lossy().replace('\\', "/");
        if ignored(&relative, rules) { continue; }
        let kind = fs::symlink_metadata(&absolute).unwrap_or_else(|err| fail(&format!("cannot stat {}: {err}", absolute.display())));
        let matches_extension = extensions.is_empty() || extensions.iter().any(|ext| absolute.extension().and_then(|value| value.to_str()) == Some(ext));
        if kind.file_type().is_symlink() {
            let target = match fs::canonicalize(&absolute) { Ok(value) => value, Err(_) => continue };
            if target.starts_with(root) && target.is_file() && matches_extension { files.push(relative); }
        } else if kind.is_dir() {
            visit(&absolute, root, extensions, rules, files);
        } else if kind.is_file() && matches_extension {
            files.push(relative);
        }
    }
}

fn json_string(value: &str) -> String {
    format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\""))
}

fn main() {
    let mut root: Option<PathBuf> = None;
    let mut extensions = Vec::new();
    let mut ignores = Vec::new();
    let args: Vec<String> = env::args().skip(1).collect();
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--root" => { index += 1; root = args.get(index).map(PathBuf::from); }
            "--extensions" => {
                index += 1;
                if let Some(value) = args.get(index) { extensions = value.split(',').filter_map(|item| { let value = item.trim().trim_start_matches('.'); (!value.is_empty()).then(|| value.to_string()) }).collect(); }
            }
            "--ignore" => { index += 1; if let Some(value) = args.get(index) { ignores.push(value.clone()); } }
            value => fail(&format!("unknown option {value}")),
        }
        index += 1;
    }
    let root = root.unwrap_or_else(|| fail("--root is required"));
    let root = fs::canonicalize(&root).unwrap_or_else(|_| fail(&format!("root does not exist: {}", root.display())));
    if !root.is_dir() { fail(&format!("root is not a directory: {}", root.display())); }
    let mut rules: Vec<String> = DEFAULT_IGNORES.iter().map(|item| (*item).to_string()).collect();
    rules.append(&mut ignores);
    let mut files = Vec::new();
    visit(&root, &root, &extensions, &rules, &mut files);
    files.sort();
    let values = files.iter().map(|value| json_string(value)).collect::<Vec<_>>().join(",");
    println!("{{\"files\":[{values}],\"count\":{}}}", files.len());
}
