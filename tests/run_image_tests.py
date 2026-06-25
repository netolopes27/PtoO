#!/usr/bin/env python3
# =============================================================================
# run_image_tests.py — runner da suíte de imagem (tools/photo_to_outline.py)
# -----------------------------------------------------------------------------
# A suíte OpenSCAD (tests/run_tests.py) é EXCLUSIVA de .scad; este é o runner
# Python do tooling de visão, que precisa do venv isolado (numpy + opencv).
#
# Uso (sempre com o Python do venv):
#   tools/.venv/Scripts/python tools/tests/run_image_tests.py
#
# Verde = OK (exit 0). Vermelho = falha/erro de teste (exit 1).
# =============================================================================

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as e:
        print(f"ERRO: dependências ausentes ({e}). Rode com o Python do venv:", file=sys.stderr)
        print("  tools/.venv/Scripts/python tools/tests/run_image_tests.py", file=sys.stderr)
        return 2
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=HERE, pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
