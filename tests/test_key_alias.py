#!/usr/bin/env python3
"""Tests del alias de flechas (runtime/opentui-input-compat.cjs).

`@opentui/core` 0.5.9 nombra las flechas `up`/`down` (raw y kitty: `"[A": "up"`),
pero la TUI de BraveCode las compara con `arrowUp`/`arrowDown`:

    if (key.name === 'arrowDown') { ... }   // nunca coincide

Resultado medido en la TUI: ctrl+p abre el diálogo de modelos/agentes, pero las
flechas no mueven la selección (el resaltado no cambia). El shim duplica el
`keypress` con el nombre alternativo, de modo que la app lo entiende sin romper
a quien usa los nombres nativos (el core sólo maneja `up`/`down`).

Contrato:
  * `down`  -> se emiten `down` y `arrowDown`
  * `up`    -> se emiten `up` y `arrowUp`
  * teclas normales: una sola emisión (sin duplicar)
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHIM = ROOT / "runtime" / "opentui-input-compat.cjs"
APP = ROOT / "app"
BUN = shutil.which("bun")

PROBE = """\
const fs = require('node:fs');
require({platform!r}).applyPlatformShim();
const OUT = process.argv[2];
const write = (o) => fs.writeFileSync(OUT, JSON.stringify(o));
(async () => {{
  const {{ applyKeyAliasShim, loadCore }} = require({compat!r});
  const core = await loadCore();
  const testing = await loadCore('/testing');
  const {{ createTestRenderer, KeyCodes }} = testing;
  const applied = await applyKeyAliasShim();
  const {{ renderer, mockInput }} = await createTestRenderer({{ width: 40, height: 8 }});
  const seen = [];
  renderer.keyInput.on('keypress', (e) => seen.push(e.name));
  mockInput.pressKey(KeyCodes.ARROW_DOWN);
  mockInput.pressKey(KeyCodes.ARROW_UP);
  mockInput.pressKey('a');
  const before = seen.slice();
  write({{ applied, seen: before }});
  process.exit(0);
}})().catch((e) => {{
  write({{ error: String((e && e.message) || e) }});
  process.exit(1);
}});
"""


class KeyAliasShim(unittest.TestCase):
    def test_shim_exposes_alias_function(self):
        """RED inicial: el shim debe ofrecer applyKeyAliasShim."""
        self.assertTrue(SHIM.exists(), f"falta {SHIM}")
        self.assertIn("applyKeyAliasShim", SHIM.read_text())

    @unittest.skipUnless(BUN, "bun no disponible")
    def test_arrows_get_aliases_without_duplicating_normal_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = pathlib.Path(tmp) / "probe.cjs"
            probe.write_text(
                PROBE.format(
                    platform=str(ROOT / "runtime" / "platform-shim.cjs"),
                    compat=str(SHIM),
                )
            )
            out_file = pathlib.Path(tmp) / "out.json"
            env = dict(os.environ, BRAVECODE_APP_DIR=str(APP))
            subprocess.run(
                [BUN, str(probe), str(out_file)],
                capture_output=True, text=True, cwd=str(APP), env=env, timeout=180, check=False
            )
            self.assertTrue(out_file.exists(), "el probe no escribió resultado")
            data = json.loads(out_file.read_text())
            self.assertNotIn("error", data, data)
            self.assertTrue(data["applied"], "el shim no se aplicó")
            seen = data["seen"]
            self.assertIn("down", seen)
            self.assertIn("arrowDown", seen, f"la app no vería la flecha abajo: {seen}")
            self.assertIn("up", seen)
            self.assertIn("arrowUp", seen, f"la app no vería la flecha arriba: {seen}")
            # una tecla normal no se duplica
            self.assertEqual(seen.count("a"), 1, f"tecla normal duplicada: {seen}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
