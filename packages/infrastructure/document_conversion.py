# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Optional, Tuple

_MAX_STDERR_CAPTURE_BYTES = 512 * 1024
_STDERR_TAIL_CHARS = 2000
_MIN_SUBPROCESS_TIMEOUT_S = 1.0
_DEFAULT_SUBPROCESS_TIMEOUT_S = 120.0
_TRUSTED_BIN_DIRS = (
    "/usr/bin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/opt/local/bin",
    "/Applications/LibreOffice.app/Contents/MacOS",
)


def _is_test_hooks_enabled() -> bool:
    return os.environ.get("FILEYARD_ENABLE_TEST_HOOKS", "") == "1" or bool(os.environ.get("PYTEST_CURRENT_TEST", ""))


def _is_trusted_executable(path: Path) -> bool:
    if _is_test_hooks_enabled():
        return path.exists() and path.is_file()
    if not path.exists() or not path.is_file() or not path.is_absolute():
        return False
    resolved = path.resolve()
    text = str(resolved)
    return any(text == base or text.startswith(base + "/") for base in _TRUSTED_BIN_DIRS)


def _normalize_timeout(timeout_s: float, *, default_s: float = _DEFAULT_SUBPROCESS_TIMEOUT_S) -> float:
    try:
        parsed = float(timeout_s)
    except (TypeError, ValueError):
        parsed = default_s
    if parsed <= 0:
        parsed = default_s
    return max(_MIN_SUBPROCESS_TIMEOUT_S, parsed)


def _tail_stderr_from_file(stderr_file) -> str:
    try:
        stderr_file.seek(0, 2)
        size = stderr_file.tell()
        if size <= 0:
            return ""
        offset = max(0, size - _MAX_STDERR_CAPTURE_BYTES)
        stderr_file.seek(offset, 0)
        data = stderr_file.read()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    return text[-_STDERR_TAIL_CHARS:]


def _validate_source_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"Source document is missing or not a regular file: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise RuntimeError(f"Failed to read document file metadata: {path}") from exc
    if size <= 0:
        raise RuntimeError(f"Document file is empty and cannot be converted: {path}")
    if not os.access(path, os.R_OK):
        raise RuntimeError(f"Document file is not readable: {path}")


def find_libreoffice() -> Optional[str]:
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for item in candidates:
        if not item:
            continue
        candidate = Path(item).expanduser()
        if _is_trusted_executable(candidate):
            return str(candidate.resolve())
    return None


def find_unoconv() -> Optional[str]:
    raw = shutil.which("unoconv")
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not _is_trusted_executable(candidate):
        return None
    return str(candidate.resolve())


def convert_to_pdf(path: Path, timeout_s: float = 120.0) -> Tuple[Path, Optional[Path], str]:
    _validate_source_file(path)
    safe_timeout_s = _normalize_timeout(timeout_s)
    temp_dir = Path(tempfile.mkdtemp(prefix="doc_pdf_"))
    try:
        soffice = find_libreoffice()
        if soffice:
            cmd = [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(temp_dir),
                str(path),
            ]
            with tempfile.TemporaryFile(mode="w+b") as stderr_file:
                try:
                    subprocess.run(  # nosec B603
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=stderr_file,
                        check=True,
                        timeout=safe_timeout_s,
                    )
                except Exception as exc:
                    stderr_tail = _tail_stderr_from_file(stderr_file)
                    detail = f"{exc}; stderr={stderr_tail}" if stderr_tail else str(exc)
                    raise RuntimeError(f"LibreOffice PDF conversion failed: {detail}") from exc
            pdfs = sorted(temp_dir.glob("*.pdf"))
            if not pdfs:
                raise RuntimeError("LibreOffice did not produce a PDF file")
            return pdfs[0], temp_dir, "libreoffice"

        unoconv = find_unoconv()
        if unoconv:
            out_path = temp_dir / f"{path.stem}.pdf"
            cmd = [unoconv, "-f", "pdf", "-o", str(out_path), str(path)]
            with tempfile.TemporaryFile(mode="w+b") as stderr_file:
                try:
                    subprocess.run(  # nosec B603
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=stderr_file,
                        check=True,
                        timeout=safe_timeout_s,
                    )
                except Exception as exc:
                    stderr_tail = _tail_stderr_from_file(stderr_file)
                    detail = f"{exc}; stderr={stderr_tail}" if stderr_tail else str(exc)
                    raise RuntimeError(f"unoconv PDF conversion failed: {detail}") from exc
            if not out_path.exists():
                raise RuntimeError("unoconv did not produce a PDF file")
            return out_path, temp_dir, "unoconv"

        raise RuntimeError("LibreOffice/soffice or unoconv is required")
    except Exception:
        with suppress(OSError):
            shutil.rmtree(temp_dir)
        raise
