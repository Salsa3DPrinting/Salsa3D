"""PyInstaller entry point for SalsaAdapter.exe (see salsa_adapter.spec)."""

import multiprocessing
import sys

from cad.adapter_app.server import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
