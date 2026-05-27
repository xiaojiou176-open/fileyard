import subprocess
import sys
from pathlib import Path


def _checker(script_root: Path) -> Path:
    return script_root / "tooling" / "scripts" / "check_test_quality.py"


def _python_bin(script_root: Path) -> Path:
    repo_root = script_root.parent
    venv_python = repo_root / ".runtime-cache" / "venv" / "default" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def test_quality_gate_passes_clean_tests(tmp_path: Path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_ok.py").write_text(
        "def test_ok():\n    value = 1\n    assert value == 1\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0
    assert "no placebo assertions" in (proc.stdout + proc.stderr)


def test_quality_gate_blocks_python_placebo_assertions(tmp_path: Path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_bad.py").write_text(
        "def test_bad():\n    assert True\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "PY_ASSERT_TRUE" in out
    assert "test_bad.py" in out


def test_quality_gate_blocks_python_literal_self_equal(tmp_path: Path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_bad_literal.py").write_text(
        "def test_bad_literal():\n    assert 1 == 1\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "PY_LITERAL_SELF_EQUAL" in out
    assert "test_bad_literal.py" in out


def test_quality_gate_blocks_python_truthy_constant_assertions(tmp_path: Path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_bad_truthy.py").write_text(
        "import unittest\n\n"
        "def test_bad_truthy():\n"
        "    assert 1\n\n"
        "class _T(unittest.TestCase):\n"
        "    def test_bad_unittest_truthy(self):\n"
        "        self.assertTrue(1)\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-python",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "PY_ASSERT_TRUTHY_CONSTANT" in out
    assert "PY_ASSERTTRUE_TRUTHY_CONSTANT" in out
    assert "test_bad_truthy.py" in out


def test_quality_gate_blocks_python_no_assertion(tmp_path: Path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_no_assert.py").write_text(
        "def test_no_assert():\n    value = 1 + 1\n    _ = value\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-python",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "PY_NO_ASSERTION" in out


def test_quality_gate_blocks_python_no_assertion_with_suffix_test_naming(tmp_path: Path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "sample_test.py").write_text(
        "def test_suffix_name_without_assert():\n    value = 1 + 1\n    _ = value\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-python",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "PY_NO_ASSERTION" in out
    assert "sample_test.py" in out


def test_quality_gate_blocks_python_no_assertion_when_call_name_contains_assert(tmp_path: Path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_assertion_name_bypass.py").write_text(
        "def test_assertion_name_bypass():\n    reassert_helper()\n\ndef reassert_helper():\n    return 1\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-python",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "PY_NO_ASSERTION" in out
    assert "test_assertion_name_bypass.py" in out


def test_quality_gate_blocks_python_no_assertion_for_test_file_without_underscore(tmp_path: Path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "teststyle.py").write_text(
        "def test_without_assert():\n    value = 2 + 2\n    _ = value\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-python",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "PY_NO_ASSERTION" in out
    assert "teststyle.py" in out


def test_quality_gate_allows_python_no_assertion_with_marker(tmp_path: Path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_no_assert_allowed.py").write_text(
        "def test_no_assert_allowed():\n    # test-quality: allow-no-assert\n    value = 1 + 1\n    _ = value\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-python",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0


def test_quality_gate_does_not_allow_python_no_assertion_marker_inside_string(tmp_path: Path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_no_assert_marker_in_string.py").write_text(
        "def test_no_assert_marker_in_string():\n    note = 'test-quality: allow-no-assert'\n    _ = note\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-python",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "PY_NO_ASSERTION" in out
    assert "test_no_assert_marker_in_string.py" in out


def test_quality_gate_blocks_python_skip_only_without_assertion(tmp_path: Path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_skip_only.py").write_text(
        "import pytest\n\ndef test_skip_only():\n    pytest.skip('not implemented yet')\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-python",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "PY_NO_ASSERTION" in out
    assert "test_skip_only.py" in out


def test_quality_gate_blocks_python_xfail_only_without_assertion(tmp_path: Path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_xfail_only.py").write_text(
        "import pytest\n\ndef test_xfail_only():\n    pytest.xfail('not implemented yet')\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-python",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "PY_NO_ASSERTION" in out
    assert "test_xfail_only.py" in out


def test_quality_gate_blocks_jest_placebo_assertions(tmp_path: Path):
    tests_dir = tmp_path / "frontend" / "__tests__"
    tests_dir.mkdir(parents=True)
    (tests_dir / "sample.test.ts").write_text(
        "test('x', () => { expect(true).toBe(true); });\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "JS_EXPECT_TRUE" in out
    assert "sample.test.ts" in out


def test_quality_gate_blocks_multiline_jest_placebo_assertions(tmp_path: Path):
    tests_dir = tmp_path / "frontend" / "__tests__"
    tests_dir.mkdir(parents=True)
    (tests_dir / "multiline.test.ts").write_text(
        "test('x', () => {\n  expect(true)\n    .toBe(true)\n})\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-js",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "JS_EXPECT_TRUE" in out
    assert "multiline.test.ts" in out


def test_quality_gate_blocks_jest_to_be_defined(tmp_path: Path):
    tests_dir = tmp_path / "frontend" / "__tests__"
    tests_dir.mkdir(parents=True)
    (tests_dir / "defined.test.ts").write_text(
        "test('x', () => { expect(value).toBeDefined(); });\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "JS_TOBEDEFINED" in out
    assert "defined.test.ts" in out


def test_quality_gate_allows_tobe_defined_with_explicit_marker(tmp_path: Path):
    tests_dir = tmp_path / "frontend" / "__tests__"
    tests_dir.mkdir(parents=True)
    (tests_dir / "allowed.test.ts").write_text(
        "test('x', () => { expect(value).toBeDefined(); // test-quality: allow-toBeDefined });\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-js",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0


def test_quality_gate_does_not_allow_tobe_defined_marker_inside_string(tmp_path: Path):
    tests_dir = tmp_path / "frontend" / "__tests__"
    tests_dir.mkdir(parents=True)
    (tests_dir / "marker_in_string.test.ts").write_text(
        "test('x', () => { const marker = '// test-quality: allow-toBeDefined'; expect(value).toBeDefined(); });\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-js",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "JS_TOBEDEFINED" in out
    assert "marker_in_string.test.ts" in out


def test_quality_gate_tobe_defined_marker_does_not_whitelist_expect_true(tmp_path: Path):
    tests_dir = tmp_path / "frontend" / "__tests__"
    tests_dir.mkdir(parents=True)
    (tests_dir / "marker_scope.test.ts").write_text(
        "test('x', () => { expect(true).toBe(true); // test-quality: allow-toBeDefined });\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-js",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "JS_EXPECT_TRUE" in out
    assert "marker_scope.test.ts" in out


def test_quality_gate_blocks_jest_literal_self_equal(tmp_path: Path):
    tests_dir = tmp_path / "frontend" / "__tests__"
    tests_dir.mkdir(parents=True)
    (tests_dir / "literal.test.ts").write_text(
        "test('x', () => { expect('ok').toBe('ok'); });\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--only-js",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "JS_LITERAL_SELF_EQUAL" in out
    assert "literal.test.ts" in out
