"""V2 collaboration engine (mode B: weak-decentralised execution).

M1: task model + state machine + L2 audit + wave executor + horizontal
collaboration + arbitration + recovery/budget + async runner.
M2: per-agent memory (T8/T9), cost/waste/budget (T10-T12), FR11 motion,
dual-mode (T14), exec-dependency evaluation (T15), run persistence (T16).
The M2 modules (memory/costing/motion/runstore) are imported directly, not
re-exported here, to keep `from collab import ...` lightweight.
See docs/AGENT_GUIDE.md.
"""

from __future__ import annotations

from .models import CollabMessage, Task, TaskAudit, TaskStatus
from .runner import get_collab_status, run_collaboration, stop_collab
from .state_machine import TaskStateMachine, can_transition

__all__ = [
    "Task",
    "TaskStatus",
    "TaskAudit",
    "CollabMessage",
    "TaskStateMachine",
    "can_transition",
    "run_collaboration",
    "get_collab_status",
    "stop_collab",
]
