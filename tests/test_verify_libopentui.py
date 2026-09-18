#!/usr/bin/env python3
"""Tests del verificador de la librería nativa OpenTUI (ci/verify-libopentui.sh).

Contrato del verificador:
  exit 0  -> la .so es ELF AArch64 shared object, tiene NEEDED libc.so y exporta
             los 397 símbolos FFI que exige @opentui/core 0.5.9
  exit 2  -> el archivo no existe
  exit 3  -> no es un ELF AArch64 shared object
  exit 4  -> no declara NEEDED libc.so (Android dlopen no la cargaría)
  exit 5  -> faltan símbolos FFI requeridos (lista en stderr)
"""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIFY = ROOT / "ci" / "verify-libopentui.sh"
REQUIRED = ROOT / "ci" / "required-symbols.txt"
# lib real de OpenTUI 0.3.4 compilada antes en este device: incompleta para 0.5.9
INCOMPLETE_LIB = pathlib.Path(
    "/data/data/com.termux/files/home/Develop/Patch/freebuf/cli/native/libopentui.android-arm64.so"
)


def run_verify(path, *args):
    return subprocess.run(
        [str(VERIFY), str(path), *args],
        capture_output=True,
        text=True,
    )


class VerifyLibOpenTui(unittest.TestCase):
    def test_verify_script_exists_and_is_executable(self):
        """RED inicial: el verificador tiene que existir y ser ejecutable."""
        self.assertTrue(VERIFY.exists(), f"falta {VERIFY}")
        self.assertTrue(os.access(VERIFY, os.X_OK), f"{VERIFY} no es ejecutable")

    def test_required_symbols_list_is_complete(self):
        """La lista de símbolos debe traer los 397 requeridos por 0.5.9."""
        lines = [
            ln.strip()
            for ln in REQUIRED.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        self.assertEqual(len(lines), 397, "esperados 397 símbolos FFI")
        for name in ("createEventSink", "createRenderer", "embeddedTerminalWrite",
                     "clipboardServiceCreate", "editorViewConvertSelectionToCell"):
            self.assertIn(name, lines)

    def test_missing_file_is_exit_2(self):
        r = run_verify("/nonexistent/libopentui.so")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("no existe", r.stderr.lower())

    def test_non_elf_is_exit_3(self):
        with tempfile.NamedTemporaryFile("w", suffix=".so", delete=False) as fh:
            fh.write("no soy una libreria\n")
            tmp = fh.name
        try:
            r = run_verify(tmp)
            self.assertEqual(r.returncode, 3, r.stderr)
        finally:
            os.unlink(tmp)

    @unittest.skipUnless(INCOMPLETE_LIB.exists(), "lib 0.3.4 de referencia no disponible")
    def test_incomplete_lib_reports_missing_symbols(self):
        """La lib 0.3.4 real debe fallar con exit 5 nombrando símbolos ausentes."""
        r = run_verify(INCOMPLETE_LIB)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("embeddedTerminalWrite", r.stdout + r.stderr)
        self.assertIn("clipboardServiceCreate", r.stdout + r.stderr)

    @unittest.skipUnless(
        (ROOT / "native" / "libopentui.android-arm64.so").exists(),
        "lib nativa 0.5.9 aún no descargada del CI",
    )
    def test_android_lib_from_ci_passes(self):
        """La lib producida por el CI debe pasar todas las comprobaciones."""
        r = run_verify(ROOT / "native" / "libopentui.android-arm64.so")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
