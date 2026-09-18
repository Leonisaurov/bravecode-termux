#!/usr/bin/env python3
"""Tests del parche del build.zig de OpenTUI para Android.

Contexto: en `packages/native/build.zig`, los pasos `addTranslateC` (miniaudio y
yoga) no heredan el `--libc` que el script de build le pasa a `zig build`, así
que Zig no encuentra los headers de Bionic (`pthread.h`, `math.h`) y el build de
Android falla en `translate-c`. Además, al apuntarlos al NDK aparece
`sys/time.h: error: nullability specifier cannot be applied to non-pointer type`
porque los headers de Bionic usan `_Nullable`/`_Nonnull` de clang.

El parche inserta, sólo cuando el target es Android, los include dirs del NDK
(pasados como `-Dndk-include` / `-Dndk-arch-include`) y anula esas tres macros.
Es idempotente, actualiza versiones previas del propio parche y falla en vez de
seguir adelante si no encuentra el ancla.

Nota: se usan `b.option` y no variables de entorno porque en Zig 0.16
`std.process.getEnvVarOwned` ya no existe (falló así en CI).
"""
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATCHER = ROOT / "ci" / "patch-opentui-android-translate-c.py"
REAL_BUILD_ZIG = ROOT / "build" / "opentui-0.5.9" / "packages" / "native" / "build.zig"

FIXTURE = """\
fn addTranslatedCImports(
    b: *std.Build,
    module: *std.Build.Module,
    optimize: std.builtin.OptimizeMode,
    target: std.Build.ResolvedTarget,
) void {
    const miniaudio_translate = b.addTranslateC(.{
        .root_source_file = b.path("src/vendor/miniaudio/miniaudio.h"),
        .target = target,
        .optimize = optimize,
    });
    const yoga_dep = b.dependency("yoga", .{});
    const yoga_translate = b.addTranslateC(.{
        .root_source_file = yoga_dep.path("yoga/Yoga.h"),
        .target = target,
        .optimize = optimize,
    });
    yoga_translate.addIncludePath(yoga_dep.path(""));
    module.addImport("yoga", yoga_translate.createModule());
}
"""

# Versión anterior del parche (leía variables de entorno): debe ser reemplazada.
V1_HELPER = (
    "\n// [bravecode-termux] versión vieja del parche\n"
    "fn addAndroidNdkIncludes(b: *std.Build, step: *std.Build.Step.TranslateC) void {\n"
    '    const value = std.process.getEnvVarOwned(b.allocator, "BRAVECODE_NDK_INCLUDE") catch return;\n'
    "    step.addSystemIncludePath(.{ .cwd_relative = value });\n"
    "}\n"
)


def run_patcher(path):
    return subprocess.run([sys.executable, str(PATCHER), str(path)], capture_output=True, text=True)


class PatchTranslateC(unittest.TestCase):
    def test_patcher_exists(self):
        """RED inicial: el parcheador debe existir."""
        self.assertTrue(PATCHER.exists(), f"falta {PATCHER}")

    def test_inserts_ndk_includes_and_nullability_macros(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / "build.zig"
            f.write_text(FIXTURE)
            p = run_patcher(f)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            out = f.read_text()
            self.assertIn('"ndk-include"', out)
            self.assertIn('"ndk-arch-include"', out)
            self.assertIn("b.option", out)
            self.assertIn("addSystemIncludePath", out)
            self.assertIn('_Nullable=', out)
            self.assertIn('_Nonnull=', out)
            self.assertIn("abi == .android", out)
            self.assertIn("addAndroidNdkIncludes(b, miniaudio_translate)", out)
            self.assertIn("addAndroidNdkIncludes(b, yoga_translate)", out)
            self.assertNotIn("getEnvVarOwned", out, "Zig 0.16 no tiene esa API")

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / "build.zig"
            f.write_text(FIXTURE)
            run_patcher(f)
            once = f.read_text()
            p = run_patcher(f)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(once, f.read_text(), "el segundo parche cambió el archivo")

    def test_upgrades_previous_patch_version(self):
        """El caché de CI puede traer un árbol con el parche viejo."""
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / "build.zig"
            f.write_text(FIXTURE.replace("}\n", "}\n", 1) + V1_HELPER)
            p = run_patcher(f)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            out = f.read_text()
            self.assertNotIn("getEnvVarOwned", out)
            self.assertEqual(out.count("addAndroidNdkIncludes"), 3, "helper o llamadas duplicadas")
            # y sigue siendo idempotente tras la actualización
            run_patcher(f)
            self.assertEqual(out, f.read_text())

    def test_fails_when_anchor_missing(self):
        """Si build.zig cambia de forma, hay que fallar (no compilar a ciegas)."""
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / "build.zig"
            f.write_text("fn otra_cosa() void {}\n")
            p = run_patcher(f)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("ancla", (p.stdout + p.stderr).lower())

    def test_real_build_zig_when_cloned(self):
        if not REAL_BUILD_ZIG.exists():
            self.skipTest("fuente de OpenTUI no clonada en build/")
        before = REAL_BUILD_ZIG.read_text()
        already = "[bravecode-termux]" in before
        p = run_patcher(REAL_BUILD_ZIG)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        after = REAL_BUILD_ZIG.read_text()
        self.assertIn("addAndroidNdkIncludes", after)
        self.assertNotIn("getEnvVarOwned", after)
        run_patcher(REAL_BUILD_ZIG)
        self.assertEqual(after, REAL_BUILD_ZIG.read_text())
        self.assertEqual(after.count("fn addAndroidNdkIncludes"), 1)
        if not already:
            self.assertNotEqual(before, after, "el parche no cambió el build.zig real")


if __name__ == "__main__":
    unittest.main(verbosity=2)
