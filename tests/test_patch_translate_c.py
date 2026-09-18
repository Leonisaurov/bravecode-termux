#!/usr/bin/env python3
"""Tests del parche del build.zig de OpenTUI para Android.

Tres fallos reales del CI, los tres reproducidos en local antes de arreglarlos:

 1. `addTranslateC` no hereda el `--libc` de `zig build` -> headers de Bionic
    ausentes (`miniaudio.h:3883: 'pthread.h' not found`).
 2. Al apuntarlos al NDK -> `sys/time.h:47: error: nullability specifier cannot
    be applied to non-pointer type` (clang `_Nullable` sobre arrays).
 3. El link pide `dl`/`pthread` (no existen en Bionic) y no encuentra `m`
    (`searched paths: none`); con `-L <ndk lib dir>` sí.

El parche (sólo en Android) añade los include dirs del NDK y las macros de
nullability a los translate-c, y el library path del NDK + sólo `m` al link.
Es idempotente, actualiza versiones previas del parche y falla si cambian las
anclas. Usa `b.option` (Zig 0.16 no tiene `std.process.getEnvVarOwned` ni
`std.posix.getenv`) y cachea las lecturas (`b.option` paniquea si se declara dos
veces y las funciones se llaman una vez por paso/módulo).
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATCHER = ROOT / "ci" / "patch-opentui-android-translate-c.py"
REAL_BUILD_ZIG = ROOT / "build" / "opentui-0.5.9" / "packages" / "native" / "build.zig"


def find_zig():
    """El helper está escrito para zig 0.16 (el que usa el CI)."""
    local = pathlib.Path.home() / ".local" / "opt" / "zig-0.16.0" / "bin" / "zig"
    if local.exists():
        return str(local)
    return shutil.which("zig")


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

fn addNativeAudioDependencies(
    b: *std.Build,
    module: *std.Build.Module,
    target: std.Build.ResolvedTarget,
    macos_sdk_path: ?[]const u8,
) void {
    _ = macos_sdk_path;

    switch (target.result.os.tag) {
        .macos => {},
        .linux => {
            module.linkSystemLibrary("dl", .{});
            module.linkSystemLibrary("pthread", .{});
            module.linkSystemLibrary("m", .{});
        },
        else => {},
    }
}

const LIB_NAME = "opentui";
const ROOT_SOURCE_FILE = "src/opentui.zig";

fn applyDependencies(
    b: *std.Build,
    module: *std.Build.Module,
    optimize: std.builtin.OptimizeMode,
    target: std.Build.ResolvedTarget,
    build_options: *std.Build.Step.Options,
) void {
    _ = b;
    _ = module;
    _ = optimize;
    _ = target;
    _ = build_options;
}

fn buildTarget(
    b: *std.Build,
    target: std.Build.ResolvedTarget,
    optimize: std.builtin.OptimizeMode,
    build_options: *std.Build.Step.Options,
) !void {
    const module = b.createModule(.{
        .root_source_file = b.path(ROOT_SOURCE_FILE),
        .target = target,
        .optimize = optimize,
    });

    applyDependencies(b, module, optimize, target, build_options);

    const lib = b.addLibrary(.{
        .name = LIB_NAME,
        .root_module = module,
        .linkage = .dynamic,
    });
    _ = lib;
}
"""

# Versión anterior del parche (leía variables de entorno): debe reemplazarse.
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
            self.assertIn('"ndk-lib"', out)
            self.assertIn('"bionic-compat-c"', out)
            self.assertIn("addAndroidBionicCompat(b, module)", out)
            self.assertIn("addCSourceFile", out)
            self.assertIn("b.option", out)
            self.assertIn("brave_ndk_include_paths", out, "las opciones deben leerse una sola vez")
            self.assertIn("if (brave_ndk_include_paths == null)", out)
            self.assertIn("addSystemIncludePath", out)
            self.assertIn("addLibraryPath", out)
            self.assertIn('_Nullable=', out)
            self.assertIn('_Nonnull=', out)
            self.assertIn("abi == .android", out)
            self.assertIn("addAndroidNdkIncludes(b, miniaudio_translate)", out)
            self.assertIn("addAndroidNdkIncludes(b, yoga_translate)", out)
            self.assertIn("addAndroidNdkLibraryPath(b, module)", out)
            self.assertNotIn("getEnvVarOwned", out, "Zig 0.16 no tiene esa API")
            # Linux sigue linkeando dl/pthread en la rama no-Android
            self.assertIn('module.linkSystemLibrary("dl", .{})', out)
            self.assertIn('module.linkSystemLibrary("pthread", .{})', out)

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
            f.write_text(FIXTURE + V1_HELPER)
            p = run_patcher(f)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            out = f.read_text()
            self.assertNotIn("getEnvVarOwned", out)
            self.assertEqual(out.count("fn addAndroidNdkIncludes"), 1, "helper duplicado")
            self.assertEqual(out.count("addAndroidNdkIncludes(b,"), 2, "llamadas duplicadas")
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

    def test_fails_when_only_link_anchor_missing(self):
        """Cada ancla se verifica por separado."""
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / "build.zig"
            f.write_text(FIXTURE.replace('            module.linkSystemLibrary("dl", .{});\n', ""))
            p = run_patcher(f)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("link de sistema", p.stdout + p.stderr)

    @unittest.skipUnless(find_zig(), "zig no disponible")
    def test_helper_compiles_and_reads_options_once(self):
        """Reproduce los fallos de CI en local (en segundos): el helper debe
        compilar con zig y llamarse varias veces sin 'declared twice'."""
        zig = find_zig()
        build_main = (
            "\nconst std = @import(\"std\");\n"
            "pub fn build(b: *std.Build) void {\n"
            "    const target = b.standardTargetOptions(.{});\n"
            "    const step = b.addTranslateC(.{\n"
            "        .root_source_file = b.path(\"foo.h\"),\n"
            "        .target = target,\n"
            "        .optimize = .Debug,\n"
            "    });\n"
            "    addAndroidNdkIncludes(b, step);\n"
            "    addAndroidNdkIncludes(b, step);\n"
            "    const mod = b.createModule(.{\n"
            "        .root_source_file = b.path(\"foo.c\"),\n"
            "        .target = target,\n"
            "        .optimize = .Debug,\n"
            "    });\n"
            "    addAndroidNdkLibraryPath(b, mod);\n"
            "    addAndroidNdkLibraryPath(b, mod);\n"
            "    addAndroidBionicCompat(b, mod);\n"
            "    addAndroidBionicCompat(b, mod);\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            (tmp_path / "foo.h").write_text("int f(void);\n")
            (tmp_path / "foo.c").write_text("int f(void) { return 1; }\n")
            f = tmp_path / "build.zig"
            f.write_text(FIXTURE)
            self.assertEqual(run_patcher(f).returncode, 0)
            f.write_text(f.read_text() + build_main)
            p = subprocess.run(
                [
                    zig,
                    "build",
                    "-Dndk-include=/tmp/include",
                    "-Dndk-arch-include=/tmp/arch",
                    "-Dndk-lib=/tmp/lib",
                    f"-Dbionic-compat-c={tmp_path / 'foo.c'}",
                ],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=300,
            )
            self.assertNotIn("declared twice", p.stderr + p.stdout)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_real_build_zig_when_cloned(self):
        if not REAL_BUILD_ZIG.exists():
            self.skipTest("fuente de OpenTUI no clonada en build/")
        before = REAL_BUILD_ZIG.read_text()
        already = "[bravecode-termux]" in before
        p = run_patcher(REAL_BUILD_ZIG)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        after = REAL_BUILD_ZIG.read_text()
        self.assertIn("addAndroidNdkIncludes", after)
        self.assertIn("addAndroidNdkLibraryPath", after)
        self.assertNotIn("getEnvVarOwned", after)
        run_patcher(REAL_BUILD_ZIG)
        self.assertEqual(after, REAL_BUILD_ZIG.read_text())
        self.assertEqual(after.count("fn addAndroidNdkIncludes"), 1)
        self.assertEqual(after.count("fn addAndroidNdkLibraryPath"), 1)
        if not already:
            self.assertNotEqual(before, after, "el parche no cambió el build.zig real")


if __name__ == "__main__":
    unittest.main(verbosity=2)
