"""Detección de Windows SDK (MSVC) y w64devkit (GCC/MinGW)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MIN_SDK = (10, 0, 20348, 0)   # Windows SDK 10.0.20348.0 o posterior
MIN_GCC = (16, 1, 0)          # versión de GCC pedida para w64devkit

_SDK_RE = re.compile(r"\d+\.\d+\.\d+\.\d+")


def parse_version(text: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", text))


@dataclass(frozen=True)
class SDK:
    version: str
    root: Path  # ...\Windows Kits\10


@dataclass(frozen=True)
class MinGW:
    gcc: Path
    bin: Path
    version: tuple

    @property
    def version_str(self) -> str:
        return ".".join(map(str, self.version))


def find_windows_sdks(min_version: tuple = MIN_SDK) -> list[SDK]:
    """Windows SDKs instalados con versión >= min_version (la más nueva primero)."""
    roots = []
    for var in ("WindowsSdkDir", "ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(var)
        if not base:
            continue
        p = Path(base)
        roots.append(p if var == "WindowsSdkDir" else p / "Windows Kits" / "10")

    found: dict[str, SDK] = {}
    for root in roots:
        inc = root / "Include"
        if not inc.is_dir():
            continue
        for d in inc.iterdir():
            if _SDK_RE.fullmatch(d.name) and (d / "um").is_dir():
                if parse_version(d.name) >= min_version:
                    found[d.name] = SDK(d.name, root)
    return sorted(found.values(), key=lambda s: parse_version(s.version), reverse=True)


def _gcc_version(gcc: Path) -> Optional[tuple]:
    try:
        out = subprocess.run(
            [str(gcc), "-dumpfullversion"], capture_output=True, text=True, timeout=20
        ).stdout.strip()
        return parse_version(out) or None
    except (OSError, subprocess.SubprocessError):
        return None


def find_w64devkit(min_gcc: tuple = MIN_GCC) -> Optional[MinGW]:
    """Busca w64devkit: W64DEVKIT_HOME, PATH, y rutas comunes."""
    cands: list[Path] = []
    home = os.environ.get("W64DEVKIT_HOME") or os.environ.get("W64DEVKIT")
    if home:
        cands.append(Path(home) / "bin" / "gcc.exe")
    which = shutil.which("gcc")
    if which:
        cands.append(Path(which))
    for p in (r"C:\w64devkit", r"C:\tools\w64devkit", str(Path.home() / "w64devkit")):
        cands.append(Path(p) / "bin" / "gcc.exe")

    for gcc in cands:
        if gcc.is_file():
            v = _gcc_version(gcc)
            if v and v >= min_gcc:
                return MinGW(gcc=gcc, bin=gcc.parent, version=v)
    return None


def find_gcc() -> Optional[MinGW]:
    """Cualquier gcc/g++ en el PATH (sin exigir versión)."""
    g = shutil.which("gcc")
    if g and shutil.which("g++"):
        gp = Path(g)
        return MinGW(gcc=gp, bin=gp.parent, version=_gcc_version(gp) or ())
    return None


def detect(min_sdk: tuple = MIN_SDK, min_gcc: tuple = MIN_GCC) -> dict:
    """Resumen de lo que hay disponible en este equipo."""
    sdks = find_windows_sdks(min_sdk)
    mingw = find_w64devkit(min_gcc)
    return {
        "msvc_sdks": [s.version for s in sdks],
        "w64devkit": mingw.version_str if mingw else None,
        "w64devkit_path": str(mingw.bin) if mingw else None,
        "gcc_en_path": (lambda g: str(g.gcc) if g else None)(find_gcc()),
    }
