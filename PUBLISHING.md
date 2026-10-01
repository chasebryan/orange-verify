# Publishing Orange Verify

The Action repository is `chasebryan/orange-verify`. Keep this
wrapper separate from `chasebryan/orange` so the Action has its own versions,
tests, and Marketplace description. The package root contains one `action.yml`;
copy the contents of this folder to the repository root.

GitHub's current requirements are a public repository, one root metadata file,
and a unique Action name. Marketplace publication is selected when publishing
the repository release. The owner must have accepted the Marketplace Developer
Agreement and have two-factor authentication enabled.

Source: [GitHub's publishing guide](https://docs.github.com/en/actions/how-tos/create-and-publish-actions/publish-in-github-marketplace).

## Before a public release

Orange's [release policy](https://github.com/chasebryan/orange/blob/4a6390645d91627490214e42319ffc86fc1a83ab/RELEASE_POLICY.md)
states that "unresolved license and working-name decisions prohibit crate,
package-registry, and binary distribution" until the release boundary is
recorded. Its [README](https://github.com/chasebryan/orange/blob/4a6390645d91627490214e42319ffc86fc1a83ab/README.md)
also says no rights to use, copy, or redistribute have been granted.

Record the owner's decision for the wrapper's license and the rights its users
need to fetch and build the pinned Orange source. Record whether this wrapper
release is within an authorized source-preview boundary. If it is, satisfy
the applicable release gates rather than treating green Action CI as release
authorization. The package includes no toolchain binary and chooses no license.

The local validation report is development evidence. Hosted Action CI and
any policy-required separately provisioned rebuilds are still outstanding.
The owner controls both development and publication; do not describe that
as independent review.

## Proposed release

| Field | Proposed value |
| --- | --- |
| Repository | `chasebryan/orange-verify` |
| Action name | `Orange Verify`; confirm uniqueness in GitHub's release form |
| Tag | `v0.1.0`, immutable and annotated |
| Title | `Orange Verify v0.1.0 — native assertion CI preview` |
| Primary category | Continuous integration |
| Secondary category | Code quality |
| Status | Pre-release; solo-produced |
| Toolchain source | `chasebryan/orange@4a6390645d91627490214e42319ffc86fc1a83ab` |
| Rust | `1.96.1` |
| Supported runner | Linux; Ubuntu 24.04 intended first target |
| Claims | Source validation and native assertions |
| Formal proof checking | Unavailable |
| Compatibility/support dates | Owner must record before publication |

Upload the reviewed source to the separate repository and let `Action CI`
run. Check that the passing invocation passes, the broken assertion and empty
entry point fail, and reports survive those failures. Review the resulting
immutable Action commit before tagging it.

When the release boundary is authorized and the required checks pass, open
`action.yml` in GitHub, choose **Draft a release**, and select **Publish this
Action to the GitHub Marketplace**. Resolve any metadata or name collision
reported by GitHub, select the categories, and publish the pre-release.
Use the full reviewed Action commit SHA in consumer workflows.

Rollback means removing the Marketplace selection for the affected release,
withdrawing the version, and publishing a correction under a new tag.
Do not reuse or move the old tag. Preserve the original source and run records.

## Draft release description

Orange Verify runs Orange source validation and native assertions in GitHub
Actions. A failed assertion or compiler diagnostic fails the workflow. Reports
include GitHub annotations, SARIF 2.1.0, and JSON with compiler provenance.

This first wrapper preview builds the pinned S3r compiler from source on Linux.
It rejects unmatched paths, empty assertion suites, mutable compiler refs,
inconsistent compiler output, and resource-limit failures. An optional
caller-supplied compiler can be reused in the same job with explicit provenance.

Formal proof checking is not implemented. Passing assertions establish only
the tested cases; this release makes no cryptographic security, refinement,
constant-time, or production assurance claim. This is solo-produced development
work and has not received independent review.
