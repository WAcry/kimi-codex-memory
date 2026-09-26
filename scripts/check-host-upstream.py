"""Read-only maintenance report for the external updating agent; never updates or publishes code."""

import argparse
import json
import subprocess
import tomllib
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
REPO = "repos/MoonshotAI/kimi-code"
SENSITIVE = (
    "packages/oauth/",
    "packages/agent-core-v2/src/human/llm/",
    "packages/agent-core-v2/src/llm-adapter/",
    "packages/agent-core-v2/src/features/externalHooks/",
    "packages/agent-core-v2/src/app/plugin/",
    "packages/agent-core-v2/src/app/kosongConfig/",
    "packages/kap-server/src/routes/",
    "packages/kap-server/src/services/transcript/",
    "packages/transcript/",
    "apps/kimi-code/src/cli/sub/plugin-run-node",
)


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", REPO + "/" + path], text=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("host-upstream-report.json"))
    args = parser.parse_args()
    baseline = tomllib.loads((ROOT / "src/kimi_memory/defaults/host.toml").read_text())
    latest = api("releases/latest")
    revision = api("commits/" + quote(latest["tag_name"], safe=""))["sha"]
    comparison = api("compare/" + baseline["source_commit"] + "..." + revision)
    files = [item["filename"] for item in comparison.get("files", [])]
    report = {
        "baseline": baseline,
        "latest_version": latest["tag_name"].rsplit("@", 1)[-1],
        "latest_tag": latest["tag_name"],
        "latest_commit": revision,
        "published_at": latest["published_at"],
        "source_changed": revision != baseline["source_commit"],
        "sensitive_files_changed": [name for name in files if name.startswith(SENSITIVE)],
        "changed_files": files,
        "comparison_may_be_truncated": len(files) >= 300,
        "action": "Review affected contracts, run actual host tests, update pinned sources together only when needed; never automatically upgrade user Kimi or publish unreviewed changes.",
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
