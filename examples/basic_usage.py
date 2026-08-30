"""Minimal Python-API usage example for the V2 collaboration engine.

    Run from anywhere:
        python examples/basic_usage.py

    It runs a small 2-persona collaboration in offline mock mode (no API key)
    and prints the run id + final report. Swap mock=True for real reasoning by
    configuring .env (e.g. DEEPSEEK_API_KEY) and passing provider=... instead.
"""

from __future__ import annotations

import os
import sys
import time

# Make `collab` importable when run as a plain script (repo root on sys.path).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from collab.runner import get_collab_status, run_collaboration


tasks = [
    {"id": "t1", "persona_id": "computing", "input": "评估符号计算的影响", "expected_output": "判断"},
    {"id": "t2", "persona_id": "history", "input": "从技术史评价计算工具演变", "expected_output": "结论"},
]

# mock=True -> deterministic, offline, no API key. For real reasoning set a key
# and use provider="deepseek" (or leave provider="auto") without mock.
run_id = run_collaboration(tasks, mock=True)
print("run_id:", run_id)

status = get_collab_status(run_id)
while status["status"] == "running":
    time.sleep(0.05)
    status = get_collab_status(run_id)
print("status:", status["status"])
print("--- final_report ---")
print(status.get("final_report", ""))
