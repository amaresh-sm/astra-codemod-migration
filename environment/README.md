# Candidate Generation and Verification

The candidate runtime and verifier use separate containers, filesystems, and mounts.

## Candidate generation

Build all three isolated images from the repository root with:

```bash
npm run build:images
```

Use `--candidate-tag`, `--runtime-tag`, and `--verifier-tag` after the command when a task needs its own image tags.

Mount only the prepared candidate workspace:
```text
/workspace/            (writable candidate workspace)
```

The runner starts a long-lived generation container, copies only the candidate-facing instruction
and public files into `/workspace`, then executes the provider CLI with `docker exec`. Logs and
metadata stay in the host run directory. The image must not receive `verifier/`, hidden tests,
mutants, calibration data, or scoring rules.

For a Codex login, pass the host credentials explicitly with `--auth-file` and, when the session
uses managed policies, its matching `--cloud-config-file`. For Claude Code, pass an
`ANTHROPIC_API_KEY` through the private env file or explicitly supply
`--claude-credentials-file`; the API key is preferred because copied OAuth credentials can expire.
The image installs the Debian system CA bundle so provider CLIs can establish TLS connections. If a
local network adds its own trusted root, pass that PEM with `--ca-cert`; never copy a private key
or the whole host credential directory.

## Verification

The shared runner starts two containers:

```text
candidate runtime:  /workspace/       (candidate only)
verifier:           /input/candidate/ (read-only candidate snapshot)
                    /input/verifier/  (read-only private tests and reference material)
                    /output/          (writable reports only)
```

Candidate manifest build, reset, and start commands run only in the candidate runtime. The verifier
joins that runtime's network namespace, so an app bound to `127.0.0.1` remains reachable without
making it reachable from the host. The verifier can therefore perform black-box HTTP and browser
checks while the candidate can never read the private verifier filesystem.

The verifier never executes candidate-provided commands. Task authors can extend either runtime
image for language runtimes, databases, browsers, or service dependencies.

The runner must keep the hidden directory and all verifier data out of any candidate application
subprocess or child container. The verifier image owns the private mount; the candidate runtime
receives only the candidate workspace.

The verifier receives separate read-only candidate and private-verifier mounts and writes reports
to the host run directory. Both containers are removed after each run. A production runner should
add CPU/memory limits, a temporary filesystem, and an explicit egress policy.
