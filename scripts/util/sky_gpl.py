#!/usr/bin/env python3
"""Run librelane through OpenROAD.GlobalPlacement and print util% as JSON.

Stops right after GPL — fast enough to use as a search metric. Reads util
from the GPL log (reported the same whether GPL passes or fails).
Exit 0 if util parsed, 2 otherwise.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
CONFIG = REPO / "src/config_merged.json"
RUN_DIR = REPO / "runs/gpl"
TT_TOOL = REPO / "tt/tt_tool.py"
PYTHON = REPO / ".venv-tt/bin/python"


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{REPO / '.venv-tt/bin'}:{env.get('PATH', '')}"
    try:
        brew = subprocess.check_output(["brew", "--prefix"], text=True).strip()
        env["DYLD_FALLBACK_LIBRARY_PATH"] = f"{brew}/lib"
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return env


def ensure_config(env: dict[str, str]) -> None:
    if CONFIG.exists():
        return
    subprocess.run(
        [str(PYTHON), str(TT_TOOL), "--create-user-config"],
        check=True, cwd=REPO, env=env,
    )


def parse_util() -> float | None:
    candidates = sorted(RUN_DIR.glob("*-openroad-globalplacement/openroad-globalplacement.log"))
    if not candidates:
        return None
    text = candidates[-1].read_text()
    m = re.search(r"\[(?:INFO|ERROR) GPL-001[89]\]\s+Utilization:?\s+([\d.]+)\s*%", text)
    if m:
        return float(m.group(1))
    m = re.search(r"\[ERROR GPL-0301\]\s+Utilization\s+([\d.]+)\s*%", text)
    if m:
        return float(m.group(1))
    return None


def main() -> None:
    env = build_env()
    ensure_config(env)
    shutil.rmtree(RUN_DIR, ignore_errors=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(PYTHON), "-m", "librelane",
        "--docker-no-tty", "--dockerized",
        "--run-tag", "gpl",
        "--force-run-dir", str(RUN_DIR),
        "--to", "OpenROAD.GlobalPlacement",
        "--hide-progress-bar",
        str(CONFIG),
    ]
    if "PDK_ROOT" in env:
        cmd[3:3] = ["--pdk-root", env["PDK_ROOT"]]

    t0 = time.time()
    proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)
    elapsed = time.time() - t0

    util = parse_util()
    result: dict[str, object] = {
        "util": util,
        "passed": proc.returncode == 0,
        "elapsed": round(elapsed, 1),
    }
    if util is None:
        # Flow died before GPL (e.g., STA-PrePnR rejected constraints.sdc).
        # Surface the real error instead of a generic parse-failure message.
        errors = re.findall(r"(?m)^.*?\bError:.*$", proc.stdout)
        result["error"] = errors[0].strip() if errors else "could not parse util from GPL log"
        result["stderr_tail"] = proc.stderr[-800:]
    print(json.dumps(result, indent=2))
    sys.exit(0 if util is not None else 2)


if __name__ == "__main__":
    main()
