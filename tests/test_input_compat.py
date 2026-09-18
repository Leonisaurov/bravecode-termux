#!/usr/bin/env python3
"""Tests del shim de eventos de Input (runtime/opentui-input-compat.cjs).

En @opentui/core 0.5.9 el renderable Input emite:

  * INPUT  -> en cada tecla (`insertText`, borrados…)
  * CHANGE -> sólo en `blur()` / `submit()` ("valor confirmado")
  * ENTER  -> en `submit()`

La TUI de BraveCode sincroniza su estado React con `onChange`, así que mientras
se escribe su `value` sigue vacío: la paleta de `/` no se abre y `doSubmit()`
corta con `if (!value.trim()) return` (el ENTER llega, pero el closure ve '').

El shim hace que INPUT emita también CHANGE con el mismo valor, de modo que el
estado se sincroniza por tecla. Comprobado en el device con este mismo método.
"""
import json
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
require({shim!r}).applyPlatformShim();
const OUT = process.argv[2];
const counts = {{ INPUT: 0, CHANGE: 0, ENTER: 0 }};
const write = (obj) => fs.writeFileSync(OUT, JSON.stringify(obj));
(async () => {{
  const {{ applyInputChangeShim, loadCore }} = require({compat!r});
  const applied = await applyInputChangeShim();
  const m = await loadCore();
  const testing = await loadCore('/testing');
  const {{ renderer }} = await testing.createTestRenderer({{ width: 40, height: 6 }});
  const input = new m.InputRenderable(renderer, {{ id: 'p', width: 30 }});
  const E = m.InputRenderableEvents;
  input.on(E.INPUT, () => counts.INPUT++);
  input.on(E.CHANGE, () => counts.CHANGE++);
  input.on(E.ENTER, () => counts.ENTER++);
  renderer.root.add(input);
  input.focus();
  input.insertText('a');
  input.insertText('b');
  input.insertText('c');
  const afterTyping = {{ ...counts }};
  input.submit();
  write({{ applied, afterTyping, afterSubmit: {{ ...counts }}, value: input.value }});
  process.exit(0);
}})().catch((e) => {{
  write({{ error: String((e && e.message) || e) }});
  process.exit(1);
}});
"""


class InputCompatShim(unittest.TestCase):
    def test_shim_file_exists(self):
        """RED inicial: el shim debe existir."""
        self.assertTrue(SHIM.exists(), f"falta {SHIM}")

    @unittest.skipUnless(BUN, "bun no disponible")
    def test_shim_makes_change_fire_per_keystroke(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = pathlib.Path(tmp) / "probe.cjs"
            probe.write_text(
                PROBE.format(
                    shim=str(ROOT / "runtime" / "platform-shim.cjs"),
                    compat=str(SHIM),
                )
            )
            out_file = pathlib.Path(tmp) / "probe.json"
            env = dict(**__import__("os").environ)
            env["BRAVECODE_APP_DIR"] = str(APP)
            p = subprocess.run(
                [BUN, str(probe), str(out_file)],
                capture_output=True,
                text=True,
                cwd=str(APP),
                env=env,
                timeout=180,
            )
            self.assertTrue(out_file.exists(), f"el probe no escribió resultado\n{p.stdout}\n{p.stderr}")
            data = json.loads(out_file.read_text())
            self.assertNotIn("error", data, data)
            self.assertTrue(data["applied"], "el shim no se aplicó")
            # sin shim: CHANGE sólo aparecería al hacer submit
            self.assertGreaterEqual(
                data["afterTyping"]["CHANGE"], 3, f"CHANGE no se emitió por tecla: {data}"
            )
            self.assertEqual(data["afterTyping"]["INPUT"], 3, data)
            self.assertEqual(data["afterSubmit"]["ENTER"], 1, data)
            self.assertEqual(data["value"], "abc")


if __name__ == "__main__":
    unittest.main(verbosity=2)
