"""An Orange validation/test CI gate. All reported claims are pre-alpha tests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

SOURCE_REPOSITORY = "https://github.com/chasebryan/orange.git"
DEFAULT_REF = "4a6390645d91627490214e42319ffc86fc1a83ab"
RUST_VERSION = "1.96.1"
ACTION_VERSION = "0.1.0-dev"
MAX_FILES = 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_LOG_BYTES = 2 * 1024 * 1024
DIAGNOSTIC = re.compile(r"^(error|warning)\[(ORC\d{4})\]: (.+)$", re.MULTILINE)
LOCATION = re.compile(r"^ --> (.+):(\d+):(\d+)$", re.MULTILINE)
TEST_LINE = re.compile(r'^test "([^"\\\r\n]*)" \.\.\. (ok|FAILED)$', re.MULTILINE)
TEST_TOTAL = re.compile(r"^(\d+) tests?: (\d+) passed, (\d+) failed$", re.MULTILINE)


class GateError(Exception):
    """A configuration or execution failure that must never produce a pass."""


def escape_command(value: str, *, property_value: bool = False) -> str:
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if property_value else value


def console_log(text: str) -> None:
    # A compiler message or file name cannot become a runner command.
    for line in text.splitlines():
        print("orangec | " + line)


def bounded_integer(text: str, label: str, maximum: int) -> int:
    if not re.fullmatch(r"[0-9]{1,10}", text) or not 1 <= int(text) <= maximum:
        raise GateError(f"{label} must be an integer from 1 to {maximum}")
    return int(text)


def check_relative(path: Path, workspace: Path) -> Path:
    try:
        relative = path.relative_to(workspace)
        resolved = path.resolve(strict=True)
        resolved.relative_to(workspace)
        str(relative).encode("utf-8")
    except (OSError, ValueError, UnicodeError) as error:
        raise GateError("selected paths must be UTF-8 files inside the workspace") from error
    if ".git" in relative.parts or any(ord(c) < 32 or ord(c) == 127 for c in str(relative)):
        raise GateError("selected paths cannot include .git or control characters")
    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise GateError("selected paths cannot traverse symbolic links")
    return relative


def select_files(workspace: Path, selections: str) -> list[Path]:
    lines = [line.strip() for line in selections.splitlines() if line.strip()]
    if not lines:
        raise GateError("paths is required; select Orange entry points explicitly")
    selected: set[Path] = set()
    for selection in lines:
        pattern = Path(selection)
        if pattern.is_absolute() or ".." in pattern.parts:
            raise GateError("paths must be relative and cannot contain '..'")
        found: set[Path] = set()
        try:
            literal = workspace / pattern
            matches = [literal] if literal.exists() else workspace.glob(selection)
            for match in matches:
                if ".git" in match.relative_to(workspace).parts:
                    continue
                check_relative(match, workspace)
                candidates = match.rglob("*.or") if match.is_dir() else [match]
                for candidate in candidates:
                    if ".git" in candidate.relative_to(workspace).parts:
                        continue
                    relative = check_relative(candidate, workspace)
                    if candidate.suffix != ".or" or not candidate.is_file():
                        continue
                    if candidate.stat().st_size > MAX_SOURCE_BYTES:
                        raise GateError("an entry point exceeds Orange's 16 MiB source limit")
                    found.add(relative)
                    if len(found | selected) > MAX_FILES:
                        raise GateError(f"select at most {MAX_FILES} entry points")
        except (OSError, ValueError) as error:
            raise GateError("could not resolve the paths selection") from error
        if not found:
            raise GateError(f"selection matched no regular .or files: {selection!r}")
        selected.update(found)
    return sorted(selected, key=lambda path: path.as_posix())


def command(args: list[str], cwd: Path, timeout: int = 600) -> str:
    try:
        completed = subprocess.run(
            args, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GateError(f"could not complete {Path(args[0]).name}") from error
    console_log(completed.stdout)
    console_log(completed.stderr)
    if completed.returncode:
        raise GateError(f"{Path(args[0]).name} failed with exit status {completed.returncode}")
    return completed.stdout.strip()


def install_compiler(ref: str, destination: Path, repository: str = SOURCE_REPOSITORY) -> Path:
    """Build a pinned source checkout; the repository argument supports offline integration tests."""
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise GateError("orange-ref must be a full, lowercase, 40-character commit SHA")
    for executable in ("git", "rustup", "cargo"):
        if shutil.which(executable) is None:
            raise GateError(f"{executable} is required on the runner")
    source = destination / "source"
    source.mkdir()
    command(["git", "init", "--quiet", str(source)], destination)
    command(["git", "fetch", "--quiet", "--depth=1", "--", repository, ref], source)
    command(["git", "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", "FETCH_HEAD"], source)
    if command(["git", "rev-parse", "HEAD"], source) != ref:
        raise GateError("the fetched source does not match orange-ref")
    # This wrapper admits one Rust version; a newer compiler needs a wrapper update.
    import tomllib
    toolchain = tomllib.loads((source / "rust-toolchain.toml").read_text(encoding="utf-8"))
    if toolchain.get("toolchain", {}).get("channel") != RUST_VERSION:
        raise GateError(f"this wrapper requires Orange's pinned Rust {RUST_VERSION}")
    available = subprocess.run(
        ["rustup", "run", RUST_VERSION, "rustc", "--version"], cwd=destination,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=30, check=False,
    )
    if available.returncode:
        command(["rustup", "toolchain", "install", RUST_VERSION, "--profile", "minimal", "--no-self-update"], destination)
    command([
        "cargo", f"+{RUST_VERSION}", "build", "--locked", "--offline", "--release",
        "--manifest-path", str(source / "compiler/Cargo.toml"), "-p", "orangec",
        "--target-dir", str(destination / "target"),
    ], source)
    return destination / "target/release/orangec"


def finding(code: str, message: str, path: Path | None = None,
            line: int | None = None, column: int | None = None, level: str = "error") -> dict:
    result = {"ruleId": code, "level": level, "message": {"text": message}}
    if path is not None:
        physical = {"artifactLocation": {"uri": quote(path.as_posix(), safe="/"), "uriBaseId": "%SRCROOT%"}}
        if line is not None and column is not None and line > 0 and column > 0:
            physical["region"] = {"startLine": line, "startColumn": column}
        result["locations"] = [{"physicalLocation": physical}]
    return result


def decode_source_name(name: str) -> str:
    """Decode Rust char::escape_default, the pinned CLI's filename encoding."""
    tokens = re.compile(r"\\(?:u\{([0-9a-f]+)\}|([\\'\"nrt0]))")
    escapes = {"\\": "\\", "'": "'", '"': '"', "n": "\n", "r": "\r", "t": "\t", "0": "\0"}
    return tokens.sub(lambda match: chr(int(match[1], 16)) if match[1] else escapes[match[2]], name)


def compiler_findings(stderr: str, workspace: Path, entry: Path) -> list[dict]:
    matches = list(DIAGNOSTIC.finditer(stderr))
    results = []
    for index, match in enumerate(matches):
        block = stderr[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(stderr)]
        location = LOCATION.search(block)
        path, line, column = entry, None, None
        if location:
            try:
                decoded = Path(decode_source_name(location[1]))
                actual = decoded if decoded.is_absolute() else workspace / decoded
                path = check_relative(actual, workspace)
                line, column = int(location[2]), int(location[3])
            except (GateError, ValueError):
                # Keep an entry-level finding rather than inventing a source position.
                pass
        results.append(finding(match[2], match[3], path, line, column,
                               "warning" if match[1] == "warning" else "error"))
    return results


def run_entry(compiler: Path, workspace: Path, entry: Path, mode: str,
              steps: int, timeout: int) -> tuple[dict, list[dict], bool]:
    args = [str(compiler), mode]
    if mode == "test":
        args += ["--steps", str(steps)]
    args += ["--", entry.as_posix()]
    record = {"path": entry.as_posix(), "sha256": hashlib.sha256((workspace / entry).read_bytes()).hexdigest(),
              "command": args, "tests": 0, "failedTests": 0}
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen(args, cwd=workspace, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        except OSError as error:
            raise GateError("could not start orangec") from error
        timed_out = False
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait()
            exit_code = None
        stdout.seek(0)
        stderr.seek(0)
        out, err = stdout.read(MAX_LOG_BYTES + 1), stderr.read(MAX_LOG_BYTES + 1)
    oversized = len(out) > MAX_LOG_BYTES or len(err) > MAX_LOG_BYTES
    out_text = out[:MAX_LOG_BYTES].decode("utf-8", errors="replace")
    err_text = err[:MAX_LOG_BYTES].decode("utf-8", errors="replace")
    record.update({"exitCode": exit_code, "stdout": out_text, "stderr": err_text})
    print("Orange " + mode + " " + json.dumps(entry.as_posix()))
    console_log(out_text)
    console_log(err_text)
    results = compiler_findings(err_text, workspace, entry)
    execution_failed = (timed_out or oversized or exit_code not in (0, 1)
                        or any(result["ruleId"] in {"ORC0301", "ORC1006", "ORC1007"} for result in results))
    if timed_out:
        results.append(finding("ORANGE-ACTION-TIMEOUT", f"orangec exceeded {timeout} seconds", entry))
    elif oversized:
        results.append(finding("ORANGE-ACTION-OUTPUT", "compiler output exceeded the 2 MiB per-stream report limit", entry))
    elif exit_code not in (0, 1):
        results.append(finding("ORANGE-ACTION-EXECUTION", f"orangec exited with status {exit_code}", entry))
    elif mode == "test" and not results:
        totals = list(TEST_TOTAL.finditer(out_text))
        tests = list(TEST_LINE.finditer(out_text))
        valid = len(totals) == 1
        if valid:
            total, passed, failed = map(int, totals[0].groups())
            valid = (total == passed + failed == len(tests)
                     and failed == sum(test[2] == "FAILED" for test in tests)
                     and (exit_code == 0) == (failed == 0))
        if not valid:
            execution_failed = True
            results.append(finding("ORANGE-ACTION-REPORT", "compiler test output is missing or inconsistent", entry))
        else:
            record.update({"tests": total, "failedTests": failed})
            if total == 0:
                execution_failed = True
                results.append(finding("ORANGE-ACTION-NO-TESTS", "test mode requires at least one native assertion per entry point", entry))
            for test in tests:
                if test[2] == "FAILED":
                    # Native test reports contain titles but no trustworthy source spans.
                    results.append(finding("ORANGE-TEST-FAILED", f'Native assertion failed: {test[1]}', entry))
    if exit_code != 0 and not results:
        results.append(finding("ORANGE-CHECK-FAILED", "orangec failed without a recognized diagnostic", entry))
    if exit_code == 0 and any(result["level"] == "error" for result in results):
        execution_failed = True
    record["status"] = "failed" if results or execution_failed else "passed"
    return record, results, execution_failed


def write_reports(directory: Path, workspace: Path, report: dict, results: list[dict], execution_failed: bool) -> tuple[Path, Path]:
    rule_ids = sorted({result["ruleId"] for result in results})
    sarif = {
        "$schema": "https://schemastore.azurewebsites.net/schemas/json/sarif-2.1.0-rtm.5.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "Orange Verify", "version": ACTION_VERSION,
                      "informationUri": "https://github.com/chasebryan/orange",
                      "rules": [{"id": code, "shortDescription": {"text": code}} for code in rule_ids]}},
            "columnKind": "unicodeCodePoints",
            "originalUriBaseIds": {"%SRCROOT%": {"uri": workspace.as_uri() + "/"}},
            "invocations": [{"executionSuccessful": not execution_failed}],
            "results": results,
            "properties": {"claimKind": report["claimKind"], "formalProofChecking": False,
                           "compilerProvenance": report["compiler"]},
        }],
    }
    sarif_path, report_path = directory / "results.sarif", directory / "report.json"
    sarif_path.write_text(json.dumps(sarif, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return sarif_path, report_path


def main() -> int:
    directory = Path(tempfile.mkdtemp(prefix="orange-verify-", dir=os.environ.get("RUNNER_TEMP"))).resolve()
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", os.getcwd())).resolve()
    mode = os.environ.get("ORANGE_INPUT_MODE", "test")
    ref = os.environ.get("ORANGE_INPUT_REF", DEFAULT_REF)
    supplied = os.environ.get("ORANGE_INPUT_ORANGEC", "")
    report = {"actionVersion": ACTION_VERSION, "mode": mode, "status": "failed",
              "claimKind": {"test": "native-assertions", "check": "source-validation"}.get(mode, "unavailable"),
              "formalProofChecking": False, "compiler": {}, "files": [], "findings": [],
              "tests": 0, "failedTests": 0}
    results, execution_failed, compiler = [], False, None
    try:
        if os.environ.get("RUNNER_OS", "Linux") != "Linux" or sys.platform != "linux":
            raise GateError("this preview supports Linux runners only")
        if sys.version_info < (3, 11):
            raise GateError("Python 3.11 or newer is required")
        if mode not in ("check", "test"):
            raise GateError("mode must be check or test; formal proof checking is not implemented")
        if not re.fullmatch(r"[0-9a-f]{40}", ref):
            raise GateError("orange-ref must be a full, lowercase, 40-character commit SHA")
        steps = bounded_integer(os.environ.get("ORANGE_INPUT_STEPS", "1048576"), "steps", 1 << 30)
        timeout = bounded_integer(os.environ.get("ORANGE_INPUT_TIMEOUT", "120"), "timeout-seconds", 3600)
        entries = select_files(workspace, os.environ.get("ORANGE_INPUT_PATHS", ""))
        report.update({"selectedFiles": [entry.as_posix() for entry in entries], "steps": steps, "timeoutSeconds": timeout})
        if supplied:
            candidate = Path(supplied)
            if (not candidate.is_absolute() or not candidate.is_file() or not os.access(candidate, os.X_OK)
                    or any(ord(char) < 32 or ord(char) == 127 for char in supplied)):
                raise GateError("orangec must be an absolute path to an executable file")
            compiler = candidate
            report["compiler"] = {"provenance": "caller-supplied", "sourceCommit": None}
        else:
            report["compiler"] = {"provenance": "source-build", "repository": SOURCE_REPOSITORY,
                                  "sourceCommit": ref, "rustVersion": RUST_VERSION}
            compiler = install_compiler(ref, directory)
        report["compiler"].update({"version": command([str(compiler), "--version"], directory, 30),
                                   "binarySha256": hashlib.sha256(compiler.read_bytes()).hexdigest()})
        for entry in entries:
            record, findings, failed_execution = run_entry(compiler, workspace, entry, mode, steps, timeout)
            report["files"].append(record)
            results.extend(findings)
            execution_failed |= failed_execution
            report["tests"] += record["tests"]
            report["failedTests"] += record["failedTests"]
        report["status"] = "failed" if results or execution_failed else "passed"
    except (GateError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        execution_failed = True
        results.append(finding("ORANGE-ACTION-ERROR", str(error)))
    report["findings"] = results
    sarif_path, report_path = write_reports(directory, workspace, report, results, execution_failed)
    outputs = {"status": report["status"], "files": len(report.get("selectedFiles", [])),
               "tests": report["tests"], "failed-tests": report["failedTests"],
               "sarif-file": str(sarif_path), "report-file": str(report_path),
               "orangec": str(compiler) if compiler is not None else ""}
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            for key, value in outputs.items():
                output.write(f"{key}={value}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
            summary.write(f"### Orange Verify: {report['status']}\n\n")
            summary.write(f"Mode: {mode if mode in ('test', 'check') else 'invalid'}. "
                          f"{outputs['files']} entry points; {report['tests']} assertions; "
                          f"{report['failedTests']} failing assertions.\n\n")
            summary.write("Pre-alpha source validation and native assertions. Formal proof checking is not implemented.\n")
    for result in results[:20]:
        properties = {"title": result["ruleId"]}
        if result.get("locations"):
            location = result["locations"][0]["physicalLocation"]
            from urllib.parse import unquote
            properties["file"] = unquote(location["artifactLocation"]["uri"])
            if location.get("region"):
                properties["line"] = str(location["region"]["startLine"])
                properties["col"] = str(location["region"]["startColumn"])
        props = ",".join(f"{key}={escape_command(value, property_value=True)}" for key, value in properties.items())
        print(f"::{result['level']} {props}::{escape_command(result['message']['text'])}")
    print(f"Orange Verify: {report['status']}; {outputs['files']} entry points, {report['tests']} assertions")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
