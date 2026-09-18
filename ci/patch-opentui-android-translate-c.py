#!/usr/bin/env python3
"""Parchea `packages/native/build.zig` de OpenTUI para poder compilar Android.

Problema (verificado en CI y localmente con zig 0.16.0):

  * Los pasos `addTranslateC` (miniaudio y yoga) NO heredan el `--libc` que
    recibe `zig build`, así que no ven los headers de Bionic y el build muere en
    `src/vendor/miniaudio/miniaudio.h:3883: 'pthread.h' not found`.
  * Apuntándolos al NDK aparece otro fallo: los headers de Bionic usan los
    especificadores de clang `_Nullable`/`_Nonnull`, que translate-c no sabe
    aplicar a arrays (`sys/time.h:47: error: nullability specifier cannot be
    applied to non-pointer type 'const struct timeval [2]'`).

Parche: sólo cuando el target es Android, los dos pasos translate-c reciben dos
include dirs del NDK por opciones del build (`-Dndk-include`, `-Dndk-arch-include`,
las resuelve ci/build-opentui-android.sh) y se anulan las tres macros de
nullability. Se usan `b.option` y no variables de entorno porque en Zig 0.16
`std.process.getEnvVarOwned` ya no existe.

El parche es idempotente y además actualiza versiones anteriores del propio
parche (útil con el caché de CI). Si no encuentra el ancla, sale con error en
vez de compilar a ciegas con otra versión de OpenTUI.

Uso: ci/patch-opentui-android-translate-c.py <ruta-a-build.zig>
"""
import pathlib
import re
import sys

MARKER = "[bravecode-termux]"
HELPER_START = "// " + MARKER

ANCHOR = (
    '    yoga_translate.addIncludePath(yoga_dep.path(""));\n'
    '    module.addImport("yoga", yoga_translate.createModule());\n'
    "}\n"
)
ANCHOR_PATCHED = (
    '    yoga_translate.addIncludePath(yoga_dep.path(""));\n'
    '    module.addImport("yoga", yoga_translate.createModule());\n'
    "\n"
    "    if (target.result.abi == .android) {\n"
    "        addAndroidNdkIncludes(b, miniaudio_translate);\n"
    "        addAndroidNdkIncludes(b, yoga_translate);\n"
    "    }\n"
    "}\n"
)
HELPER = (
    "\n"
    "// " + MARKER + " Los pasos translate-c no heredan el `--libc` de `zig build`,\n"
    "// así que en Android no ven los headers de Bionic (`pthread.h`, `math.h`) y el\n"
    "// build falla. Se les añaden los include dirs del NDK (-Dndk-include,\n"
    "// -Dndk-arch-include) y se anulan las macros de nullability de clang, que\n"
    "// translate-c no acepta sobre arrays (`sys/time.h`).\n"
    "// Las opciones se leen una sola vez: `b.option` paniquea con\n"
    "// \"Option 'ndk-include' declared twice\" porque esta función se llama una vez\n"
    "// por cada paso translate-c (miniaudio y yoga).\n"
    "// Ver ci/build-opentui-android.sh y ci/patch-opentui-android-translate-c.py.\n"
    "var brave_ndk_include_paths: ?[][]const u8 = null;\n"
    "\n"
    "fn addAndroidNdkIncludes(b: *std.Build, step: *std.Build.Step.TranslateC) void {\n"
    "    if (brave_ndk_include_paths == null) {\n"
    "        var list: std.ArrayList([]const u8) = .empty;\n"
    "        for ([_][]const u8{ \"ndk-include\", \"ndk-arch-include\" }) |name| {\n"
    "            if (b.option([]const u8, name, \"Include dir del NDK para translate-c en Android\")) |value| {\n"
    "                if (value.len > 0) list.append(b.allocator, value) catch @panic(\"OOM\");\n"
    "            }\n"
    "        }\n"
    "        brave_ndk_include_paths = list.toOwnedSlice(b.allocator) catch @panic(\"OOM\");\n"
    "    }\n"
    "    for (brave_ndk_include_paths.?) |dir| {\n"
    "        step.addSystemIncludePath(.{ .cwd_relative = dir });\n"
    "    }\n"
    '    step.defineCMacroRaw("_Nullable=");\n'
    '    step.defineCMacroRaw("_Nonnull=");\n'
    '    step.defineCMacroRaw("_Null_unspecified=");\n'
    "}\n"
)

# Bloque helper completo (de la versión actual o de anteriores), para poder
# reemplazarlo al actualizar el parche.
_HELPER_BLOCK_RE = re.compile(
    r"\n// " + re.escape(MARKER) + r".*?\n}\n", re.DOTALL
)


def patch(path: pathlib.Path) -> str:
    text = path.read_text()
    started = HELPER_START not in text

    # 1. quitar cualquier versión previa del helper (auto-actualización)
    cleaned, n_removed = _HELPER_BLOCK_RE.subn("\n", text)

    # 2. insertar la llamada dentro de addTranslatedCImports
    if ANCHOR_PATCHED in cleaned:
        call_inserted = False
    elif cleaned.count(ANCHOR) == 1:
        cleaned = cleaned.replace(ANCHOR, ANCHOR_PATCHED)
        call_inserted = True
    else:
        raise SystemExit(
            f"error: no encuentro el ancla esperada en {path} (¿otra versión de OpenTUI?). "
            f"Ancla original: {cleaned.count(ANCHOR)}, ya parcheada: {cleaned.count(ANCHOR_PATCHED)}"
        )

    # 3. añadir el helper
    result = cleaned.rstrip("\n") + "\n" + HELPER.lstrip("\n")
    path.write_text(result)

    if started:
        return "parcheado"
    if n_removed:
        return "actualizado a la versión actual del parche"
    return "ya parcheado" if not call_inserted else "parcheado (helper ya presente)"


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
