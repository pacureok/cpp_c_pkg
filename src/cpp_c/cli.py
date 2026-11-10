import argparse
import json
import shlex
from . import detect, Project, build, to_asm, check_headers, BuildError


def _args():
    ap = argparse.ArgumentParser(prog="cpp_c", description="C/C++ -> ASM -> EXE con SCons")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect", help="Muestra los compiladores encontrados")

    b = sub.add_parser("build", help="Compila archivos, carpetas o globs")
    b.add_argument("name")
    b.add_argument("sources", nargs="+", help="archivos, carpetas o globs (src/**/*.cpp)")
    b.add_argument("--stage", default="link", choices=["asm", "obj", "link"])
    b.add_argument("--check-headers", action="store_true")
    b.add_argument("--toolchain", default="auto", choices=["auto", "w64devkit", "gcc", "msvc"])
    b.add_argument("--gcc-path", help="carpeta bin de un gcc propio")
    b.add_argument("--sdk", help="solo MSVC")
    b.add_argument("--kind", default="program", choices=["program", "static", "shared"])
    b.add_argument("--root", default=".")
    b.add_argument("--build-dir", default="build")
    b.add_argument("-I", dest="include_dirs", action="append", default=[])
    b.add_argument("-D", dest="defines", action="append", default=[])
    b.add_argument("-U", dest="undefines", action="append", default=[])
    b.add_argument("--include", dest="force_includes", action="append", default=[])
    b.add_argument("-l", dest="libs", action="append", default=[])
    b.add_argument("-L", dest="lib_dirs", action="append", default=[])
    b.add_argument("--std-c", dest="c_std", default="c17")
    b.add_argument("--std-cxx", dest="cxx_std", default="c++20")
    b.add_argument("-O", dest="optimize", default="2")
    b.add_argument("-g", dest="debug", action="store_true")
    b.add_argument("--warn", dest="warnings", default="all", choices=["none", "all", "extra"])
    b.add_argument("--pedantic", action="store_true")
    b.add_argument("--werror", action="store_true")
    b.add_argument("--march"); b.add_argument("--mtune")
    b.add_argument("--arch", default="x86_64", choices=["x86_64", "x86"])
    b.add_argument("--lto", action="store_true")
    b.add_argument("--sanitize", action="append", default=[])
    b.add_argument("--pthread", dest="threads", action="store_true")
    b.add_argument("--openmp", action="store_true")
    b.add_argument("--no-exceptions", dest="exceptions", action="store_false")
    b.add_argument("--no-rtti", dest="rtti", action="store_false")
    b.add_argument("--no-asm", dest="via_asm", action="store_false", help="compilar directo sin pasar por .s")
    b.add_argument("--asm-syntax", default="intel", choices=["intel", "att"])
    b.add_argument("--asm-comments", action="store_true")
    b.add_argument("--dynamic-runtime", dest="static_runtime", action="store_false")
    b.add_argument("--subsystem", default="console", choices=["console", "windows"])
    b.add_argument("--strip", action="store_true")
    b.add_argument("--map", dest="map_file", action="store_true")
    b.add_argument("--ccflags", default=""); b.add_argument("--cflags", default="")
    b.add_argument("--cxxflags", default=""); b.add_argument("--asflags", default="")
    b.add_argument("--linkflags", default="")
    b.add_argument("-j", dest="jobs", type=int)
    b.add_argument("--clean", action="store_true")
    b.add_argument("-v", dest="verbose", action="store_true")
    return ap.parse_args()


def main():
    a = _args()
    if a.cmd == "detect":
        print(json.dumps(detect(), indent=2))
        return 0
    p = Project(
        name=a.name, sources=a.sources, kind=a.kind, root=a.root, build_dir=a.build_dir,
        include_dirs=a.include_dirs, defines=a.defines, undefines=a.undefines,
        force_includes=a.force_includes, libs=a.libs, lib_dirs=a.lib_dirs,
        c_std=a.c_std, cxx_std=a.cxx_std, optimize=a.optimize, debug=a.debug,
        warnings=a.warnings, pedantic=a.pedantic, werror=a.werror, march=a.march,
        mtune=a.mtune, arch=a.arch, lto=a.lto, sanitize=a.sanitize, threads=a.threads,
        openmp=a.openmp, exceptions=a.exceptions, rtti=a.rtti, via_asm=a.via_asm,
        asm_syntax=a.asm_syntax, asm_comments=a.asm_comments, static_runtime=a.static_runtime,
        subsystem=a.subsystem, strip=a.strip, map_file=a.map_file,
        ccflags=shlex.split(a.ccflags), cflags=shlex.split(a.cflags),
        cxxflags=shlex.split(a.cxxflags), asflags=shlex.split(a.asflags),
        linkflags=shlex.split(a.linkflags),
    )
    kw = dict(toolchain=a.toolchain, gcc_path=a.gcc_path, jobs=a.jobs, verbose=a.verbose)
    try:
        if a.check_headers:
            for h, e in check_headers(p, toolchain=a.toolchain, gcc_path=a.gcc_path).items():
                print(("OK    " if e is None else "ERROR ") + h + ("" if e is None else "\n" + e))
        if a.stage == "asm":
            for s in to_asm(p, **kw):
                print("ASM ->", s)
        else:
            print("OK ->", build(p, sdk_version=a.sdk, clean=a.clean, stage=a.stage, **kw))
    except BuildError as e:
        print("ERROR:", e)
        return 1
    return 0
