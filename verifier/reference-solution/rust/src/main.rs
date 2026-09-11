use std::collections::{BTreeMap, HashSet};
use std::env;
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Instant;

mod native_ast;

#[derive(Default, Clone)]
struct Stats {
    ok: usize,
    nochange: usize,
    skip: usize,
    error: usize,
}
struct Config {
    transform: String,
    parser: String,
    extensions: Vec<String>,
    ignores: Vec<String>,
    cpus: usize,
    in_band: bool,
    silent: bool,
    verbose: u32,
    dry: bool,
    print: bool,
    fail_on_error: bool,
    package_root: PathBuf,
    options: BTreeMap<String, Vec<String>>,
}

fn quote(s: &str) -> String {
    let mut o = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            '\r' => o.push_str("\\r"),
            '\t' => o.push_str("\\t"),
            c if c.is_control() => o.push_str(&format!("\\u{:04x}", c as u32)),
            c => o.push(c),
        }
    }
    o.push('"');
    o
}
fn options_json(o: &BTreeMap<String, Vec<String>>) -> String {
    let mut s = String::from("{");
    for (i, (k, v)) in o.iter().enumerate() {
        if i > 0 {
            s.push(',')
        }
        s.push_str(&quote(k));
        s.push(':');
        if v.len() == 1 {
            s.push_str(&quote(&v[0]))
        } else {
            s.push('[');
            for (j, x) in v.iter().enumerate() {
                if j > 0 {
                    s.push(',')
                }
                s.push_str(&quote(x))
            }
            s.push(']')
        }
    }
    s.push('}');
    s
}
fn usage() {
    println!("jscodeshift [options] PATH...\n  -t, --transform PATH  transform module\n  -c, --cpus N          worker count\n  --extensions LIST     file extensions\n  --ignore-pattern GLOB ignore matching paths\n  --ignore-config FILE  read ignore patterns\n  --gitignore            read .gitignore\n  --stdin                read newline-separated paths\n  --run-in-band          run serially\n  --dry --print --silent --fail-on-error\n  --parser NAME          parser adapter\n  --version --help");
}
fn nextval(a: &[String], i: &mut usize, x: &str) -> Result<String, String> {
    if let Some((_, v)) = x.split_once('=') {
        return Ok(v.to_string());
    }
    *i += 1;
    a.get(*i)
        .cloned()
        .ok_or_else(|| format!("option {x} requires a value"))
}
fn parse(a: &[String]) -> Result<(Config, Vec<String>), String> {
    let mut c = Config {
        transform: String::new(),
        parser: "babel".into(),
        extensions: ["js", "jsx", "mjs", "cjs", "ts", "tsx"]
            .iter()
            .map(|x| format!(".{x}"))
            .collect(),
        ignores: Vec::new(),
        cpus: thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(1),
        in_band: false,
        silent: false,
        verbose: 0,
        dry: false,
        print: false,
        fail_on_error: false,
        package_root: PathBuf::new(),
        options: BTreeMap::new(),
    };
    let mut p = Vec::new();
    let mut i = 0;
    while i < a.len() {
        let x = &a[i];
        match x.as_str() {
            "--help" | "-h" => {
                usage();
                std::process::exit(0)
            }
            "--version" | "-v" => {
                println!("jscodeshift: 17.4.0 (rust)");
                std::process::exit(0)
            }
            "--package-root" => c.package_root = PathBuf::from(nextval(a, &mut i, x)?),
            "--transform" | "-t" => c.transform = nextval(a, &mut i, x)?,
            "--cpus" | "-c" => {
                c.cpus = nextval(a, &mut i, x)?
                    .parse()
                    .map_err(|_| "invalid cpus".to_string())?
            }
            "--extensions" => {
                c.extensions = nextval(a, &mut i, x)?
                    .split(',')
                    .map(|e| format!(".{}", e.trim().trim_start_matches('.')))
                    .collect()
            }
            "--ignore-pattern" | "--ignore" => c.ignores.push(nextval(a, &mut i, x)?),
            "--ignore-config" => {
                if let Ok(t) = fs::read_to_string(nextval(a, &mut i, x)?) {
                    c.ignores.extend(
                        t.lines()
                            .map(str::trim)
                            .filter(|x| !x.is_empty())
                            .map(str::to_string),
                    );
                }
            }
            "--gitignore" => {
                if let Ok(t) =
                    fs::read_to_string(env::current_dir().unwrap_or_default().join(".gitignore"))
                {
                    c.ignores.extend(
                        t.lines()
                            .map(str::trim)
                            .filter(|x| !x.is_empty())
                            .map(str::to_string),
                    );
                }
            }
            "--run-in-band" => c.in_band = true,
            "--silent" => c.silent = true,
            "--dry" => c.dry = true,
            "--print" => c.print = true,
            "--fail-on-error" => c.fail_on_error = true,
            "--stdin" => {
                let mut t = String::new();
                io::stdin()
                    .read_to_string(&mut t)
                    .map_err(|e| e.to_string())?;
                p.extend(
                    t.lines()
                        .map(str::trim)
                        .filter(|x| !x.is_empty())
                        .map(str::to_string),
                );
            }
            "--parser" => c.parser = nextval(a, &mut i, x)?,
            "--parser-config" => {
                let _ = nextval(a, &mut i, x)?;
            }
            "--babel" => c.parser = "babel".into(),
            "--verbose" => c.verbose = nextval(a, &mut i, x)?.parse().unwrap_or(1),
            z if z.starts_with('-') => {
                let raw = &z[2..];
                let (k, v) = if let Some((k, v)) = raw.split_once('=') {
                    (k.to_string(), v.to_string())
                } else {
                    let k = raw.to_string();
                    let v = a
                        .get(i + 1)
                        .filter(|n| !n.starts_with('-'))
                        .cloned()
                        .unwrap_or_else(|| "true".into());
                    if v != "true" {
                        i += 1;
                    }
                    (k, v)
                };
                c.options.entry(k).or_default().push(v)
            }
            _ => p.push(x.clone()),
        }
        i += 1
    }
    if c.transform.is_empty() {
        return Err("a transform is required (--transform)".into());
    }
    if c.package_root.as_os_str().is_empty() {
        c.package_root = env::current_dir().unwrap_or_default()
    }
    if !matches!(
        c.parser.as_str(),
        "babel" | "babylon" | "flow" | "ts" | "tsx"
    ) {
        return Err(format!("unknown parser: {}", c.parser));
    }
    Ok((c, p))
}
fn ignored(p: &Path, ps: &[String]) -> bool {
    let x = p.to_string_lossy();
    ps.iter().any(|q| {
        let q = q.trim_matches('/');
        if q.contains('*') {
            let z: Vec<_> = q.split('*').collect();
            return z.len() == 2 && x.contains(z[0]) && x.ends_with(z[1]);
        }
        x.ends_with(q) || x.contains(&format!("/{q}"))
    })
}
fn discover(
    p: &Path,
    c: &Config,
    out: &mut Vec<PathBuf>,
    seen: &mut HashSet<PathBuf>,
) -> io::Result<()> {
    let m = match fs::symlink_metadata(p) {
        Ok(v) => v,
        Err(_) => {
            eprintln!("Skipping path {} which does not exist. ", p.display());
            return Ok(());
        }
    };
    if m.is_dir() {
        for e in fs::read_dir(p)? {
            let q = e?.path();
            if q.file_name()
                .map(|n| {
                    matches!(
                        n.to_string_lossy().as_ref(),
                        "node_modules" | ".git" | "dist" | "coverage"
                    )
                })
                .unwrap_or(false)
            {
                continue;
            }
            discover(&q, c, out, seen)?
        }
    } else if m.file_type().is_symlink() {
        let target = fs::canonicalize(p).unwrap_or_default();
        if target.is_file() {
            discover(&target, c, out, seen)?
        }
    } else if m.is_file()
        && c.extensions
            .iter()
            .any(|e| p.to_string_lossy().ends_with(e))
        && !ignored(p, &c.ignores)
    {
        let q = p.to_path_buf();
        if seen.insert(q.clone()) {
            out.push(q)
        }
    }
    Ok(())
}
fn decode(s: &str) -> Vec<u8> {
    let mut o = Vec::new();
    let mut b = 0u32;
    let mut n = 0;
    for c in s.bytes() {
        if c == b'=' {
            break;
        }
        let v = match c {
            b'A'..=b'Z' => c - b'A',
            b'a'..=b'z' => c - b'a' + 26,
            b'0'..=b'9' => c - b'0' + 52,
            b'+' => 62,
            b'/' => 63,
            _ => continue,
        };
        b = (b << 6) | v as u32;
        n += 6;
        if n >= 8 {
            n -= 8;
            o.push((b >> n) as u8);
            b &= (1 << n) - 1
        }
    }
    o
}
fn one(c: &Config, tr: &Path, file: &Path) -> (String, String, String) {
    let src = match fs::read(file) {
        Ok(v) => v,
        Err(e) => return ("error".into(), String::new(), e.to_string()),
    };
    let native_engine = match env::current_exe() {
        Ok(path) => path,
        Err(error) => return ("error".into(), String::new(), error.to_string()),
    };
    let mut child = match Command::new("node")
        .arg(c.package_root.join("rust-compat-worker.js"))
        .args([
            tr.to_string_lossy().as_ref(),
            file.to_string_lossy().as_ref(),
            &c.parser,
            &options_json(&c.options),
        ])
        .env("JSCODESHIFT_PACKAGE", &c.package_root)
        .env("JSCODESHIFT_NATIVE_ENGINE", native_engine)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(v) => v,
        Err(e) => return ("error".into(), String::new(), e.to_string()),
    };
    if let Some(mut i) = child.stdin.take() {
        let _ = i.write_all(&src);
    };
    let out = match child.wait_with_output() {
        Ok(v) => v,
        Err(e) => return ("error".into(), String::new(), e.to_string()),
    };
    let text = String::from_utf8_lossy(&out.stdout);
    let mut l = text.lines();
    let st = l.next().unwrap_or("error").to_string();
    let body = String::from_utf8(decode(l.next().unwrap_or(""))).unwrap_or_default();
    let msg = String::from_utf8(decode(l.next().unwrap_or("")))
        .unwrap_or_else(|_| String::from_utf8_lossy(&out.stderr).to_string());
    (st, body, msg)
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let a: Vec<String> = env::args().skip(1).collect();
    if a.first().is_some_and(|arg| arg == "--native-engine") {
        return native_ast::serve();
    }
    let (c, mut paths) = parse(&a).map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?;
    let tr = if c.transform.starts_with("http://") || c.transform.starts_with("https://") {
        let p = env::temp_dir().join(format!("jscodeshift-{}-transform.js", std::process::id()));
        let o = Command::new("curl")
            .args([
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                &c.transform,
            ])
            .output()?;
        if !o.status.success() {
            return Err("unable to download transform".into());
        }
        fs::write(&p, o.stdout)?;
        p
    } else {
        PathBuf::from(&c.transform).canonicalize()?
    };
    if paths.is_empty() {
        paths.push(".".into())
    }
    let mut files = Vec::new();
    let mut seen = HashSet::new();
    for p in &paths {
        discover(Path::new(p), &c, &mut files, &mut seen)?
    }
    files.sort();
    if files.is_empty() {
        if !c.silent {
            println!("No files selected, nothing to do. ")
        }
        return Ok(());
    }
    if !c.silent {
        println!("Processing {} files... ", files.len());
        if !c.in_band {
            println!("Spawning {} workers...", c.cpus.min(files.len()))
        }
        if c.dry {
            println!("Running in dry mode, no files will be written! ")
        }
    }
    let queue = Arc::new(Mutex::new(files));
    let results = Arc::new(Mutex::new(Vec::<(PathBuf, String, String, String)>::new()));
    let workers = if c.in_band {
        1
    } else {
        c.cpus.min(queue.lock().unwrap().len()).max(1)
    };
    let mut hs = Vec::new();
    for _ in 0..workers {
        let q = queue.clone();
        let r = results.clone();
        let root = c.package_root.clone();
        let parser = c.parser.clone();
        let opts = c.options.clone();
        let dry = c.dry;
        let tr = tr.clone();
        hs.push(thread::spawn(move || loop {
            let f = { q.lock().unwrap().pop() };
            let Some(f) = f else { break };
            let cc = Config {
                transform: String::new(),
                parser: parser.clone(),
                extensions: Vec::new(),
                ignores: Vec::new(),
                cpus: 1,
                in_band: true,
                silent: true,
                verbose: 0,
                dry,
                print: false,
                fail_on_error: false,
                package_root: root.clone(),
                options: opts.clone(),
            };
            let (o, s, e) = one(&cc, &tr, &f);
            r.lock().unwrap().push((f, o, s, e));
        }))
    }
    for h in hs {
        h.join().map_err(|_| "worker panic")?
    }
    let mut rs = results.lock().unwrap().clone();
    rs.sort_by(|a, b| a.0.cmp(&b.0));
    let mut st = Stats::default();
    let mut had = false;
    let start = Instant::now();
    for (f, status, out, msg) in rs {
        match status.as_str() {
            "ok" => {
                st.ok += 1;
                let original = fs::read(&f)?;
                if out.as_bytes() != original.as_slice() {
                    if !c.dry {
                        fs::write(&f, out.as_bytes())?
                    }
                    if c.print {
                        println!("{}", out);
                        if !msg.is_empty() {
                            println!("{}", msg);
                        }
                    }
                    if c.verbose > 0 && !c.silent {
                        println!("OK {}", f.display())
                    }
                } else {
                    st.nochange += 1;
                    if c.verbose > 0 && !c.silent {
                        println!("NOC {}", f.display())
                    }
                }
            }
            "nochange" => {
                st.nochange += 1;
                if c.verbose > 0 && !c.silent {
                    println!("NOC {}", f.display())
                }
            }
            "skip" => {
                st.skip += 1;
                if c.verbose > 0 && !c.silent {
                    println!("SKIP {}", f.display())
                }
            }
            _ => {
                st.error += 1;
                had = true;
                if !c.silent {
                    println!("ERR {} {}", f.display(), msg)
                }
            }
        }
    }
    if !c.silent {
        println!(
            "Results: {} ok, {} unmodified, {} skipped, {} errors",
            st.ok, st.nochange, st.skip, st.error
        );
        if c.print {
            println!("Time elapsed: {:.3}seconds", start.elapsed().as_secs_f64())
        }
    }
    if had && c.fail_on_error {
        std::process::exit(1)
    }
    Ok(())
}
