"""One documented host contract and a supported floor, not per-release adapters."""

import re
import tomllib
from pathlib import Path

from .errors import CompatibilityError

HOST = tomllib.loads((Path(__file__).parent / "defaults/host.toml").read_text(encoding="utf-8"))


def check_host_version(value: str) -> None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", value)
    if match and tuple(map(int, match.groups())) < tuple(
        map(int, HOST["minimum_version"].split("."))
    ):
        raise CompatibilityError(
            f"This plugin supports Kimi {HOST['minimum_version']} or newer. "
            "Use a compatible plugin or update Kimi yourself; existing memory remains readable."
        )


def host_support() -> dict:
    return {
        **HOST,
        "policy": "Try actual APIs on newer versions; update the plugin if a required contract changes.",
    }
