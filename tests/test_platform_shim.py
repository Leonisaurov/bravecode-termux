#!/usr/bin/env python3
"""Tests del shim de plataforma (runtime/platform-shim.cjs).

Por qué existe el shim: `@opentui/core` no publica binarios para Android y el
CLI (dist/cli-main.mjs) sólo busca la librería nativa cuando
`process.platform` es darwin/linux/win32. En Termux `process.platform` es
'android', así que el preflight devuelve null y la TUI muere con
"OpenTUI is not supported on the current platform: android-arm64".
El shim declara 'linux' (Bun lo permite sin trucos) y deja `process.arch`
intacto ('arm64'), con lo que el CLI resuelve `@opentui/core-linux-arm64` y
apunta `setRenderLibPath` a la lib compilada para Android que instalamos ahí.

Contrato:
  applyPlatformShim() -> 'linux'   (y process.platform queda en 'linux')
  es idempotente y no rompe process.arch
"""
import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHIM = ROOT / "runtime" / "platform-shim.cjs"
BUN = shutil.which("bun")
NODE = shutil.which("node")


def run_js(runner, script):
    return subprocess.run([runner, "-e", script], capture_output=True, text=True, cwd=str(ROOT))


class PlatformShim(unittest.TestCase):
    def test_shim_file_exists(self):
        """RED inicial: el shim tiene que existir antes de tocar el launcher."""
        self.assertTrue(SHIM.exists(), f"falta {SHIM}")

    @unittest.skipUnless(BUN, "bun no disponible")
    def test_shim_sets_linux_platform_but_keeps_arch(self):
        script = (
            "const {applyPlatformShim} = require('./runtime/platform-shim.cjs');"
            "const r = applyPlatformShim();"
            "console.log(JSON.stringify({ret:r, platform:process.platform, arch:process.arch}));"
        )
        p = run_js(BUN, script)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(data["ret"], "linux")
        self.assertEqual(data["platform"], "linux")
        self.assertEqual(data["arch"], "arm64")

    @unittest.skipUnless(BUN, "bun no disponible")
    def test_shim_is_idempotent(self):
        script = (
            "const {applyPlatformShim} = require('./runtime/platform-shim.cjs');"
            "applyPlatformShim(); applyPlatformShim();"
            "console.log(process.platform);"
        )
        p = run_js(BUN, script)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip().splitlines()[-1], "linux")

    @unittest.skipUnless(NODE, "node no disponible")
    def test_shim_also_works_on_node(self):
        """El mismo shim debe comportarse igual bajo node (por si se depura ahí)."""
        script = (
            "const {applyPlatformShim} = require('./runtime/platform-shim.cjs');"
            "console.log(applyPlatformShim() + ':' + process.platform);"
        )
        p = run_js(NODE, script)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip().splitlines()[-1], "linux:linux")


if __name__ == "__main__":
    unittest.main(verbosity=2)
