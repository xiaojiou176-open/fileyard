from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_clusterfuzzlite_dockerfile_pins_base_image_and_hash_locked_requirements() -> None:
    dockerfile = (_repo_root() / ".clusterfuzzlite" / "Dockerfile").read_text(encoding="utf-8")

    assert "base-builder-python@sha256:6bb326cd90cc82d526add050b67b92bf53f900d5f61aa9abd74cc2f04f622dc9" in dockerfile
    assert "--require-hashes -r $SRC/movi-organizer/.clusterfuzzlite/requirements.txt" in dockerfile
    assert 'pip install --disable-pip-version-check .' not in dockerfile


def test_clusterfuzzlite_build_script_avoids_unpinned_pip_installs() -> None:
    script = (_repo_root() / ".clusterfuzzlite" / "build.sh").read_text(encoding="utf-8")

    assert 'export PYTHONPATH="${PYTHONPATH:-$SRC/movi-organizer}"' in script
    assert "pip install" not in script
    assert "compile_python_fuzzer tests/fuzz/fuzz_safe_join.py" in script


def test_clusterfuzzlite_requirements_pin_atheris_by_hash() -> None:
    requirements = (_repo_root() / ".clusterfuzzlite" / "requirements.txt").read_text(encoding="utf-8")

    assert "atheris==2.3.0" in requirements
    assert "--hash=sha256:cf1fdf5fa220a41a2f262b32363fc566549502b2cb0addf4e1baad5531c0e825" in requirements
