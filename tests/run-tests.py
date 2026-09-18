#!/usr/bin/env python3
"""Runner de tests del port de BraveCode (Termux/Android).

Los tests son de tipo TDD: primero el comportamiento observable (RED), luego
la implementación que lo cumple (GREEN). Cada test corre con `python3` del
sistema, sin dependencias externas.

Uso:
    python3 tests/run-tests.py            # todos los tests
    python3 tests/run-tests.py -k shim    # sólo los que matcheen
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"


def main(argv):
    loader = unittest.TestLoader()
    suite = loader.discover(str(TESTS), pattern="test_*.py", top_level_dir=str(TESTS))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
