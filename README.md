# Orange Verify

[![Action CI](https://github.com/chasebryan/orange-verify/actions/workflows/ci.yml/badge.svg)](https://github.com/chasebryan/orange-verify/actions/workflows/ci.yml)

**Run your Orange assertions in CI.**

Orange Verify builds a pinned Orange compiler, validates your selected entry
points, and runs their native assertions. A broken assertion stops the build.
Compilation errors appear as GitHub annotations, with a SARIF report for code
scanning and a JSON report for the complete run.

This is a development preview of a separate GitHub Action wrapper. Orange's
proof checker is not implemented. Passing assertions demonstrate the cases
you tested; they do not prove an algorithm secure or establish refinement,
constant-time behavior, or production readiness. `mode: proof` is rejected.

## Use it

Check out the repository you want to test before calling the Action. Select
test entry points explicitly, one path or glob per line. Imported modules are
loaded by Orange; a library without its own assertions belongs behind a test
entry point or in a separate `mode: check` invocation.

The wrapper source lives in `chasebryan/orange-verify`. No Marketplace release
or version tag exists yet. The example pins the first source snapshot whose
hosted Action CI passed, including all 40 regression tests and the expected
failure cases. Review and pin a new full commit SHA when upgrading.

```yaml
name: Orange assertions
on: [push, pull_request]

permissions:
  contents: read

jobs:
  orange:
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6
        with:
          persist-credentials: false
      - name: Run Orange assertions
        id: orange
        uses: chasebryan/orange-verify@7f736f30d2546abef85bb56d6c08a20fe4862625
        with:
          paths: |
            crypto/tests.or
            crypto/*-tests.or
```

Every selection must match a regular `.or` file. The default `test` mode
requires at least one native assertion in **every** selected entry point.
Missing files, empty runs, compiler failures, inconsistent reports, and
resource-limit failures cannot produce a pass. A directory selects its `.or`
files recursively; avoid selecting an entire compiler fixture tree containing
deliberately invalid files or libraries without assertions.

For source validation without executing assertions, set `mode: check`.
This mode reports `source-validation`, with zero executed tests.

## SARIF and reports

The Action writes reports before returning a failing exit status. To upload
SARIF, grant `security-events: write` to the caller's job and append this step
after the Action:

```yaml
- name: Upload Orange findings
  if: ${{ always() && steps.orange.outputs.sarif-file != '' }}
  uses: github/codeql-action/upload-sarif@2892aa5e19bbd11bc0cff5427e3b750a04d9e3c2 # v4
  with:
    sarif_file: ${{ steps.orange.outputs.sarif-file }}
    category: orange-assertions
```

The original gate failure remains a job failure. SARIF upload is optional;
the wrapper uses no token and makes no GitHub API calls. Code scanning
availability and fork pull-request upload permissions depend on GitHub and
your repository settings.

Compiler diagnostics preserve their source location, including diagnostics in
imported modules. The current native assertion report provides a title but no
source span, so assertion failures receive an entry-point file location.
No line number is invented.

The JSON report records the compiler's source commit when built by the Action,
Rust version, compiler binary digest, selected source digests, commands,
stdout, stderr, executed test counts, and findings. It is a run record, not
an Orange proof bundle. A caller-supplied compiler is labeled as such and
does not inherit the default source commit's provenance.

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `paths` | Required | Entry points, directories, or globs, one per line |
| `mode` | `test` | `test` for native assertions; `check` for source validation |
| `orange-ref` | `4a6390645d91627490214e42319ffc86fc1a83ab` | Full lowercase source commit SHA; branches and tags are rejected |
| `orangec` | Empty | Absolute executable path; skips the source build and records caller-supplied provenance |
| `steps` | `1048576` | Evaluation budget per entry point; maximum `1073741824` |
| `timeout-seconds` | `120` | Wall-clock limit per entry point; maximum `3600` |

## Outputs

| Output | Meaning |
| --- | --- |
| `status` | `passed` or `failed` |
| `files` | Selected entry-point count |
| `tests` | Executed native assertion count reported by the compiler |
| `failed-tests` | Failing assertion count reported by the compiler |
| `sarif-file` | Absolute path to the SARIF 2.1.0 report |
| `report-file` | Absolute path to the JSON run report |
| `orangec` | Compiler executable for reuse in the same job |

## Runner requirements

This preview supports Linux and requires Python 3.11 or newer. The default
source build also requires Git, rustup, Cargo, a C linker, and network access
to fetch the pinned Orange source and Rust 1.96.1 if it is not installed.
GitHub's Ubuntu 24.04 hosted runner is the intended first target.

After source and toolchain acquisition, Cargo builds with `--locked --offline`.
The current Orange compiler has no third-party dependencies. The wrapper
itself uses only Python's standard library and has no nested Actions.
Updating Orange to a different Rust version requires a wrapper update.
No toolchain binary is bundled or distributed in this source package.

Select at most 1,024 entry points. The wrapper rejects source entry points
larger than 16 MiB, paths outside the workspace, symbolic-link traversal,
control-character filenames, and `.git` metadata. It retains at most 2 MiB
per compiler output stream and fails if that limit is exceeded. Use the job's
`timeout-minutes` to limit the complete scan; `timeout-seconds` applies to
each entry point. Reports are retained under the runner's temporary directory
until job cleanup.

## Test it locally

Build the pinned Orange compiler in an owner-authorized checkout, then run:

```sh
ORANGEC=/absolute/path/to/orangec python3 -m unittest discover -s tests -v

GITHUB_WORKSPACE="$PWD" \
ORANGE_INPUT_PATHS=examples/rfc8439.or \
ORANGE_INPUT_ORANGEC=/absolute/path/to/orangec \
python3 -I scripts/run.py
```

The unit suite covers selection, diagnostics, SARIF, command escaping, malformed
reports, crashes, and timeouts. Native tests cover passing assertions, a
deliberately broken assertion, zero-test rejection, source diagnostics, budget
exhaustion, and reports retained after failure. Native tests are explicitly
skipped if `ORANGEC` is not set; the bundled CI workflow requires a real
compiler and tests the installed Action as a local composite Action.

## Publication status

The wrapper source is hosted in the separate
[orange-verify repository](https://github.com/chasebryan/orange-verify).
Hosted [Action CI](https://github.com/chasebryan/orange-verify/actions/runs/36867834282)
passed the source build, 40 regression tests, expected failure cases, and report
retention checks. It has not been released or registered in GitHub Marketplace.
The owner release decision and licensing scope still need to be established.
Orange currently has no outbound license and
no authorized product release. This package makes neither decision.
Owner development and testing can proceed; public use needs the rights
and release boundary recorded in Orange's policy.

See [PUBLISHING.md](PUBLISHING.md) for the proposed repository and release.
