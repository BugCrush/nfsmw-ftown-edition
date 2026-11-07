"""Entry point of FTownEditionInstaller.exe (PyInstaller runs this file)."""
import sys

from ftedition.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
