# cpp_c

Lee tus `.c`, `.cpp` y `.h`, los pasa a **ensamblador (ASM)**, los ensambla y enlaza,
todo orquestado con **SCons** (dependencia). **No necesita ningún SDK de Windows**:
con **w64devkit** (MinGW-w64) o cualquier `gcc` basta.

    .c / .cpp  --(gcc -S)-->  .s  --(as)-->  .o  --(link)-->  .exe / .dll / .a

## Instalar
    pip install -e .

## Uso
```python
import cpp_c

print(cpp_c.detect())

# lee TODA la carpeta (recursivo): .c .cpp .h .hpp (+ .rc en Windows)
p = cpp_c.Project.from_dir("src", "juego",
        defines=["VERSION=3"], warnings="extra", optimize="3",
        march="native", asm_syntax="intel", asm_comments=True)

cpp_c.check_headers(p)   # revisa la sintaxis de cada .h por separado
cpp_c.to_asm(p)          # solo genera build/asm/*.s
cpp_c.build(p)           # build/juego.exe
```

## Flags principales (campos de `Project` / opciones del CLI)
| Área | Campos |
|---|---|
| Preprocesador | `include_dirs`, `auto_include`, `defines`, `undefines`, `force_includes` |
| Lenguaje | `c_std`, `cxx_std`, `exceptions`, `rtti` |
| Optimización | `optimize` (0-3,s,z,fast,g), `debug`, `march`, `mtune`, `lto`, `arch` (x86_64/x86) |
| Diagnóstico | `warnings` (none/all/extra), `pedantic`, `werror`, `sanitize` |
| Paralelismo | `threads`, `openmp` |
| ASM | `via_asm`, `asm_syntax` (intel/att), `asm_comments` |
| Enlace | `libs`, `lib_dirs`, `static_runtime`, `subsystem` (console/windows), `strip`, `map_file` |
| Libres | `ccflags`, `cflags`, `cxxflags`, `asflags`, `linkflags` |

CLI:
    python -m cpp_c detect
    python -m cpp_c build juego src --stage asm
    python -m cpp_c build juego src -O3 --warn extra --pedantic --march native --strip
    python -m cpp_c build juego src --no-asm --cxxflags=-fno-exceptions
    python -m cpp_c build juego src --check-headers --toolchain w64devkit

## Toolchains
`toolchain="auto"` prueba: w64devkit (GCC >= 16.1.0, `min_gcc=` configurable; `W64DEVKIT_HOME`) -> gcc del PATH
-> MSVC + Windows SDK >= 10.0.20348.0 (solo con `via_asm=False`).

## Límites
- `lto=True` desactiva el paso por ASM (el LTO no genera ensamblador real).
- El pipeline ASM requiere gcc; MSVC compila directo.
- `-fsanitize` y `arch="x86"` dependen de lo que incluya tu w64devkit.
