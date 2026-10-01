# Development validation — 1 October 2026

The standalone Orange Verify wrapper passed the local validation recorded
below. This initial record predates its hosted CI run. The wrapper source is
being uploaded to `chasebryan/orange-verify`; no release or Marketplace listing
has been created.

| Check | Result |
| --- | --- |
| Unit and real-compiler regression tests | 40 passed; zero failures or skips |
| Pinned source acquisition | Exact `4a6390645d91627490214e42319ffc86fc1a83ab`, fetched through local Git transport |
| Fresh compiler build through the wrapper installer | Passed with Rust 1.96.1, release mode, locked and offline Cargo |
| Native crypto assertions through the gate | 15 passed across RFC 8439, RC6, and SHA-3 fixtures |
| Deliberately broken assertion | Correctly fails; file-level SARIF result and JSON report retained |
| Zero-test entry point in test mode | Correctly fails |
| Source-only entry point in check mode | Correctly passes as source validation |
| Empty and unmatched selections | Correctly fail |
| Mutable compiler reference and unavailable proof mode | Correctly fail |
| Compiler crash, malformed report, output cap, and timeout | Correctly fail |
| Evaluation-budget exhaustion | Correctly fails and records incomplete execution |
| Shell metacharacters and leading dash in a filename | Treated as a literal path; no shell execution |
| Action metadata, YAML, embedded Python, Python syntax, and text formatting | Passed local structural checks |

The complete unit/native log is in `validation/tests.txt`. The crypto run and
the intentionally failing assertion have JSON and SARIF samples under
`validation/`. Sample runs explicitly supplied the locally built compiler;
their JSON therefore reports caller-supplied provenance instead of borrowing
the default source commit's identity. `validation/build.json` separately records
the fresh source build used for those runs.

SARIF structure and locations have unit coverage and local JSON checks. No
full external SARIF-schema validator or actual GitHub code-scanning upload
was run. The hosted CI workflow includes assertions that composite outputs
and reports survive failed invocations; that integration remains to be run.

The local Git acquisition test exercises the same installer path with an
exact source commit and a fresh checkout. It does not establish the runner's
future network access to GitHub or Rust distribution servers. Both local
compiler builds took place in the same execution environment, so they are
not separately provisioned owner rebuilds or independent reproducibility
evidence.

These results concern implemented source validation and native assertions.
Formal proof checking, cryptographic security, refinement, constant-time
behavior, production readiness, and independent review are not established.
Licensing and publication decisions remain with the owner.
