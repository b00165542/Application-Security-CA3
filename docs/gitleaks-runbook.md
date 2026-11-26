# Gitleaks Secret Scanning Runbook

This runbook covers how secret scanning works in this repository, how to run it locally, and what to do when it finds something.

For static code analysis (Bandit and Semgrep), see the [static analysis runbook](sast-runbook.md).

| Item | Value |
| --- | --- |
| Tool | [Gitleaks](https://github.com/gitleaks/gitleaks) (open source, MIT) |
| Pinned version | `8.28.0` |
| CI workflow | [`.github/workflows/secret-scan.yml`](../.github/workflows/secret-scan.yml) |
| Config | [`.gitleaks.toml`](../.gitleaks.toml) |
| Ignore list | `.gitleaksignore` (create it when needed) |

---

## 1. How it works

- Gitleaks scans files and git history for secrets: cloud keys, API tokens, private keys, JWTs and generic high-entropy strings.
- The scan runs **entirely on the CI runner**. No code is sent to an external scanning service, and no account, licence or API token is needed.
- The CI job downloads the official Gitleaks release binary and **checks it against a pinned SHA-256 checksum** before running it. If the checksum doesn't match, the job stops.
- The CI job fetches the full history (`fetch-depth: 0`), so **every commit** is scanned, not just the latest code.

### When it runs

| Trigger | When |
| --- | --- |
| `push` | Every push to any branch |
| `pull_request` | When a PR is opened and on every new commit to it |
| `workflow_dispatch` | Manually: **Actions** tab → **Secret scan** → **Run workflow** |

### Outcome

- **Green ✓**: no leaks found.
- **Red ✗**: at least one finding. Secret values are redacted in the job log. The full report is attached to the run as the `gitleaks-report` artifact (SARIF format).

> **Note:** A failed scan only blocks merges if branch protection requires it. See [section 7](#7-enforcement).

---

## 2. Install Gitleaks locally (Windows, no admin)

Gitleaks is a single `.exe`, so it doesn't need an installer or admin rights.

```powershell
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = 'Tls12'
$v   = "8.28.0"
$zip = "$env:TEMP\gitleaks.zip"
$tmp = "$env:TEMP\gitleaks-extract"
Invoke-WebRequest "https://github.com/gitleaks/gitleaks/releases/download/v$v/gitleaks_${v}_windows_x64.zip" -OutFile $zip
if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne "DA6458E8864AF553807DE1C46A7A8EAC0880BD6B99BA56288E87E86A45AF884F") { throw "Checksum mismatch - do not use this file" }
Expand-Archive $zip -DestinationPath $tmp -Force
New-Item -ItemType Directory -Force "$env:USERPROFILE\bin" | Out-Null
Copy-Item "$tmp\gitleaks.exe" "$env:USERPROFILE\bin\gitleaks.exe" -Force
```

Add the folder to your user PATH (one-time, no admin needed):

```powershell
$p = [Environment]::GetEnvironmentVariable("Path", "User")
if ($p -notlike "*$env:USERPROFILE\bin*") {
    [Environment]::SetEnvironmentVariable("Path", "$p;$env:USERPROFILE\bin", "User")
}
$env:Path += ";$env:USERPROFILE\bin"   # apply to the current terminal too
gitleaks version                       # should print 8.28.0
```

Restart VS Code fully so its integrated terminal picks up the new PATH.

**Alternative: Docker (no install)**

```powershell
docker run --rm -v "${PWD}:/repo" ghcr.io/gitleaks/gitleaks:v8.28.0 dir /repo -v --redact
```

**Other platforms:** download the matching archive from the [v8.28.0 release](https://github.com/gitleaks/gitleaks/releases/tag/v8.28.0) and verify it against `gitleaks_8.28.0_checksums.txt`.

---

## 3. Run a scan

Run from the repository root. `.gitleaks.toml` and `.gitleaksignore` are picked up automatically.

| Command | What it scans |
| --- | --- |
| `gitleaks git . -v --redact` | Every commit in history (**same as CI**) |
| `gitleaks dir . -v --redact` | Current files, including uncommitted changes |
| `gitleaks git . -v` | Same as the first, but shows secret values. Use it only to check a finding, and not while screen-sharing |

**Before pushing**, run both `git` and `dir` scans.

Expected clean output:

```
INF scanned ~108645 bytes (108.64 KB) in 45.3ms
INF no leaks found
```

Gitleaks exits with code `1` when it finds leaks, and `0` when it doesn't.

---

## 4. Triage a finding

Each finding looks like this:

```
Finding:     SECRET_KEY = "REDACTED"
RuleID:      generic-api-key
File:        main.py
Line:        30
Commit:      64c99e1...
Fingerprint: 64c99e1...:main.py:generic-api-key:30
```

To decide whether it's real:

1. **Is it an actual credential?** A real key, token, password or private key, even an expired or test one, counts as **real**. Go to [section 6](#6-handle-a-real-secret).
2. **Is it a placeholder, a dummy value, a hash, or test data that grants no access?** That's a **false positive**. Go to [section 5](#5-mark-a-false-positive).
3. **Not sure?** Treat it as real.

---

## 5. Mark a false positive

Use the narrowest option that works.

### a) `.gitleaksignore`: one specific finding (preferred)

Create `.gitleaksignore` in the repo root and add one fingerprint per line, with a comment explaining why:

```
# Dummy value used for timing-safe login checks, not a credential
64c99e1...:auth.py:generic-api-key:17
```

- Fingerprints from `git` scans include the commit hash, so they only match that commit. This is the right way to handle findings in old history.
- Fingerprints from `dir` scans have no commit hash (`file:rule:line`).
- Commit `.gitleaksignore` so CI uses it too.

### b) Inline comment: a line in current code

```python
EXAMPLE_TOKEN = "not-a-real-token"  # gitleaks:allow
```

This only covers commits that **contain** the comment. Older commits still have the line without it, so CI's history scan will still flag those. Use option (a) for them.

### c) Allowlist in `.gitleaks.toml`: a whole folder or pattern

```toml
[allowlist]
paths = [
  '''(^|/)\.venv/''',
  '''(^|/)__pycache__/''',
  '''\.db$''',
  '''(^|/)tests/fixtures/''',       # example: skip a folder
]
regexes = [
  '''dummy-password-for-timing''',  # example: skip a known harmless value
]
```

Keep allowlists narrow, because a broad pattern can hide real leaks. Every allowlist change should go through code review.

---

## 6. Handle a real secret

**Do not** add a real secret to `.gitleaksignore`. Treat it as compromised as soon as it has been committed, even if it was never pushed.

1. **Revoke or rotate the secret** with whoever issued it (cloud console, API provider, database). This is the step that actually removes the risk.
2. **Remove it from the code.** Load it from an environment variable or a `.env` file instead. `.env` is already in `.gitignore`.
3. **Commit the fix** and confirm the next CI run goes green. Until then the old commit is still flagged, so add its fingerprint to `.gitleaksignore` with a comment such as `# rotated on YYYY-MM-DD`.
4. **Rewrite history only if needed**, for example if the repo is public or the secret can't be rotated:
   ```powershell
   pip install git-filter-repo
   git filter-repo --replace-text replacements.txt   # lines like: literal-secret==>REMOVED
   git push --force-with-lease
   ```
   Tell your collaborators first, because everyone will need to re-clone.
5. **Record it:** what leaked, when, how long it was exposed, and when it was rotated.

---

## 7. Enforcement

To stop merges when the scan fails:

1. Go to GitHub → **Settings** → **Branches** → **Add branch protection rule** for `main`.
2. Turn on **Require status checks to pass before merging**.
3. Select the **Gitleaks** check.

Optional extra layers:

- **GitHub push protection** (Settings → Code security): blocks pushes that contain known secret formats before they reach GitHub. It's free for public repos.
- **Local pre-commit hook:** catches secrets before they are committed at all.

---

## 8. Upgrade Gitleaks

1. Pick a release from the [releases page](https://github.com/gitleaks/gitleaks/releases). Avoid ones published in the last couple of weeks.
2. Get its checksum file:
   ```powershell
   $v = "X.Y.Z"
   (Invoke-WebRequest "https://github.com/gitleaks/gitleaks/releases/download/v$v/gitleaks_${v}_checksums.txt").Content
   ```
3. Update `GITLEAKS_VERSION` and `GITLEAKS_SHA256` (using the `linux_x64.tar.gz` line) in `.github/workflows/secret-scan.yml`.
4. Update the version and Windows checksum (the `windows_x64.zip` line) in [section 2](#2-install-gitleaks-locally-windows-no-admin) of this runbook.
5. Run the scan locally with the new version, then open a PR. CI will confirm it works.

---

## 9. Troubleshooting

| Problem | Cause | Fix |
| --- | --- | --- |
| `gitleaks : The term 'gitleaks' is not recognized` | The install folder isn't on PATH | Run the PATH step in [section 2](#2-install-gitleaks-locally-windows-no-admin), or call `& "$env:USERPROFILE\bin\gitleaks.exe"` directly |
| Works in a new terminal but not in VS Code | VS Code keeps the PATH it started with | Fully restart VS Code |
| `choco install` fails with `Access to the path ... is denied` / lock file error | Chocolatey needs an admin shell | Use the no-admin install in section 2. Or open an admin shell, delete the stale lock file named in the error, and retry |
| Docker `git` scan fails with `dubious ownership` | Windows file ownership seen from inside the container | Use `dir` mode in Docker, or the native binary for history scans |
| CI fails at `sha256sum -c` | The download doesn't match the pinned checksum | **Don't bypass it.** Check the version/checksum pair. If they're correct, treat the download as untrusted and investigate |
| CI finds something the local scan didn't | You ran `dir` locally, but CI runs `git` | Run `gitleaks git . -v --redact` locally |
| Scan is slow or flags library files | A folder that should be skipped is being scanned | Add it to `paths` in `.gitleaks.toml` |

---

## 10. Known gaps

Gitleaks detects things that *look like* secrets. It won't catch:

- **Weak hard-coded passwords**, such as `password = "admin12345"`. Gitleaks treats them as ordinary strings, so they have to be found by code review.
- Secrets in formats it has no rule for, or that are obfuscated or split across lines.
- Secrets that never enter git (shell history, logs, screenshots).

A clean scan means no detectable secrets. It does not mean there are no secrets.
