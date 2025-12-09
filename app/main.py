from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .models import AgentState, Provider, Mode
from .agent_core import plan_tasks, run_execution_loop, execute_task, regenerate_task
from .llm_client import QuotaExceededError

app = FastAPI(title="Agent TODO Executor")

# ----------------------------
# CORS + GLOBALS
# ----------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ok for dev / demo; tighten for production if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single in-memory state for the demo.
# This is fine for a simple MVP, but not multi-user safe.
CURRENT_STATE: Optional[AgentState] = None

# Base paths for static files (index.html, app.js, etc.)
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


# ----------------------------
# REQUEST MODELS
# ----------------------------

class PlanRequest(BaseModel):
    goal: str = Field(..., min_length=1, description="High-level user goal")
    mode: Mode = "confirm"
    provider: Provider = "mock"


class TaskIdRequest(BaseModel):
    task_id: int = Field(..., description="ID of the task to operate on")


class UpdateTaskRequest(BaseModel):
    task_id: int = Field(..., description="ID of the task to update")
    title: str = Field(..., description="New title for the task")
    description: str = Field(..., description="New description for the task")


# ----------------------------
# API ENDPOINTS
# ----------------------------

@app.post("/api/plan", response_model=AgentState)
def api_plan(req: PlanRequest) -> AgentState:
    """
    1) User sends goal + mode + provider.
    2) We plan tasks using that provider.
    3) If mode == 'auto', we immediately run the execution loop.
    4) We return the full AgentState.
    """
    global CURRENT_STATE

    # Basic safety: trim whitespace and ensure the goal is not empty
    cleaned_goal = req.goal.strip()
    if not cleaned_goal:
        raise HTTPException(status_code=400, detail="Goal cannot be empty.")

    try:
        # Plan tasks from the goal
        tasks = plan_tasks(cleaned_goal, provider=req.provider)

        # Build initial state
        state = AgentState(
            goal=cleaned_goal,
            mode=req.mode,
            provider=req.provider,
            tasks=tasks,
            history=[],
        )

        # In auto mode, also execute the plan immediately
        if req.mode == "auto":
            state = run_execution_loop(state)

        CURRENT_STATE = state
        return state

    except QuotaExceededError as e:
        # Demo quota exceeded for OpenAI/HF
        raise HTTPException(status_code=429, detail=str(e))
    except RuntimeError as e:
        # Pass through clear LLM / config errors (missing keys, Ollama down, etc.)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        # Catch-all for truly unexpected issues
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while planning tasks.",
        )


@app.post("/api/execute", response_model=AgentState)
def api_execute() -> AgentState:
    """
    Run the execution loop on the current plan (auto mode).
    """
    global CURRENT_STATE

    if CURRENT_STATE is None:
        raise HTTPException(status_code=400, detail="No plan found. Call /api/plan first.")

    try:
        state = run_execution_loop(CURRENT_STATE)
        CURRENT_STATE = state
        return state

    except QuotaExceededError as e:
        # Demo quota exceeded for OpenAI/HF
        raise HTTPException(status_code=429, detail=str(e))
    except RuntimeError as e:
        # Pass through LLM/config issues
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while executing tasks.",
        )


# ----------------------------
# CONFIRM-MODE TASK OPERATIONS
# ----------------------------

@app.post("/api/update_task", response_model=AgentState)
def api_update_task(req: UpdateTaskRequest) -> AgentState:
    """
    Update a single task's title and description.
    Status and other fields remain unchanged.
    """
    global CURRENT_STATE

    if CURRENT_STATE is None:
        raise HTTPException(status_code=400, detail="No plan found. Call /api/plan first.")

    if not CURRENT_STATE.tasks:
        raise HTTPException(status_code=400, detail="No tasks in current plan.")

    task = next((t for t in CURRENT_STATE.tasks if t.id == req.task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    # Update only title/description; keep status and other fields as is
    task.title = req.title
    task.description = req.description

    return CURRENT_STATE


@app.post("/api/regenerate_task", response_model=AgentState)
def api_regenerate_task(req: TaskIdRequest) -> AgentState:
    """
    Ask the LLM to rewrite a single task (title + description only).
    Status, result, reflection, and history remain unchanged.
    """
    global CURRENT_STATE

    if CURRENT_STATE is None:
        raise HTTPException(status_code=400, detail="No plan found. Call /api/plan first.")

    if not CURRENT_STATE.tasks:
        raise HTTPException(status_code=400, detail="No tasks in current plan.")

    task = next((t for t in CURRENT_STATE.tasks if t.id == req.task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    try:
        regenerate_task(CURRENT_STATE, task)
        return CURRENT_STATE

    except QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except RuntimeError as e:
        # LLM failure / bad JSON
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while regenerating task.",
        )


@app.post("/api/execute_task", response_model=AgentState)
def api_execute_task(req: TaskIdRequest) -> AgentState:
    """
    Execute exactly one task (typically used in Confirm mode).
    Only pending tasks can be executed.
    """
    global CURRENT_STATE

    if CURRENT_STATE is None:
        raise HTTPException(status_code=400, detail="No plan found. Call /api/plan first.")

    if not CURRENT_STATE.tasks:
        raise HTTPException(status_code=400, detail="No tasks in current plan.")

    task = next((t for t in CURRENT_STATE.tasks if t.id == req.task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    if task.status != "pending":
        raise HTTPException(
            status_code=400,
            detail="Only pending tasks can be executed.",
        )

    try:
        execute_task(CURRENT_STATE, task)
        return CURRENT_STATE

    except QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while executing the task.",
        )


@app.post("/api/cancel_task", response_model=AgentState)
def api_cancel_task(req: TaskIdRequest) -> AgentState:
    """
    Cancel a task by marking its status as 'cancelled'.
    Title and description remain unchanged.
    No LLM calls.
    """
    global CURRENT_STATE

    if CURRENT_STATE is None:
        raise HTTPException(status_code=400, detail="No plan found. Call /api/plan first.")

    if not CURRENT_STATE.tasks:
        raise HTTPException(status_code=400, detail="No tasks in current plan.")

    task = next((t for t in CURRENT_STATE.tasks if t.id == req.task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    if task.status != "pending":
        raise HTTPException(
            status_code=400,
            detail="Only pending tasks can be cancelled.",
        )

    task.status = "cancelled"  # type: ignore[assignment]

    return CURRENT_STATE


# ----------------------------
# FRONTEND ROUTE + STATIC FILES
# ----------------------------

@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    """Serve the simple HTML UI."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        # Helpful message if static files are misconfigured on the server
        raise HTTPException(status_code=500, detail="index.html not found in static/ directory.")
    return FileResponse(index_path)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
