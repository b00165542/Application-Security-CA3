# Static Analysis (Bandit + Semgrep) Runbook

This runbook covers how to run the static analysis checks locally, on your own machine, before pushing, and how to handle what they find.

| Item | Bandit | Semgrep |
| --- | --- | --- |
| What it checks | Python code | Python, Jinja/HTML templates, workflow files (OWASP Top 10 rules) |
| Pinned version | `1.9.4` | `1.183.0` |
| CI job | `Bandit` in [`.github/workflows/sast.yml`](../.github/workflows/sast.yml) | `Semgrep` in the same workflow |
| Network use | None (fully offline) | Downloads the public rule packs only. No code is uploaded |

Both CI jobs fail on **any** finding. If both commands in [section 3](#3-run-the-checks) pass locally, CI should pass too.

For secret scanning, see the [Gitleaks runbook](gitleaks-runbook.md).

---

## 1. Why use a separate environment

Install the scanners in their **own virtual environment**, outside the project:

- They are development tools, not app dependencies, so they don't belong in `requirements.txt` or the app's `.venv`.
- Semgrep has many dependencies that could clash with the app's pinned packages.
- Keeping the environment outside the repo means it is never scanned, committed or picked up by `.gitignore` rules.

The commands below use `%USERPROFILE%\.venvs\sast`. Admin rights are **not** needed.

---

## 2. Install (one-time)

PowerShell, from any folder:

```powershell
python -m venv "$env:USERPROFILE\.venvs\sast"
& "$env:USERPROFILE\.venvs\sast\Scripts\python.exe" -m pip install "bandit[sarif]==1.9.4" "semgrep==1.183.0"
```

Use the same versions as CI, so your local results match. Python 3.10 or newer is required for Semgrep.

Activate the environment in each new terminal before running the checks:

```powershell
& "$env:USERPROFILE\.venvs\sast\Scripts\Activate.ps1"
bandit --version     # bandit 1.9.4
semgrep --version    # 1.183.0
```

If PowerShell refuses to run `Activate.ps1`, see [Troubleshooting](#8-troubleshooting).

---

## 3. Run the checks

Run from the **repository root**, with the `sast` environment activated.

### Bandit

```powershell
bandit -r . -x ./.venv
```

- `-r .` scans the project folder recursively.
- `-x ./.venv` skips the app's virtual environment (installed libraries, not your code).
- It exits with `1` if it finds any issue, and `0` if it finds none.

### Semgrep

```powershell
$env:PYTHONUTF8 = "1"                  # avoids Unicode errors in the Windows console
$env:SEMGREP_SEND_METRICS = "off"
$env:SEMGREP_ENABLE_VERSION_CHECK = "0"
semgrep scan --config p/python --config p/owasp-top-ten --metrics=off --error
```

- `--error` makes it exit with `1` on findings, as in CI.
- **Semgrep only scans files tracked by git.** A new file isn't scanned until you `git add` it, but it doesn't need to be committed.
- `PartialParsing` / `Syntax error ... was unexpected` messages for files in `templates/` are **not findings**. They mean the HTML parser didn't understand Jinja syntax such as `{% block %}` and skipped those lines. The scan still completes.

### All checks in one go (including Gitleaks)

```powershell
& "$env:USERPROFILE\.venvs\sast\Scripts\Activate.ps1"
$env:PYTHONUTF8 = "1"; $env:SEMGREP_SEND_METRICS = "off"; $env:SEMGREP_ENABLE_VERSION_CHECK = "0"

bandit -r . -x ./.venv -q;                                                   $bandit  = $LASTEXITCODE
semgrep scan --config p/python --config p/owasp-top-ten --metrics=off --error -q; $semgrep = $LASTEXITCODE
gitleaks git . --redact --no-banner;                                         $leaks   = $LASTEXITCODE

"Bandit: $bandit   Semgrep: $semgrep   Gitleaks: $leaks   (0 = pass)"
```

---

## 4. Read the results

The outputs below are illustrative examples, not findings in this codebase.

### Bandit

```
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   Location: ./routers/products.py:42:11
```

- **Test ID** (`B608`): look it up in the [Bandit docs](https://bandit.readthedocs.io/en/latest/plugins/index.html) for an explanation and fix.
- **Severity:** how bad it would be if it is a real issue.
- **Confidence:** how sure Bandit is that it is a real issue. Low confidence means it's more likely a false positive, but you still need to check it.

### Semgrep

```
.github/workflows/secret-scan.yml
   ❯❱ yaml.github-actions.security.github-actions-mutable-action-tag
        Using a mutable tag for an action ...
         20┆ uses: actions/checkout@v4
```

- The **rule ID** (`yaml.github-actions...`) is what you need to silence a false positive.
- Each finding includes a short explanation, and often a link with more detail.

To get a report file like the one CI uploads, add `-f sarif -o bandit.sarif` to the Bandit command, or `--sarif-output=semgrep.sarif` to the Semgrep one. SARIF files open in VS Code with the *SARIF Viewer* extension. Don't commit them.

---

## 5. Decide: real issue or false positive?

| Ask | If yes |
| --- | --- |
| Can a user, request, file or environment value reach this line? | Treat as **real**. Fix it ([section 6](#6-fix-a-real-issue)) |
| Is the input fully under our control (a constant, a validated enum, a parameterised query)? | Probably a **false positive** ([section 7](#7-mark-a-false-positive)) |
| Not sure? | Treat it as real, or ask for a review |

The pull request description or a code comment should say **why** a finding was dismissed.

---

## 6. Fix a real issue

Common findings and fixes for this codebase:

| Finding | Fix |
| --- | --- |
| SQL built with `%`, `+` or f-strings (`B608`, `sqlalchemy-execute-raw-query`) | Use SQLAlchemy `select()` or bound parameters: `text("... WHERE id = :id")` with `{"id": value}` |
| `subprocess` with `shell=True` (`B602`) | Pass a list of arguments without `shell=True` |
| `eval` / `exec` (`B307`, `B102`) | Use `ast.literal_eval` for data, or remove it |
| `pickle` / `yaml.load` (`B301`, `B506`) | Use JSON, or `yaml.safe_load` |
| Weak hash for passwords (`B303`, `B324`) | Use the existing `passlib` bcrypt helpers in `auth.py` |
| Hard-coded password (`B105`–`B107`) | Read it from the environment (see `.env.example`) |
| Jinja `autoescape=False` or `\|safe` on user input | Keep autoescaping on; don't mark user input as safe |
| Mutable action tag in a workflow | Pin to a full commit SHA with the version in a comment, e.g. `actions/checkout@<sha> # v4.3.1` |

After fixing, re-run the check to confirm the finding is gone.

---

## 7. Mark a false positive

Always use the **narrowest** suppression, always name the specific rule, and add a reason.

### Bandit: `# nosec`

```python
query = text(f"SELECT * FROM {TABLE_NAME}")  # nosec B608 - TABLE_NAME is a module constant
```

- Always include the test ID (`B608`). A bare `# nosec` hides **every** check on that line.
- Bandit counts suppressed lines in its report (`Total lines skipped (#nosec)`), so they stay visible in review.

### Semgrep: `# nosemgrep`

```python
query = text(f"SELECT * FROM {TABLE_NAME}")  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query
```

In YAML or HTML, use that file's comment syntax, for example `# nosemgrep: <rule-id>` in YAML.

### Skipping files

- **Bandit:** add paths to `-x`, e.g. `-x ./.venv,./tests`. Change the same option in `sast.yml`.
- **Semgrep:** create a `.semgrepignore` file in the repo root (same syntax as `.gitignore`).

Skipping whole files hides every future issue in them. Prefer line-level suppressions, and get any file exclusion reviewed.

---

## 8. Troubleshooting

| Problem | Cause | Fix |
| --- | --- | --- |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | The PowerShell execution policy blocks scripts | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once (no admin needed), or call the tools directly: `& "$env:USERPROFILE\.venvs\sast\Scripts\bandit.exe" ...` |
| `bandit` / `semgrep` is not recognized | The `sast` environment isn't activated in this terminal | Run the `Activate.ps1` line from [section 2](#2-install-one-time) |
| `UnicodeEncodeError` from Semgrep | The Windows console isn't using UTF-8 | Set `$env:PYTHONUTF8 = "1"` before running |
| Semgrep finds nothing in a new file | It only scans files tracked by git | `git add` the file first |
| Semgrep fails to download rules | No internet, or a proxy is blocking `semgrep.dev` | Check your connection. Bandit still works offline |
| Bandit reports issues in `.venv` | The `-x` option is missing or the path is wrong | Run from the repo root with `-x ./.venv` |
| CI fails but local passes | Different versions, or new files Semgrep didn't see | Check `--version` against the pinned versions, and `git add` new files |
| Many `PartialParsing` messages for templates | Jinja syntax inside HTML | Expected. Not findings, and they don't fail the scan |

---

## 9. Upgrade the scanners

1. Pick a release from PyPI ([Bandit](https://pypi.org/project/bandit/#history), [Semgrep](https://pypi.org/project/semgrep/#history)). Avoid ones published in the last couple of weeks.
2. Update `BANDIT_VERSION` / `SEMGREP_VERSION` in [`.github/workflows/sast.yml`](../.github/workflows/sast.yml).
3. Update the versions in [section 2](#2-install-one-time) of this runbook and the table at the top.
4. Reinstall locally: `pip install "bandit[sarif]==X.Y.Z" "semgrep==X.Y.Z"` in the `sast` environment.
5. Run both checks. New versions often add rules, so fix or triage any new findings in the same pull request.

---

## 10. Known gaps

- **Bandit** only reads Python, one file at a time. It doesn't follow data between files, so it can't tell whether a value really comes from a user.
- **Semgrep** with these free rule packs is narrow: in testing it caught `shell=True` but **missed** SQL string formatting, `pickle.loads` and `eval`, which Bandit caught. That's why both run.
- Neither tool finds **logic flaws**: broken access control (e.g. a missing role check on an admin route), IDOR (viewing another user's order by changing the ID), business-logic bugs, or CSRF design issues. These need code review and testing.
- Neither checks **dependencies** for known vulnerabilities. That needs a separate tool such as `pip-audit`.

A clean scan means no known risky patterns were detected. It does not mean the code is secure.
