"""Lee .c/.cpp/.h, los pasa a ASM (gcc -S), ensambla y enlaza con SCons.

No usa ningún SDK de Windows: con w64devkit (MinGW-w64) o cualquier gcc
alcanza. MSVC/Windows SDK queda como modo opcional (sin pipeline ASM).
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Sequence

from . import toolchains as tc

C_EXT = {".c"}
CXX_EXT = {".cpp", ".cc", ".cxx", ".c++"}
H_EXT = {".h", ".hpp", ".hh", ".hxx"}
RC_EXT = {".rc"}
SKIP_DIRS = {".git", "__pycache__", ".cpp_c", "node_modules"}


class BuildError(RuntimeError):
    pass


@dataclass
class Project:
    name: str
    sources: list[str]                       # archivos, carpetas o globs (**/*.cpp)
    headers: list[str] = field(default_factory=list)   # .h/.hpp extra (archivos/carpetas)
    kind: str = "program"                    # program | static | shared
    root: str = "."
    build_dir: str = "build"

    # --- preprocesador ---
    include_dirs: list[str] = field(default_factory=list)
    auto_include: bool = True                # agrega las carpetas de los .h encontrados
    defines: list[str] = field(default_factory=list)      # "DEBUG", "VER=3"
    undefines: list[str] = field(default_factory=list)
    force_includes: list[str] = field(default_factory=list)

    # --- lenguaje ---
    c_std: str = "c17"
    cxx_std: str = "c++20"
    exceptions: bool = True
    rtti: bool = True

    # --- optimización / diagnóstico ---
    optimize: str = "2"                      # 0 1 2 3 s z fast g
    debug: bool = False
    warnings: str = "all"                    # none | all | extra
    pedantic: bool = False
    werror: bool = False
    march: Optional[str] = None              # "native", "haswell"...
    mtune: Optional[str] = None
    lto: bool = False
    sanitize: list[str] = field(default_factory=list)     # address, undefined...
    threads: bool = False                    # -pthread
    openmp: bool = False
    arch: str = "x86_64"                     # x86_64 | x86 (-m32)

    # --- pipeline ASM ---
    via_asm: bool = True                     # C/C++ -> .s -> .o -> exe
    asm_syntax: str = "intel"                # intel | att
    asm_comments: bool = False               # -fverbose-asm

    # --- enlace ---
    libs: list[str] = field(default_factory=list)
    lib_dirs: list[str] = field(default_factory=list)
    static_runtime: bool = True
    subsystem: str = "console"               # console | windows (Windows)
    strip: bool = False
    map_file: bool = False

    # --- banderas libres ---
    ccflags: list[str] = field(default_factory=list)      # C y C++
    cflags: list[str] = field(default_factory=list)       # solo C
    cxxflags: list[str] = field(default_factory=list)     # solo C++
    asflags: list[str] = field(default_factory=list)
    linkflags: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    @classmethod
    def from_dir(cls, directory: str, name: str, **kw) -> "Project":
        """Lee recursivamente todos los .c/.cpp/.h de una carpeta."""
        return cls(name=name, sources=[directory], root=kw.pop("root", "."), **kw)

    def resolve(self):
        """-> (units, headers, include_dirs) ya expandidos."""
        root = Path(self.root).resolve()
        skip = SKIP_DIRS | {self.build_dir}
        srcs: list[str] = []
        hdrs: list[str] = []

        def add(p: Path):
            e = p.suffix.lower()
            rel = os.path.relpath(p, root).replace("\\", "/")
            if e in C_EXT | CXX_EXT | RC_EXT:
                if rel not in srcs:
                    srcs.append(rel)
            elif e in H_EXT:
                if rel not in hdrs:
                    hdrs.append(rel)

        for entry in list(self.sources) + list(self.headers):
            pth = root / entry
            if pth.is_dir():
                for dp, dn, fn in os.walk(pth):
                    dn[:] = sorted(d for d in dn if d not in skip)
                    for f in sorted(fn):
                        add(Path(dp) / f)
            elif any(c in entry for c in "*?["):
                for m in sorted(glob.glob(str(root / entry), recursive=True)):
                    add(Path(m))
            elif pth.is_file():
                add(pth)
            else:
                raise BuildError(f"No existe: {entry}")

        if not srcs:
            raise BuildError("No se encontró ningún .c/.cpp para compilar.")

        units, used = [], set()
        for s in srcs:
            ext = os.path.splitext(s)[1].lower()
            lang = "c" if ext in C_EXT else ("rc" if ext in RC_EXT else "cxx")
            stem = os.path.splitext(s)[0].replace("../", "").replace("/", "__").lstrip(".")
            base, n = stem, 1
            while stem in used:
                n += 1
                stem = f"{base}_{n}"
            used.add(stem)
            units.append({"src": s, "stem": stem, "lang": lang})

        incs = list(self.include_dirs)
        if self.auto_include:
            for d in ["."] + [os.path.dirname(h) or "." for h in hdrs]:
                if d not in incs:
                    incs.append(d)
        return units, hdrs, incs


# ----------------------------------------------------------------------
# Banderas GNU
# ----------------------------------------------------------------------
def _gnu_flags(p: Project, has_cxx: bool, use_asm: bool) -> dict:
    cc = [f"-O{p.optimize}"]
    if p.debug:
        cc.append("-g")
    if p.warnings in ("all", "extra"):
        cc.append("-Wall")
    if p.warnings == "extra":
        cc.append("-Wextra")
    if p.pedantic:
        cc.append("-pedantic")
    if p.werror:
        cc.append("-Werror")
    if p.march:
        cc.append(f"-march={p.march}")
    if p.mtune:
        cc.append(f"-mtune={p.mtune}")
    if p.arch == "x86":
        cc.append("-m32")
    if p.sanitize:
        cc.append("-fsanitize=" + ",".join(p.sanitize))
    if p.lto and not use_asm:
        cc.append("-flto")
    if p.threads:
        cc.append("-pthread")
    if p.openmp:
        cc.append("-fopenmp")
    cc += [f"-U{u}" for u in p.undefines]
    for f in p.force_includes:
        cc += ["-include", f]
    cc += p.ccflags

    cxx = [f"-std={p.cxx_std}"]
    if not p.exceptions:
        cxx.append("-fno-exceptions")
    if not p.rtti:
        cxx.append("-fno-rtti")
    cxx += p.cxxflags

    ln = []
    if p.static_runtime:
        ln += ["-static", "-static-libgcc"] + (["-static-libstdc++"] if has_cxx else [])
    if p.lto and not use_asm:
        ln.append("-flto")
    if p.threads:
        ln.append("-pthread")
    if p.openmp:
        ln.append("-fopenmp")
    if p.sanitize:
        ln.append("-fsanitize=" + ",".join(p.sanitize))
    if p.arch == "x86":
        ln.append("-m32")
    if p.subsystem == "windows" and os.name == "nt":
        ln.append("-mwindows")
    if p.strip:
        ln.append("-s")
    if p.map_file:
        ln.append(f"-Wl,-Map={p.build_dir}/{p.name}.map")
    ln += p.linkflags

    return {
        "ccflags": cc,
        "cflags": [f"-std={p.c_std}"] + p.cflags,
        "cxxflags": cxx,
        "asflags": (["-m32"] if p.arch == "x86" else []) + p.asflags,
        "linkflags": ln,
    }


SCONSTRUCT = r'''
import json, os
AddOption("--cpp-c-config", dest="cppc_cfg", type="string")
cfg = json.load(open(GetOption("cppc_cfg"), encoding="utf-8"))
p = cfg["project"]; units = cfg["units"]; bd = p["build_dir"]
has_cxx = any(u["lang"] == "cxx" for u in units)
objs, asm_nodes = [], []

if cfg["toolchain"] == "msvc":
    kw = {"TARGET_ARCH": p["arch"]}
    if cfg.get("sdk"):
        kw["MSVC_SDK_VERSION"] = cfg["sdk"]
    env = Environment(**kw)
    env.Append(CCFLAGS=["/nologo", "/utf-8", "/W3", "/EHsc"],
               CFLAGS=["/std:" + p["c_std"]], CXXFLAGS=["/std:" + p["cxx_std"]])
    opt = {"0": "/Od", "1": "/O1", "2": "/O2", "3": "/Ox", "s": "/O1"}.get(p["optimize"], "/O2")
    env.Append(CCFLAGS=[opt, "/MT" if p["static_runtime"] else "/MD"])
    if p["debug"]:
        env.Append(CCFLAGS=["/Zi"], LINKFLAGS=["/DEBUG"])
    env.Append(CCFLAGS=p["ccflags"], LINKFLAGS=p["linkflags"])
    for u in units:
        if u["lang"] != "rc":
            objs += env.Object(target=os.path.join(bd, "obj", u["stem"]), source=u["src"])
else:
    g = cfg["gnu"]
    ev = {k: os.environ[k] for k in ("TEMP", "TMP", "SYSTEMROOT", "HOME", "LANG") if k in os.environ}
    ev["PATH"] = (cfg["bin"] + os.pathsep if cfg.get("bin") else "") + os.environ.get("PATH", "")
    env = Environment(ENV=ev, tools=["mingw"] if os.name == "nt" else ["default"])
    env.Replace(CC="gcc", CXX="g++", AR="ar", RANLIB="ranlib",
                LINK="g++" if has_cxx else "gcc")
    env.Append(CCFLAGS=g["ccflags"], CFLAGS=g["cflags"], CXXFLAGS=g["cxxflags"],
               LINKFLAGS=g["linkflags"], ASFLAGS=g["asflags"])
    env.Append(CPPPATH=cfg["include_dirs"], CPPDEFINES=p["defines"])
    syn = "-masm=intel " if p["asm_syntax"] == "intel" else ""
    com = "-fverbose-asm " if p["asm_comments"] else ""
    for u in units:
        o = os.path.join(bd, "obj", u["stem"])
        if u["lang"] == "rc":
            if os.name == "nt":
                objs += env.RES(o, u["src"])
            continue
        if p["via_asm"]:
            comp, std = ("$CC", "$CFLAGS") if u["lang"] == "c" else ("$CXX", "$CXXFLAGS")
            a = env.Command(os.path.join(bd, "asm", u["stem"] + ".s"), u["src"],
                            comp + " -S " + syn + com + std + " $CCFLAGS $_CCCOMCOM -o $TARGET $SOURCE")
            env.Depends(a, cfg["headers"])
            asm_nodes += a
            objs += env.Command(o + ".o", a, "$CC -c -x assembler $ASFLAGS -o $TARGET $SOURCE")
        else:
            objs += env.Object(target=o, source=u["src"])

env.Append(LIBS=p["libs"], LIBPATH=p["lib_dirs"])
if env["CC"] != "cl" and cfg["toolchain"] == "msvc":
    env.Append(CPPPATH=cfg["include_dirs"], CPPDEFINES=p["defines"])

target = os.path.join(bd, p["name"])
out = {"program": env.Program, "static": env.StaticLibrary, "shared": env.SharedLibrary}[p["kind"]](target, objs)
Alias("asm", asm_nodes) if asm_nodes else None
Alias("obj", objs)
Default(out)
'''


# ----------------------------------------------------------------------
def _resolve_toolchain(toolchain, sdk_version, min_sdk, min_gcc, via_asm, gcc_path):
    """-> dict con kind (gnu|msvc), bin, sdk."""
    mingw = tc.find_w64devkit(min_gcc)
    gcc = tc.find_gcc()
    sdks = tc.find_windows_sdks(min_sdk)
    t = toolchain

    if gcc_path:  # carpeta bin de un gcc propio
        return {"kind": "gnu", "bin": str(gcc_path), "label": f"gcc en {gcc_path}"}
    if t == "auto":
        if mingw:
            t = "w64devkit"
        elif gcc:
            t = "gcc"
        elif sdks and not via_asm:
            t = "msvc"
        else:
            raise BuildError("No hay w64devkit ni gcc. Define W64DEVKIT_HOME o usa gcc_path=.")
    if t == "w64devkit":
        if not mingw:
            raise BuildError("No se encontró w64devkit con GCC >= "
                             + ".".join(map(str, min_gcc)) + " (W64DEVKIT_HOME / PATH).")
        return {"kind": "gnu", "bin": str(mingw.bin), "label": f"w64devkit GCC {mingw.version_str}"}
    if t == "gcc":
        if not gcc:
            raise BuildError("No hay gcc/g++ en el PATH.")
        return {"kind": "gnu", "bin": "", "label": f"gcc {'.'.join(map(str, gcc.version))}"}
    if t == "msvc":
        if via_asm:
            raise BuildError("El pipeline ASM necesita gcc. Usa via_asm=False para MSVC.")
        v = sdk_version or (sdks[0].version if sdks else None)
        if not v or tc.parse_version(v) < min_sdk:
            raise BuildError("No hay Windows SDK >= " + ".".join(map(str, min_sdk)))
        return {"kind": "msvc", "sdk": v, "label": f"MSVC + SDK {v}"}
    raise BuildError(f"toolchain desconocido: {toolchain!r}")


def _run(project: Project, stage, toolchain, sdk_version, min_sdk, min_gcc,
         jobs, clean, scons_args, verbose, gcc_path):
    try:
        import SCons  # noqa: F401
    except ImportError as e:
        raise BuildError("SCons no está instalado: pip install scons") from e
    if project.kind not in ("program", "static", "shared"):
        raise BuildError(f"kind inválido: {project.kind!r}")
    if project.asm_syntax not in ("intel", "att"):
        raise BuildError("asm_syntax debe ser 'intel' o 'att'")

    units, headers, incs = project.resolve()
    use_asm = project.via_asm
    if use_asm and project.lto:
        print("[cpp_c] aviso: LTO no es compatible con el paso por ASM; se desactiva ASM.")
        use_asm = False
        project.via_asm = False
    info = _resolve_toolchain(toolchain, sdk_version, min_sdk, min_gcc, use_asm, gcc_path)
    has_cxx = any(u["lang"] == "cxx" for u in units)

    cfg = {"project": asdict(project), "units": units, "headers": headers,
           "include_dirs": incs,
           "toolchain": "msvc" if info["kind"] == "msvc" else "gnu"}
    if info["kind"] == "msvc":
        cfg["sdk"] = info["sdk"]
    else:
        cfg["bin"] = info["bin"]
        cfg["gnu"] = _gnu_flags(project, has_cxx, use_asm)

    root = Path(project.root).resolve()
    work = root / ".cpp_c"
    work.mkdir(exist_ok=True)
    cfg_path = work / "config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (root / "SConstruct.cpp_c").write_text(SCONSTRUCT, encoding="utf-8")

    cmd = [sys.executable, "-m", "SCons", "-f", "SConstruct.cpp_c",
           f"--cpp-c-config={cfg_path}", f"-j{jobs or os.cpu_count() or 1}"]
    if not verbose:
        cmd.append("-Q")
    if clean:
        cmd.append("-c")
    cmd += list(scons_args)
    if stage in ("asm", "obj"):
        cmd.append(stage)

    print(f"[cpp_c] {info['label']} | {len(units)} fuentes, {len(headers)} headers")
    if subprocess.run(cmd, cwd=root).returncode != 0:
        raise BuildError("SCons falló")
    return root, units, info


def build(project: Project, toolchain: str = "auto", sdk_version: Optional[str] = None,
          min_sdk: tuple = tc.MIN_SDK, min_gcc: tuple = tc.MIN_GCC,
          jobs: Optional[int] = None, clean: bool = False, stage: str = "link",
          scons_args: Sequence[str] = (), verbose: bool = False,
          gcc_path: Optional[str] = None) -> Path:
    """Compila y devuelve el binario. stage: 'asm' | 'obj' | 'link'."""
    root, units, info = _run(project, stage, toolchain, sdk_version, min_sdk, min_gcc,
                             jobs, clean, scons_args, verbose, gcc_path)
    win = os.name == "nt"
    if project.kind == "program":
        n = project.name + (".exe" if win else "")
    elif project.kind == "shared":
        n = project.name + ".dll" if win else f"lib{project.name}.so"
    else:
        n = project.name + ".lib" if info["kind"] == "msvc" else f"lib{project.name}.a"
    return root / project.build_dir / n


def to_asm(project: Project, **kw) -> list[Path]:
    """Solo genera los .s (ensamblador) de todos los .c/.cpp."""
    project.via_asm = True
    kw.pop("stage", None)
    root, units, _ = _run(project, "asm", kw.pop("toolchain", "auto"), kw.pop("sdk_version", None),
                          kw.pop("min_sdk", tc.MIN_SDK), kw.pop("min_gcc", tc.MIN_GCC),
                          kw.pop("jobs", None), kw.pop("clean", False), kw.pop("scons_args", ()),
                          kw.pop("verbose", False), kw.pop("gcc_path", None))
    return [root / project.build_dir / "asm" / (u["stem"] + ".s") for u in units if u["lang"] != "rc"]


def check_headers(project: Project, toolchain: str = "auto", min_gcc: tuple = tc.MIN_GCC,
                  gcc_path: Optional[str] = None) -> dict:
    """Revisa la sintaxis de cada .h/.hpp por separado. -> {header: None | error}."""
    _, headers, incs = project.resolve()
    info = _resolve_toolchain(toolchain, None, tc.MIN_SDK, min_gcc, True, gcc_path)
    env = dict(os.environ)
    if info.get("bin"):
        env["PATH"] = info["bin"] + os.pathsep + env.get("PATH", "")
    root = Path(project.root).resolve()
    inc = [f"-I{i}" for i in incs]
    inc += [f"-D{d}" for d in project.defines]
    out = {}
    for h in headers:
        err = None
        for lang, std in (("c", f"-std={project.c_std}"), ("c++", f"-std={project.cxx_std}")):
            r = subprocess.run(["gcc", "-fsyntax-only", "-x", lang, std, *inc, h],
                               cwd=root, env=env, capture_output=True, text=True)
            if r.returncode == 0:
                err = None
                break
            err = r.stderr.strip()
        out[h] = err
    return out
