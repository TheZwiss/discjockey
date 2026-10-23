"""PyInstaller's entry script for Discjockey.app. An entry script runs as __main__ and can't use relative imports, so
the program is discjockey/app_main.py and this only calls it."""
import sys

from discjockey.app_main import main

sys.exit(main())
