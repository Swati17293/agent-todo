# app/models.py

"""
Core data models for the Agent TODO Executor app.

These Pydantic models define the shapes of tasks and the overall agent state
that flow between the backend and frontend.
"""

from typing import Literal, List, Optional
from pydantic import BaseModel, Field

# Allowed task statuses in the execution flow
TaskStatus = Literal["pending", "done", "failed", "needs_follow_up"]

# Supported LLM providers
Provider = Literal["mock", "ollama", "openai", "hf", "huggingface"]

# Modes for how the agent should behave
# - "confirm": plan first, then execute only when asked
# - "auto": plan and execute immediately
Mode = Literal["confirm", "auto"]


class Task(BaseModel):
    """
    One atomic task in the agent's TODO list.
    """

    id: int
    title: str
    description: str

    # Execution status and outputs
    status: TaskStatus = "pending"
    result: Optional[str] = None
    reflection: Optional[str] = None


class AgentState(BaseModel):
    """
    Full state of the agent for a single session:
    - the overall goal
    - the chosen mode and provider
    - the list of tasks
    - a simple text history of what happened during execution
    """

    goal: str
    mode: Mode = "confirm"
    provider: Provider = "mock"

    # Use default_factory so each AgentState gets its own list instance
    tasks: List[Task] = Field(default_factory=list)
    history: List[str] = Field(default_factory=list)
