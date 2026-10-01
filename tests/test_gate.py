"""Exercise actual compiler behavior and failures that could otherwise give false green CI."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gate", ROOT / "scripts/run.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)

    def source(self, name="hello.or", text="edition 2026;\nmodule hello { }\n"):
        path = self.workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class WorkspaceTests(WorkspaceCase):
    def test_missing_paths_fails(self):
        with self.assertRaises(gate.GateError):
            gate.select_files(self.workspace, "\n")

    def test_glob_without_matches_fails(self):
        with self.assertRaises(gate.GateError):
            gate.select_files(self.workspace, "**/*.or")

    def test_each_selection_must_match(self):
        self.source()
        with self.assertRaises(gate.GateError):
            gate.select_files(self.workspace, "hello.or\nmissing/*.or")

    def test_directory_selection_is_sorted_and_deduplicated(self):
        self.source("src/b.or")
        self.source("src/a.or")
        self.assertEqual(gate.select_files(self.workspace, "src\nsrc/*.or"),
                         [Path("src/a.or"), Path("src/b.or")])

    def test_parent_and_absolute_paths_fail(self):
        for selection in ("../x.or", "/tmp/x.or", "src/../x.or"):
            with self.subTest(selection=selection), self.assertRaises(gate.GateError):
                gate.select_files(self.workspace, selection)

    def test_symlinked_file_fails(self):
        self.source()
        (self.workspace / "linked.or").symlink_to("hello.or")
        with self.assertRaises(gate.GateError):
            gate.select_files(self.workspace, "linked.or")

    def test_symlinked_parent_fails(self):
        self.source("src/hello.or")
        (self.workspace / "linked").symlink_to("src", target_is_directory=True)
        with self.assertRaises(gate.GateError):
            gate.select_files(self.workspace, "linked/hello.or")

    def test_git_metadata_is_excluded(self):
        self.source(".git/ignored.or")
        self.source()
        self.assertEqual(gate.select_files(self.workspace, "."), [Path("hello.or")])

    def test_paths_with_spaces_are_supported(self):
        self.source("src/a file.or")
        self.assertEqual(gate.select_files(self.workspace, "src/a file.or"), [Path("src/a file.or")])

    def test_oversized_source_fails_before_execution(self):
        path = self.source()
        with path.open("wb") as output:
            output.truncate(gate.MAX_SOURCE_BYTES + 1)
        with self.assertRaises(gate.GateError):
            gate.select_files(self.workspace, "hello.or")

    def test_empty_directory_fails(self):
        (self.workspace / "src").mkdir()
        with self.assertRaises(gate.GateError):
            gate.select_files(self.workspace, "src")

    def test_control_character_filename_fails(self):
        self.source("bad\tname.or")
        with self.assertRaises(gate.GateError):
            gate.select_files(self.workspace, "*.or")

    def test_non_or_selection_fails(self):
        self.source("readme.md")
        with self.assertRaises(gate.GateError):
            gate.select_files(self.workspace, "readme.md")

    def test_compiler_diagnostic_keeps_source_position(self):
        self.source("src/colon:name.or")
        results = gate.compiler_findings("error[ORC0001]: unexpected character\n --> src/colon:name.or:4:8\n",
                                         self.workspace, Path("hello.or"))
        physical = results[0]["locations"][0]["physicalLocation"]
        self.assertEqual(physical["artifactLocation"]["uri"], "src/colon%3Aname.or")
        self.assertEqual(physical["region"], {"startLine": 4, "startColumn": 8})

    def test_imported_module_position_is_kept(self):
        self.source("lib.or")
        results = gate.compiler_findings("error[ORC0001]: bad library\n --> lib.or:2:3\n",
                                         self.workspace, Path("main.or"))
        self.assertEqual(results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], "lib.or")

    def test_escaped_unicode_source_name_round_trips(self):
        self.source("é.or")
        results = gate.compiler_findings("error[ORC0001]: bad\n --> \\u{e9}.or:1:1\n",
                                         self.workspace, Path("main.or"))
        self.assertEqual(results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], "%C3%A9.or")

    def test_backslash_source_name_round_trips(self):
        self.source("a\\b.or")
        results = gate.compiler_findings("error[ORC0001]: bad\n --> a\\\\b.or:1:1\n",
                                         self.workspace, Path("main.or"))
        self.assertEqual(results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], "a%5Cb.or")

    def test_outside_diagnostic_has_no_invented_region(self):
        results = gate.compiler_findings("error[ORC0001]: bad\n --> /etc/passwd:1:1\n",
                                         self.workspace, Path("main.or"))
        self.assertNotIn("region", results[0]["locations"][0]["physicalLocation"])

    def fake_compiler(self, body):
        compiler = self.workspace / "fake-compiler"
        compiler.write_text("#!" + sys.executable + "\n" + body, encoding="utf-8")
        compiler.chmod(0o755)
        return compiler

    def test_malformed_test_report_cannot_pass(self):
        self.source()
        compiler = self.fake_compiler('print("0 tests: 0 passed, 1 failed")\n')
        record, results, failed = gate.run_entry(compiler, self.workspace, Path("hello.or"), "test", 100, 10)
        self.assertEqual(record["status"], "failed")
        self.assertTrue(failed)
        self.assertEqual(results[0]["ruleId"], "ORANGE-ACTION-REPORT")

    def test_missing_report_cannot_pass(self):
        self.source()
        compiler = self.fake_compiler('print("unexpected output")\n')
        record, _, failed = gate.run_entry(compiler, self.workspace, Path("hello.or"), "test", 100, 10)
        self.assertEqual(record["status"], "failed")
        self.assertTrue(failed)

    def test_crashed_compiler_cannot_pass(self):
        self.source()
        compiler = self.fake_compiler("import sys\nsys.exit(3)\n")
        record, results, failed = gate.run_entry(compiler, self.workspace, Path("hello.or"), "check", 100, 10)
        self.assertEqual(record["status"], "failed")
        self.assertTrue(failed)
        self.assertEqual(results[0]["ruleId"], "ORANGE-ACTION-EXECUTION")

    def test_compiler_failure_without_diagnostic_cannot_pass(self):
        self.source()
        compiler = self.fake_compiler("import sys\nsys.exit(1)\n")
        record, results, _ = gate.run_entry(compiler, self.workspace, Path("hello.or"), "check", 100, 10)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(results[0]["ruleId"], "ORANGE-CHECK-FAILED")

    def test_oversized_compiler_output_cannot_pass(self):
        self.source()
        compiler = self.fake_compiler(f'print("x" * {gate.MAX_LOG_BYTES + 1})\n')
        with contextlib.redirect_stdout(io.StringIO()):
            record, results, failed = gate.run_entry(compiler, self.workspace, Path("hello.or"), "check", 100, 10)
        self.assertEqual(record["status"], "failed")
        self.assertTrue(failed)
        self.assertEqual(results[0]["ruleId"], "ORANGE-ACTION-OUTPUT")

    def test_timeout_cannot_pass(self):
        self.source()
        compiler = self.fake_compiler("import time\ntime.sleep(10)\n")
        record, results, failed = gate.run_entry(compiler, self.workspace, Path("hello.or"), "test", 100, 1)
        self.assertTrue(failed)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(results[0]["ruleId"], "ORANGE-ACTION-TIMEOUT")

    def test_untrusted_stdout_cannot_inject_runner_commands(self):
        self.source()
        compiler = self.fake_compiler('print("::error::injected")\nprint("1 test: 1 passed, 0 failed")\n')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            gate.run_entry(compiler, self.workspace, Path("hello.or"), "test", 100, 10)
        self.assertFalse(any(line.startswith("::") for line in output.getvalue().splitlines()))

    def test_generated_sarif_records_no_proof_claim(self):
        report = {"claimKind": "native-assertions", "compiler": {}}
        sarif_path, _ = gate.write_reports(self.workspace, self.workspace, report,
                                         [gate.finding("ORANGE-TEST-FAILED", "broken", Path("a#b.or"))], False)
        run = json.loads(sarif_path.read_text())["runs"][0]
        self.assertFalse(run["properties"]["formalProofChecking"])
        self.assertTrue(run["invocations"][0]["executionSuccessful"])
        self.assertEqual(run["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], "a%23b.or")


class ValueTests(unittest.TestCase):
    def test_invalid_budgets_fail(self):
        for value in ("0", "-1", "1; echo broken", "1\n", "1073741825", "nan"):
            with self.subTest(value=value), self.assertRaises(gate.GateError):
                gate.bounded_integer(value, "steps", 1 << 30)

    def test_annotations_escape_command_and_property_controls(self):
        self.assertEqual(gate.escape_command("x%\r\n,:y", property_value=True), "x%25%0D%0A%2C%3Ay")


@unittest.skipUnless(os.environ.get("ORANGEC"), "set ORANGEC to exercise the real Orange compiler")
class NativeCompilerTests(WorkspaceCase):
    def native(self, name, mode="test", steps=1048576):
        text = (ROOT / "examples" / name).read_text(encoding="utf-8")
        self.source(name, text)
        return gate.run_entry(Path(os.environ["ORANGEC"]), self.workspace, Path(name), mode, steps, 120)

    def test_real_native_assertions_pass(self):
        record, results, failed = self.native("pass.or")
        self.assertEqual(record["status"], "passed")
        self.assertEqual(record["tests"], 2)
        self.assertEqual(results, [])
        self.assertFalse(failed)

    def test_real_rfc8439_quarter_round(self):
        record, results, failed = self.native("rfc8439.or")
        self.assertEqual(record["status"], "passed")
        self.assertEqual(record["tests"], 1)
        self.assertEqual(results, [])
        self.assertFalse(failed)

    def test_real_broken_assertion_fails_with_file_location(self):
        record, results, failed = self.native("fail.or")
        self.assertEqual(record["failedTests"], 1)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(results[0]["ruleId"], "ORANGE-TEST-FAILED")
        self.assertNotIn("region", results[0]["locations"][0]["physicalLocation"])
        self.assertFalse(failed)

    def test_real_zero_test_source_cannot_pass_test_mode(self):
        record, results, failed = self.native("no-tests.or")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(results[0]["ruleId"], "ORANGE-ACTION-NO-TESTS")
        self.assertTrue(failed)

    def test_check_mode_admits_source_without_assertions(self):
        record, results, failed = self.native("no-tests.or", "check")
        self.assertEqual(record["status"], "passed")
        self.assertEqual(record["tests"], 0)
        self.assertEqual(results, [])
        self.assertFalse(failed)

    def test_real_compiler_diagnostic_has_a_position(self):
        self.source("bad.or", "edition 2026;\nmodule bad { @ }\n")
        record, results, failed = gate.run_entry(Path(os.environ["ORANGEC"]), self.workspace,
                                               Path("bad.or"), "check", 100, 120)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(results[0]["ruleId"], "ORC0001")
        self.assertEqual(results[0]["locations"][0]["physicalLocation"]["region"]["startLine"], 2)
        self.assertFalse(failed)

    def test_real_budget_exhaustion_cannot_pass(self):
        record, results, failed = self.native("pass.or", steps=1)
        self.assertEqual(record["status"], "failed")
        self.assertTrue(results)
        self.assertTrue(failed)

    def test_shell_metacharacters_and_leading_dash_are_literal_paths(self):
        name = "-odd $(touch marker).or"
        self.source(name, (ROOT / "examples/pass.or").read_text())
        record, results, failed = gate.run_entry(Path(os.environ["ORANGEC"]), self.workspace,
                                               Path(name), "test", 1048576, 120)
        self.assertEqual(record["status"], "passed")
        self.assertFalse((self.workspace / "marker").exists())
        self.assertEqual(results, [])
        self.assertFalse(failed)

    def action(self, **inputs):
        environment = os.environ.copy()
        environment.update({"GITHUB_WORKSPACE": str(self.workspace), "RUNNER_TEMP": str(self.workspace),
                            "RUNNER_OS": "Linux", "GITHUB_OUTPUT": str(self.workspace / "output.txt"),
                            "GITHUB_STEP_SUMMARY": str(self.workspace / "summary.md"),
                            "ORANGE_INPUT_ORANGEC": os.environ["ORANGEC"], "ORANGE_INPUT_PATHS": "fail.or",
                            "ORANGE_INPUT_MODE": "test", "ORANGE_INPUT_REF": gate.DEFAULT_REF,
                            "ORANGE_INPUT_STEPS": "1048576", "ORANGE_INPUT_TIMEOUT": "120"})
        environment.update(inputs)
        completed = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/run.py")], env=environment,
                                   capture_output=True, text=True, check=False, timeout=120)
        outputs = dict(line.split("=", 1) for line in (self.workspace / "output.txt").read_text().splitlines())
        report = json.loads(Path(outputs["report-file"]).read_text())
        sarif = json.loads(Path(outputs["sarif-file"]).read_text())
        return completed, outputs, report, sarif

    def test_action_persists_reports_and_outputs_on_failure(self):
        self.source("fail.or", (ROOT / "examples/fail.or").read_text())
        completed, outputs, report, sarif = self.action()
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(outputs["status"], "failed")
        self.assertEqual(outputs["failed-tests"], "1")
        self.assertEqual(report["compiler"]["provenance"], "caller-supplied")
        self.assertIsNone(report["compiler"]["sourceCommit"])
        self.assertTrue(sarif["runs"][0]["invocations"][0]["executionSuccessful"])

    def test_action_rejects_mutable_source_ref(self):
        completed, outputs, _, sarif = self.action(ORANGE_INPUT_REF="main")
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(outputs["status"], "failed")
        self.assertFalse(sarif["runs"][0]["invocations"][0]["executionSuccessful"])

    def test_action_cannot_claim_formal_proof(self):
        completed, _, report, _ = self.action(ORANGE_INPUT_MODE="proof")
        self.assertEqual(completed.returncode, 1)
        self.assertFalse(report["formalProofChecking"])
        self.assertEqual(report["claimKind"], "unavailable")

    def test_action_rejects_relative_compiler(self):
        self.source("fail.or", (ROOT / "examples/fail.or").read_text())
        completed, _, _, _ = self.action(ORANGE_INPUT_ORANGEC="./orangec")
        self.assertEqual(completed.returncode, 1)


if __name__ == "__main__":
    unittest.main()
