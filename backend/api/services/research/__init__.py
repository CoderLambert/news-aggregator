"""Owner-private, recoverable research execution services.

Public API:
    run_agent_loop(...)            — guarded research conversation loop
    submit_research_run(...)       — create or attach by owner idempotency key
    cancel_research_run(...)       — cancel only the exact current owner run
    active_run_for_session(...)    — read the current session run
    latest_run_state(...)          — read the safe latest-run DTO
    TOOLS / execute_tool           — existing research tool contract
"""

from .agent_loop import run_agent_loop
from .tools import TOOLS, execute_tool
from .job_manager import (
    ResearchRunError,
    active_run_for_session,
    cancel_research_run,
    latest_run_state,
    submit_research_run,
)

__all__ = [
    'run_agent_loop',
    'TOOLS',
    'execute_tool',
    'ResearchRunError',
    'submit_research_run',
    'cancel_research_run',
    'active_run_for_session',
    'latest_run_state',
]
