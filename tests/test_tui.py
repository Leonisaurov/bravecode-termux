#!/usr/bin/env python3
"""Test de integración de la TUI en tmux.

Es la verificación final del port: la TUI sólo arranca si
  1. el shim de plataforma hace que el preflight del bundle vea linux-arm64,
  2. `@opentui/core-linux-arm64/libopentui.so` es la lib compilada para Android
     (con los 397 símbolos FFI), y
  3. bun:ffi puede hacer dlopen de una .so Bionic.

Se salta automáticamente si la lib nativa todavía no está instalada.
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "bin" / "bravecode"
PLATFORM_LIB = ROOT / "app" / "node_modules" / "@opentui" / "core-linux-arm64" / "libopentui.so"
TMUX = shutil.which("tmux")
SESSION = "bc-tui-test"

BAD = ("OpenTUI is not supported", "Fatal error", "Bad system call", "Cannot find module")


def tmux(*args, timeout=30):
    return subprocess.run([TMUX, *args], capture_output=True, text=True, timeout=timeout)


class TuiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PLATFORM_LIB.exists():
            raise unittest.SkipTest("lib nativa no instalada (install.sh --native --patch)")

    def tearDown(self):
        if TMUX:
            tmux("kill-session", "-t", SESSION)

    @unittest.skipUnless(TMUX, "tmux no disponible")
    def test_tui_renders_in_tmux(self):
        with tempfile.TemporaryDirectory() as project:
            tmux("kill-session", "-t", SESSION)
            r = tmux(
                "new-session",
                "-d",
                "-s",
                SESSION,
                "-x",
                "110",
                "-y",
                "32",
                "-c",
                project,
                str(LAUNCHER),
            )
            self.assertEqual(r.returncode, 0, r.stderr)

            pane = ""
            deadline = time.time() + 90
            while time.time() < deadline:
                time.sleep(3)
                pane = tmux("capture-pane", "-p", "-t", SESSION).stdout
                if "BraveCode" in pane or "bravecode" in pane.lower():
                    break

            tmux("kill-session", "-t", SESSION)

            for bad in BAD:
                self.assertNotIn(bad, pane, f"la TUI mostró un error fatal:\n{pane}")
            self.assertTrue(
                pane.strip(), "el panel de la TUI quedó vacío (no arrancó)"
            )
            self.assertIn(
                "BraveCode",
                pane,
                f"la TUI no renderizó su cabecera; contenido del panel:\n{pane}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
