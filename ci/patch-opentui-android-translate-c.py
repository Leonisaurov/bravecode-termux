#!/usr/bin/env python3
"""Parchea `packages/native/build.zig` de OpenTUI para poder compilar Android.

Tres problemas, los tres verificados en CI y reproducidos en local con zig
0.16.0 + NDK r29:

 1. Los pasos `addTranslateC` (miniaudio y yoga) NO heredan el `--libc` que
    recibe `zig build`, así que no ven los headers de Bionic y el build muere en
    `src/vendor/miniaudio/miniaudio.h:3883: 'pthread.h' not found`.
 2. Al apuntarlos al NDK aparece el segundo fallo: los headers de Bionic usan
    los especificadores `_Nullable`/`_Nonnull` de clang, que translate-c no
    acepta sobre arrays (`sys/time.h:47: error: nullability specifier cannot be
    applied to non-pointer type 'const struct timeval [2]'`).
 3. El link de Linux pide `dl` y `pthread`, que en Bionic no existen, y Zig no
    encuentra `m` porque el `--libc` no aporta rutas de librerías
    (`error: unable to find dynamic system library 'm' ... searched paths: none`).
    Comprobado en local: `-L <ndk>/.../aarch64-linux-android/24` lo resuelve.

Parche (sólo cuando el target es Android):
  * los dos translate-c reciben `-Dndk-include` / `-Dndk-arch-include` y las
    tres macros de nullability anuladas;
  * el módulo recibe `-Dndk-lib` como library path y se linkea sólo `m`
    (nada de `dl`/`pthread`).

Opciones del build y no variables de entorno porque en Zig 0.16
`std.process.getEnvVarOwned` (y `std.posix.getenv`) no existen. Las opciones se
leen una sola vez, cacheándolas: `b.option` paniquea con
"Option 'ndk-include' declared twice" y estas funciones se llaman una vez por
cada paso/módulo.

Es idempotente, actualiza versiones anteriores del propio parche y falla en vez
de compilar a ciegas si no encuentra las anclas.

Uso: ci/patch-opentui-android-translate-c.py <ruta-a-build.zig>
"""
import pathlib
import re
import sys

BEGIN = "// [bravecode-termux] BEGIN"
END = "// [bravecode-termux] END"

# --- transformación A: translate-c con headers del NDK ---------------------
ANCHOR_A = (
    '    yoga_translate.addIncludePath(yoga_dep.path(""));\n'
    '    module.addImport("yoga", yoga_translate.createModule());\n'
    "}\n"
)
ANCHOR_A_PATCHED = (
    '    yoga_translate.addIncludePath(yoga_dep.path(""));\n'
    '    module.addImport("yoga", yoga_translate.createModule());\n'
    "\n"
    "    if (target.result.abi == .android) {\n"
    "        addAndroidNdkIncludes(b, miniaudio_translate);\n"
    "        addAndroidNdkIncludes(b, yoga_translate);\n"
    "    }\n"
    "}\n"
)

# --- transformación B: link de sistema en Android --------------------------
ANCHOR_B = (
    "        .linux => {\n"
    '            module.linkSystemLibrary("dl", .{});\n'
    '            module.linkSystemLibrary("pthread", .{});\n'
    '            module.linkSystemLibrary("m", .{});\n'
    "        },\n"
)
ANCHOR_B_PATCHED = (
    "        .linux => {\n"
    "            if (target.result.abi == .android) {\n"
    "                addAndroidNdkLibraryPath(b, module);\n"
    '                module.linkSystemLibrary("m", .{});\n'
    "            } else {\n"
    '                module.linkSystemLibrary("dl", .{});\n'
    '                module.linkSystemLibrary("pthread", .{});\n'
    '                module.linkSystemLibrary("m", .{});\n'
    "            }\n"
    "        },\n"
)

HELPER = f"""
{BEGIN}
// Ajustes para compilar OpenTUI en Android/Bionic. Generado por
// ci/patch-opentui-android-translate-c.py: no editar a mano.
//
// - translate-c no hereda el `--libc` de `zig build` -> sin include dirs del NDK
//   falla con 'pthread.h'/'math.h' not found, y con ellos hay que anular las
//   macros de nullability de clang que translate-c no acepta sobre arrays.
// - El link de Linux pide dl/pthread (inexistentes en Bionic) y las libs del
//   NDK no están en las rutas por defecto -> library path explícito.
// - Las opciones se leen una sola vez: `b.option` paniquea si se declara dos
//   veces y estas funciones se llaman una vez por paso/módulo.
var brave_ndk_include_paths: ?[][]const u8 = null;
var brave_ndk_lib_dir: ?[]const u8 = null;

fn addAndroidNdkIncludes(b: *std.Build, step: *std.Build.Step.TranslateC) void {{
    if (brave_ndk_include_paths == null) {{
        var list: std.ArrayList([]const u8) = .empty;
        for ([_][]const u8{{ "ndk-include", "ndk-arch-include" }}) |name| {{
            if (b.option([]const u8, name, "Include dir del NDK para translate-c en Android")) |value| {{
                if (value.len > 0) list.append(b.allocator, value) catch @panic("OOM");
            }}
        }}
        brave_ndk_include_paths = list.toOwnedSlice(b.allocator) catch @panic("OOM");
    }}
    for (brave_ndk_include_paths.?) |dir| {{
        step.addSystemIncludePath(.{{ .cwd_relative = dir }});
    }}
    step.defineCMacroRaw("_Nullable=");
    step.defineCMacroRaw("_Nonnull=");
    step.defineCMacroRaw("_Null_unspecified=");
}}

fn addAndroidNdkLibraryPath(b: *std.Build, module: *std.Build.Module) void {{
    if (brave_ndk_lib_dir == null) {{
        brave_ndk_lib_dir = b.option([]const u8, "ndk-lib", "Directorio de librerías del NDK para el link en Android") orelse "";
    }}
    if (brave_ndk_lib_dir.?.len > 0) {{
        module.addLibraryPath(.{{ .cwd_relative = brave_ndk_lib_dir.? }});
    }}
}}
{END}
"""

_HELPER_RE = re.compile(
    re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n", re.DOTALL
)
# Formato de las versiones 1-3 del parche (sin marcadores BEGIN/END).
_LEGACY_HELPER_RE = re.compile(
    r"\n// \[bravecode-termux\](?! BEGIN).*?\n}\n", re.DOTALL
)


def _strip_previous(text: str) -> tuple[str, bool]:
    cleaned, n = _HELPER_RE.subn("", text)
    if n:
        return cleaned, True
    cleaned, n = _LEGACY_HELPER_RE.subn("\n", text)
    return cleaned, bool(n)


def _apply(text: str, anchor: str, patched: str, label: str, path: pathlib.Path) -> str:
    if patched in text:
        return text
    if text.count(anchor) != 1:
        raise SystemExit(
            f"error: no encuentro el ancla '{label}' en {path} (¿otra versión de OpenTUI?). "
            f"Ocurrencias: {text.count(anchor)}"
        )
    return text.replace(anchor, patched)


def patch(path: pathlib.Path) -> str:
    text = path.read_text()
    was_patched = BEGIN in text or "[bravecode-termux]" in text

    cleaned, replaced_helper = _strip_previous(text)
    cleaned = _apply(cleaned, ANCHOR_A, ANCHOR_A_PATCHED, "translate-c", path)
    cleaned = _apply(cleaned, ANCHOR_B, ANCHOR_B_PATCHED, "link de sistema", path)

    result = cleaned.rstrip("\n") + "\n" + HELPER.lstrip("\n")
    path.write_text(result)

    if not was_patched:
        return "parcheado"
    if replaced_helper:
        return "actualizado a la versión actual del parche"
    return "anclas completadas"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    target = pathlib.Path(argv[1])
    if not target.exists():
        print(f"error: no existe {target}", file=sys.stderr)
        return 2
    print(f"{target}: {patch(target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
