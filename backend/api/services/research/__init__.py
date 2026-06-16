"""Intelligent news research agent service.

Public API:
    run_agent_loop(session, user_query, on_event)  — core agent loop
    execute_tool(name, args) -> dict                 — tool dispatcher
    TOOLS                                            — OpenAI function-calling schema
    start_or_get_research_job(...)                   — background job manager
"""

from .agent_loop import run_agent_loop
from .tools import TOOLS, execute_tool
from .job_manager import start_or_get_research_job, get_research_job

__all__ = [
    'run_agent_loop',
    'TOOLS',
    'execute_tool',
    'start_or_get_research_job',
    'get_research_job',
]
