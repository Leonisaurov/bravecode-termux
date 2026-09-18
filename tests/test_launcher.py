#!/usr/bin/env python3
"""Tests del launcher (bin/bravecode + runtime/launch.cjs).

Contrato observable:
  - `bin/bravecode` es ejecutable y arranca el bundle real del CLI pasando los
    argumentos tal cual (el CLI resuelve el proyecto desde el CWD del usuario,
    así que el launcher no debe cambiar de directorio).
  - `runtime/launch.cjs` aplica el shim de plataforma ANTES de importar el
    bundle (si no, el preflight de la TUI ve 'android' y falla).
"""
import os
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "bin" / "bravecode"
LAUNCH = ROOT / "runtime" / "launch.cjs"
APP_BUNDLE = ROOT / "app" / "node_modules" / "bravecode-cli" / "dist" / "cli-main.mjs"
BUN = shutil.which("bun")


class Launcher(unittest.TestCase):
    def test_launcher_exists_and_is_executable(self):
        """RED inicial: el launcher y el wrapper deben existir y ser usables."""
        self.assertTrue(LAUNCHER.exists(), f"falta {LAUNCHER}")
        self.assertTrue(os.access(LAUNCHER, os.X_OK), f"{LAUNCHER} no es ejecutable")
        self.assertTrue(LAUNCH.exists(), f"falta {LAUNCH}")

    def test_launch_applies_shim_before_loading_the_package(self):
        """Prueba de comportamiento: cuando el bundle del paquete carga, la
        plataforma ya es 'linux' y arch sigue siendo 'arm64'."""
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp) / "node_modules" / "bravecode-cli" / "dist"
            fake.mkdir(parents=True)
            (fake / "cli.cjs").write_text(
                "console.log(JSON.stringify({platform: process.platform, arch: process.arch}));\n"
            )
            env = dict(os.environ, BRAVECODE_APP_DIR=tmp)
            p = subprocess.run(
                [BUN, str(LAUNCH)], capture_output=True, text=True, env=env, timeout=60
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            data = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertEqual(data["platform"], "linux", "el shim no se aplicó antes del paquete")
            self.assertEqual(data["arch"], "arm64")

    def test_launcher_does_not_cd(self):
        """El CLI trabaja sobre el proyecto del usuario: el launcher no debe cd."""
        src = LAUNCHER.read_text()
        for bad in ("cd /", "cd $HOME", "cd ~"):
            self.assertNotIn(bad, src)

    @unittest.skipUnless(BUN and APP_BUNDLE.exists(), "app/node_modules aún no instalado")
    def test_cli_version_runs(self):
        """Smoke real: `bravecode --version` debe imprimir la versión del paquete."""
        p = subprocess.run([str(LAUNCHER), "--version"], capture_output=True, text=True, timeout=180)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout + p.stderr, r"\d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main(verbosity=2)
