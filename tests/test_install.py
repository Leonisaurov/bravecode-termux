#!/usr/bin/env python3
"""Tests de install.sh (el instalador del port).

Contrato:
  * sin argumentos       -> ayuda con las opciones y exit 1
  * --check              -> exit 0 sólo si TODO está listo (bun, deps, lib nativa
                            válida y aplicada al node_modules); si falta algo,
                            exit != 0 y nombra lo que falta
  * --patch              -> sólo copia una lib nativa que pase
                            ci/verify-libopentui.sh; con una lib inválida sale
                            con el código del verificador y NO toca node_modules
  * --bin                -> instala el launcher en $PREFIX/bin con el shebang
                            reescrito al $PREFIX real
"""
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.sh"
NATIVE_LIB = ROOT / "native" / "libopentui.android-arm64.so"
TARGET_LIB = ROOT / "app" / "node_modules" / "@opentui" / "core-linux-arm64" / "libopentui.so"
INCOMPLETE_LIB = pathlib.Path(
    "/data/data/com.termux/files/home/Develop/Patch/freebuf/cli/native/libopentui.android-arm64.so"
)


def run_install(*args, env=None, timeout=600):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        [str(INSTALL), *args], capture_output=True, text=True, cwd=str(ROOT), env=e, timeout=timeout
    )


class InstallScript(unittest.TestCase):
    def test_script_exists_and_is_executable(self):
        """RED inicial: install.sh debe existir y ser ejecutable."""
        self.assertTrue(INSTALL.exists(), f"falta {INSTALL}")
        self.assertTrue(os.access(INSTALL, os.X_OK), f"{INSTALL} no es ejecutable")

    def test_no_args_prints_usage(self):
        p = run_install()
        out = p.stdout + p.stderr
        self.assertNotEqual(p.returncode, 0, "sin argumentos debe salir != 0")
        for flag in ("--fetch", "--deps", "--native", "--patch", "--check", "--bin"):
            self.assertIn(flag, out, f"la ayuda no menciona {flag}")

    def test_check_fails_without_native_lib(self):
        """Sin lib nativa en su sitio, --check no puede dar OK."""
        p = run_install("--check")
        out = (p.stdout + p.stderr).lower()
        if NATIVE_LIB.exists() and TARGET_LIB.exists() and NATIVE_LIB.read_bytes() == TARGET_LIB.read_bytes():
            self.skipTest("la lib nativa ya está instalada: el caso 'falta la lib' no aplica")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("libopentui", out)

    def test_patch_rejects_lib_without_required_symbols(self):
        """Una lib que no cumple el contrato FFI no debe llegar a node_modules."""
        if not INCOMPLETE_LIB.exists():
            self.skipTest("no hay lib incompleta de referencia (freebuf 0.3.4)")
        before = TARGET_LIB.read_bytes() if TARGET_LIB.exists() else None
        with tempfile.TemporaryDirectory() as tmp:
            fake_native = pathlib.Path(tmp) / "native"
            fake_native.mkdir()
            shutil.copy2(INCOMPLETE_LIB, fake_native / NATIVE_LIB.name)
            env = {"BRAVECODE_NATIVE_DIR": str(fake_native)}
            p = run_install("--patch", env=env)
        self.assertEqual(p.returncode, 5, p.stdout + p.stderr)
        after = TARGET_LIB.read_bytes() if TARGET_LIB.exists() else None
        self.assertEqual(before, after, "--patch no debe escribir con una lib inválida")

    def test_patch_installs_valid_lib(self):
        if not NATIVE_LIB.exists():
            self.skipTest("lib nativa aún no descargada del CI")
        p = run_install("--patch")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(TARGET_LIB.exists())
        self.assertEqual(NATIVE_LIB.read_bytes(), TARGET_LIB.read_bytes())

    def test_bin_installs_launcher_with_rewritten_shebang(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = pathlib.Path(tmp) / "usr"
            (prefix / "bin").mkdir(parents=True)
            env = {"PREFIX": str(prefix), "BRAVECODE_BUN": shutil.which("bun") or "/bin/false"}
            p = run_install("--bin", env=env)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            installed = prefix / "bin" / "bravecode"
            self.assertTrue(installed.exists())
            self.assertTrue(os.access(installed, os.X_OK))
            shebang = installed.read_text().splitlines()[0]
            self.assertEqual(shebang, f"#!{prefix}/bin/sh")

    def test_check_ok_when_everything_ready(self):
        if not (NATIVE_LIB.exists() and TARGET_LIB.exists()):
            self.skipTest("lib nativa aún no instalada")
        p = run_install("--check")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
