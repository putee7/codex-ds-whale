"""Portable entry point: also works with CPython's isolated embedded distribution."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_whale_pet.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
