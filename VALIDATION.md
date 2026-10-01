# Development validation — 1 October 2026

The standalone Orange Verify wrapper passed both local and hosted validation.
Its source is in `chasebryan/orange-verify`; no release or Marketplace listing
has been created. The local record below precedes the hosted run recorded
at the end of this document.

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
was run. The hosted CI workflow checked that composite outputs and reports
survive failed invocations; that integration passed.

The local Git acquisition test exercises the same installer path with an
exact source commit and a fresh checkout. It does not establish the runner's
future network access to GitHub or Rust distribution servers. The hosted run
then fetched the immutable source and built it on a GitHub runner. The two
local compiler builds took place in the same execution environment. No binary
comparison across separately provisioned environments was performed, and
none of these owner-controlled runs is independent reproducibility evidence.

These results concern implemented source validation and native assertions.
Formal proof checking, cryptographic security, refinement, constant-time
behavior, production readiness, and independent review are not established.
Licensing and publication decisions remain with the owner.

## Hosted Action CI

[Run 36867834282](https://github.com/chasebryan/orange-verify/actions/runs/36867834282)
passed for wrapper commit `7f736f30d2546abef85bb56d6c08a20fe4862625` on
Ubuntu 24.04. The log confirms all 40 regression tests passed with the real
compiler. The primary invocation passed three native assertions across two
entry points. The deliberately broken assertion and zero-test invocation
failed as expected, and the workflow's outcome/report assertions passed.

Six JSON/SARIF files were retained in
[orange-verify-ci-reports](https://github.com/chasebryan/orange-verify/actions/runs/36867834282/artifacts/11164970919),
artifact ID `11164970919`, SHA-256
`9a522a20d7ed4f177db3046c368e0baefcf7e09e3c65eb935da150bafe438263`.
The machine-readable record is `validation/hosted.json`.
