"""PyInstaller entry: the same CLI and offline reader as the source version."""

import sys

from kimi_memory.cli import main

for stream in (sys.stdin, sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")
raise SystemExit(main())
