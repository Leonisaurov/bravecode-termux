#!/usr/bin/env python3
"""Tests del verificador de la librería nativa OpenTUI (ci/verify-libopentui.sh).

Contrato del verificador:
  exit 0  -> la .so es ELF AArch64 shared object, declara NEEDED libc.so (Bionic,
             no glibc) y exporta los 397 símbolos FFI de @opentui/core 0.5.9; si
             se le pasa --ndk-lib, todos sus símbolos indefinidos se resuelven
             contra las librerías del NDK
  exit 1  -> falta la lista de símbolos requeridos / NDK mal indicado
  exit 2  -> el archivo no existe
  exit 3  -> no es un ELF AArch64 shared object
  exit 4  -> no declara NEEDED libc.so (Android dlopen no la cargaría)
  exit 5  -> faltan símbolos FFI requeridos (lista completa en stderr)
  exit 6  -> está enlazada contra glibc (libc.so.6), no contra Bionic
  exit 7  -> símbolos indefinidos que Bionic no tiene (glibc-only)
"""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIFY = ROOT / "ci" / "verify-libopentui.sh"
REQUIRED = ROOT / "ci" / "required-symbols.txt"
NATIVE_LIB = ROOT / "native" / "libopentui.android-arm64.so"
# lib real de OpenTUI 0.3.4 compilada antes en este device: incompleta para 0.5.9
INCOMPLETE_LIB = pathlib.Path(
    "/data/data/com.termux/files/home/Develop/Patch/freebuf/cli/native/libopentui.android-arm64.so"
)


def find_glibc_reference():
    """Una .so aarch64 enlazada contra glibc, para probar que el verificador la
    rechaza (exit 6). No se usa la del paquete npm: bun la enlaza con hardlink al
    cache y `install.sh --patch` la sobreescribe con la de Android."""
    for candidate in list((pathlib.Path.home() / ".cache" / "glibc-shim").rglob("lib*.so.*")) + list(
        (ROOT.parent / "Vibe" / "download").rglob("*.so")
    ) + list((ROOT.parent / "Junie" / "app" / "lib").rglob("*.so")):
        name = candidate.name
        # la libc/ld mismas no sirven de fixture: no piden libc.so.6
        if name.startswith(("libc.so", "ld-", "libm.so", "libpthread.so")):
            continue
        try:
            out = subprocess.run(
                ["readelf", "-h", str(candidate)], capture_output=True, text=True
            ).stdout
            if "AArch64" not in out:
                continue
            dyn = subprocess.run(
                ["readelf", "-d", str(candidate)], capture_output=True, text=True
            ).stdout
            if "libc.so.6" in dyn:
                return candidate
        except OSError:
            continue
    return None


def find_ndk_lib_dir():
    """Directorio de librerías de Bionic del NDK local (para el chequeo de UND)."""
    roots = [pathlib.Path(os.environ.get("ANDROID_NDK_HOME", ""))] if os.environ.get("ANDROID_NDK_HOME") else []
    roots += sorted((pathlib.Path.home() / "Android" / "ndk").glob("*"), reverse=True)
    for root in roots:
        if not root or not root.exists():
            continue
        for prebuilt in (root / "toolchains" / "llvm" / "prebuilt").glob("*/sysroot/usr/lib/aarch64-linux-android"):
            d = prebuilt / "24"
            if (d / "libc.so").exists():
                return d
    return None


NDK_LIB_DIR = find_ndk_lib_dir()


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

    def test_glibc_lib_is_rejected(self):
        """Una .so enlazada contra glibc (libc.so.6) no la puede cargar el
        linker de Android: el verificador debe distinguirla por sus NEEDED y
        salir con 6."""
        glibc_lib = find_glibc_reference()
        if glibc_lib is None:
            self.skipTest("no hay .so glibc aarch64 de referencia en el device")
        r = run_verify(glibc_lib)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("glibc", (r.stdout + r.stderr).lower())

    @unittest.skipUnless(NDK_LIB_DIR, "no hay NDK local para el chequeo de símbolos UND")
    @unittest.skipUnless(NATIVE_LIB.exists(), "lib nativa no descargada del CI")
    def test_unresolved_symbols_are_reported(self):
        """Contra las libs de Bionic del NDK, un símbolo glibc-only
        (pthread_tryjoin_np, que Zig 0.16 emite para linux-android) no se
        resuelve: el verificador debe decirlo con exit 7."""
        r = run_verify(NATIVE_LIB, "--ndk-lib", str(NDK_LIB_DIR))
        out = r.stdout + r.stderr
        if "pthread_tryjoin_np" not in out:
            self.assertEqual(r.returncode, 0, f"la lib ya resuelve todos sus UND:\n{out}")
        else:
            self.assertEqual(r.returncode, 7, out)
            self.assertIn("Bionic", out)

    @unittest.skipUnless(
        NATIVE_LIB.exists(),
        "lib nativa 0.5.9 aún no descargada del CI",
    )
    def test_android_lib_from_ci_passes(self):
        """La lib producida por el CI debe pasar todas las comprobaciones."""
        args = ["--ndk-lib", str(NDK_LIB_DIR)] if NDK_LIB_DIR else []
        r = run_verify(NATIVE_LIB, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
