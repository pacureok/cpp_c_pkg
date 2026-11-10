"""cpp_c: lee .c/.cpp/.h, los pasa a ASM y los compila con SCons (sin SDKs).

    import cpp_c
    p = cpp_c.Project.from_dir("src", "juego", warnings="extra")
    cpp_c.to_asm(p)          # solo ensamblador
    cpp_c.build(p)           # .c/.cpp -> .s -> .o -> .exe
"""
from .toolchains import (MIN_SDK, MIN_GCC, SDK, MinGW, find_windows_sdks,
                         find_w64devkit, find_gcc, detect)
from .builder import Project, build, to_asm, check_headers, BuildError

__all__ = ["MIN_SDK", "MIN_GCC", "SDK", "MinGW", "find_windows_sdks", "find_w64devkit",
           "find_gcc", "detect", "Project", "build", "to_asm", "check_headers", "BuildError"]
__version__ = "0.2.0"
