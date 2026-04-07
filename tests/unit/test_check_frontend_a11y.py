from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _script_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _checker(script_root: Path) -> Path:
    return script_root / "tooling" / "scripts" / "check_frontend_a11y.py"


def _python_bin(script_root: Path) -> Path:
    repo_root = script_root.parent
    venv_python = repo_root / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def test_check_frontend_a11y_passes_on_basic_accessible_html(tmp_path: Path) -> None:
    html = tmp_path / "ok.html"
    html.write_text(
        """<!doctype html>
<html lang="en">
<head><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body>
  <label for="email">Email</label>
  <input id="email" />
  <img src="/a.png" alt="desc" />
  <button type="button">Save</button>
</body>
</html>
""",
        encoding="utf-8",
    )
    script_root = _script_root()
    proc = subprocess.run(
        [str(_python_bin(script_root)), str(_checker(script_root)), str(html)],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "check_frontend_a11y: passed" in proc.stdout + proc.stderr


def test_check_frontend_a11y_blocks_missing_alt_and_button_type(tmp_path: Path) -> None:
    html = tmp_path / "bad.html"
    html.write_text(
        """<!doctype html>
<html>
<head></head>
<body>
  <img src="/a.png" />
  <button>Save</button>
  <input id="email" />
</body>
</html>
""",
        encoding="utf-8",
    )
    script_root = _script_root()
    proc = subprocess.run(
        [str(_python_bin(script_root)), str(_checker(script_root)), str(html)],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "img missing alt attribute" in out
    assert "button missing explicit type" in out


def test_check_frontend_a11y_accepts_common_jsx_syntax(tmp_path: Path) -> None:
    tsx = tmp_path / "ok.tsx"
    tsx.write_text(
        """export function Demo() {
  const imageAlt = "cover";
  return (
    <form>
      <label htmlFor="email">Email</label>
      <input id="email" />
      <img src="/a.png" alt={imageAlt} />
      <button type={"button"}>Save</button>
    </form>
  );
}
""",
        encoding="utf-8",
    )
    script_root = _script_root()
    proc = subprocess.run(
        [str(_python_bin(script_root)), str(_checker(script_root)), str(tsx)],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "check_frontend_a11y: passed" in proc.stdout + proc.stderr


def test_check_frontend_a11y_blocks_icon_only_button_without_name(tmp_path: Path) -> None:
    html = tmp_path / "icon_only_button.html"
    html.write_text(
        """<!doctype html>
<html lang="en">
<head><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body>
  <button type="button"><svg aria-hidden="true"></svg></button>
</body>
</html>
""",
        encoding="utf-8",
    )
    script_root = _script_root()
    proc = subprocess.run(
        [str(_python_bin(script_root)), str(_checker(script_root)), str(html)],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "icon-only button missing accessible name" in out


def test_check_frontend_a11y_blocks_zoom_disabling_viewport(tmp_path: Path) -> None:
    html = tmp_path / "bad_viewport.html"
    html.write_text(
        """<!doctype html>
<html lang="en">
<head><meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no"></head>
<body>
  <label for="email">Email</label>
  <input id="email" />
  <img src="/a.png" alt="desc" />
  <button type="button">Save</button>
</body>
</html>
""",
        encoding="utf-8",
    )
    script_root = _script_root()
    proc = subprocess.run(
        [str(_python_bin(script_root)), str(_checker(script_root)), str(html)],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "viewport must not disable zoom via user-scalable=no/0/false" in out
    assert "viewport maximum-scale should be >=2 to preserve zoom" in out


def test_check_frontend_a11y_blocks_zoom_disabling_viewport_zero_variant(tmp_path: Path) -> None:
    html = tmp_path / "bad_viewport_zero.html"
    html.write_text(
        """<!doctype html>
<html lang="en">
<head><meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=0"></head>
<body>
  <label for="email">Email</label>
  <input id="email" />
  <img src="/a.png" alt="desc" />
  <button type="button">Save</button>
</body>
</html>
""",
        encoding="utf-8",
    )
    script_root = _script_root()
    proc = subprocess.run(
        [str(_python_bin(script_root)), str(_checker(script_root)), str(html)],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "viewport must not disable zoom via user-scalable=no/0/false" in out


def test_check_frontend_a11y_blocks_icon_only_link_without_name(tmp_path: Path) -> None:
    html = tmp_path / "icon_only_link.html"
    html.write_text(
        """<!doctype html>
<html lang="en">
<head><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body>
  <a href="/download"><svg aria-hidden="true"></svg></a>
</body>
</html>
""",
        encoding="utf-8",
    )
    script_root = _script_root()
    proc = subprocess.run(
        [str(_python_bin(script_root)), str(_checker(script_root)), str(html)],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "icon-only link missing accessible name" in out


def test_check_frontend_a11y_blocks_focus_outline_removed_without_replacement(tmp_path: Path) -> None:
    tsx = tmp_path / "focus_bad.tsx"
    tsx.write_text(
        """export function Demo() {
  return (
    <button type="button" className="focus:outline-none">Save</button>
  );
}
""",
        encoding="utf-8",
    )
    script_root = _script_root()
    proc = subprocess.run(
        [str(_python_bin(script_root)), str(_checker(script_root)), str(tsx)],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "focus outline removed without replacement focus indicator" in out


def test_check_frontend_a11y_accepts_focus_outline_removed_with_replacement(tmp_path: Path) -> None:
    tsx = tmp_path / "focus_ok.tsx"
    tsx.write_text(
        """export function Demo() {
  return (
    <button type="button" className="focus:outline-none focus:ring-2">Save</button>
  );
}
""",
        encoding="utf-8",
    )
    script_root = _script_root()
    proc = subprocess.run(
        [str(_python_bin(script_root)), str(_checker(script_root)), str(tsx)],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "check_frontend_a11y: passed" in proc.stdout + proc.stderr


def test_check_frontend_a11y_accepts_aria_labeled_control_without_label_for(tmp_path: Path) -> None:
    html = tmp_path / "aria_label_control.html"
    html.write_text(
        """<!doctype html>
<html lang="en">
<head><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body>
  <input id="email" aria-label="Email" />
  <img src="/a.png" alt="desc" />
  <button type="button">Save</button>
</body>
</html>
""",
        encoding="utf-8",
    )
    script_root = _script_root()
    proc = subprocess.run(
        [str(_python_bin(script_root)), str(_checker(script_root)), str(html)],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "check_frontend_a11y: passed" in proc.stdout + proc.stderr
