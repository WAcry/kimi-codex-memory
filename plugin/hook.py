#!/usr/bin/env python3
"""Repo-local plugin entry. The hook module is independent from worker dependencies."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kimi_memory.hooks import main

raise SystemExit(main())
