#!/usr/bin/env python3
"""Tests del shim de compatibilidad con Bionic (ci/bionic-compat.c).

Contexto: OpenTUI 0.5.9 compilada con zig 0.16 para `aarch64-linux-android`
queda con `pthread_tryjoin_np` como símbolo indefinido (es exclusivo de glibc;
Bionic no lo tiene). bun:ffi hace dlopen con resolución de símbolos, así que el
cargador falla y la TUI no arranca:

    dlopen failed: cannot locate symbol "pthread_tryjoin_np" referenced by ".../libopentui.so"

El shim define ese símbolo dentro de la propia .so (se compila en el mismo
módulo), con la semántica que espera Zig: 0 si el hilo terminó, EBUSY si sigue
vivo. Verificado en local: el .so resultante ya no lo pide.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHIM = ROOT / "ci" / "bionic-compat.c"


def find_zig():
    local = pathlib.Path.home() / ".local" / "opt" / "zig-0.16.0" / "bin" / "zig"
    if local.exists():
        return str(local)
    return shutil.which("zig")


def find_ndk_libc_file():
    """Escribe el libc.txt del NDK local para poder linkear en el test."""
    roots = sorted((pathlib.Path.home() / "Android" / "ndk").glob("*"), reverse=True)
    for root in roots:
        for prebuilt in (root / "toolchains" / "llvm" / "prebuilt").glob("*/sysroot"):
            if not (prebuilt / "usr" / "include" / "stdlib.h").exists():
                continue
            crt = prebuilt / "usr" / "lib" / "aarch64-linux-android" / "24"
            if not (crt / "crtbegin_dynamic.o").exists():
                continue
            text = (
                f"include_dir={prebuilt}/usr/include\n"
                f"sys_include_dir={prebuilt}/usr/include/aarch64-linux-android\n"
                f"crt_dir={crt}\n"
                "msvc_lib_dir=\n"
                "kernel32_lib_dir=\n"
                "gcc_dir=\n"
            )
            tmp = pathlib.Path(tempfile.mkdtemp()) / "android-libc.txt"
            tmp.write_text(text)
            return tmp, crt
    return None, None


class BionicCompat(unittest.TestCase):
    def test_shim_file_exists(self):
        """RED inicial: el shim tiene que existir."""
        self.assertTrue(SHIM.exists(), f"falta {SHIM}")

    def test_shim_source_defines_tryjoin_with_zig_abi(self):
        src = SHIM.read_text()
        self.assertIn("pthread_tryjoin_np", src)
        self.assertIn("pthread_join", src)
        self.assertIn("EBUSY", src)

    @unittest.skipUnless(find_zig(), "zig no disponible")
    def test_shim_compiles_for_android_and_defines_the_symbol(self):
        zig = find_zig()
        libc_file, lib_dir = find_ndk_libc_file()
        if libc_file is None:
            self.skipTest("no hay NDK local")
        out = pathlib.Path(tempfile.mkdtemp()) / "libcompat.so"
        p = subprocess.run(
            [
                zig,
                "build-lib",
                str(SHIM),
                "-dynamic",
                "-target",
                "aarch64-linux-android.24",
                "--libc",
                str(libc_file),
                f"-L{lib_dir}",
                f"-femit-bin={out}",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        syms = subprocess.run(
            ["readelf", "--dyn-syms", "-W", str(out)], capture_output=True, text=True
        ).stdout
        defined = [
            line
            for line in syms.splitlines()
            if "pthread_tryjoin_np" in line and " UND " not in line
        ]
        self.assertTrue(defined, f"el símbolo no quedó definido:\n{syms[:400]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
