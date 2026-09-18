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

Parche: sólo cuando el target es Android, los dos pasos translate-c reciben los
include dirs del NDK desde las variables de entorno `BRAVECODE_NDK_INCLUDE` y
`BRAVECODE_NDK_ARCH_INCLUDE` (las resuelve ci/build-opentui-android.sh) y se
anulan las tres macros de nullability.

Es idempotente y, si no encuentra el ancla, sale con error en vez de compilar a
ciegas con otra versión de OpenTUI.

Uso: ci/patch-opentui-android-translate-c.py <ruta-a-build.zig>
"""
import pathlib
import sys

MARKER = "[bravecode-termux]"
ANCHOR = (
    '    yoga_translate.addIncludePath(yoga_dep.path(""));\n'
    '    module.addImport("yoga", yoga_translate.createModule());\n'
    "}\n"
)
PATCHED_BLOCK = (
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
    "// build falla. Se les añaden los include dirs del NDK pasados por entorno y se\n"
    "// anulan las macros de nullability de clang, que translate-c no acepta sobre\n"
    "// arrays (`sys/time.h`). Ver ci/build-opentui-android.sh.\n"
    "fn addAndroidNdkIncludes(b: *std.Build, step: *std.Build.Step.TranslateC) void {\n"
    '    const env_names = [_][]const u8{ "BRAVECODE_NDK_INCLUDE", "BRAVECODE_NDK_ARCH_INCLUDE" };\n'
    "    for (env_names) |name| {\n"
    '        const value = std.process.getEnvVarOwned(b.allocator, name) catch continue;\n'
    "        if (value.len == 0) continue;\n"
    "        step.addSystemIncludePath(.{ .cwd_relative = value });\n"
    "    }\n"
    '    step.defineCMacroRaw("_Nullable=");\n'
    '    step.defineCMacroRaw("_Nonnull=");\n'
    '    step.defineCMacroRaw("_Null_unspecified=");\n'
    "}\n"
)


def patch(path: pathlib.Path) -> str:
    text = path.read_text()
    if MARKER in text:
        return "ya parcheado"
    if text.count(ANCHOR) != 1:
        raise SystemExit(
            f"error: no encuentro el ancla esperada en {path} (¿otra versión de OpenTUI?). "
            f"Ocurrencias: {text.count(ANCHOR)}"
        )
    patched = text.replace(ANCHOR, PATCHED_BLOCK) + HELPER
    path.write_text(patched)
    return "parcheado"


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
