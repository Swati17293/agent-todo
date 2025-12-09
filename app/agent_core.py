import json
import re
from typing import List, Optional

from .models import Task, AgentState, Provider
from .llm_client import call_llm


def _parse_llm_json(raw: str) -> Optional[dict]:
  """
  Try hard to parse a JSON object from LLM output.
  """
  if not isinstance(raw, str):
      raw = str(raw)

  try:
      data = json.loads(raw)
      if isinstance(data, dict):
          return data
  except Exception:
      pass

  match = re.search(r"\{[\s\S]*\}", raw)
  if match:
      candidate = match.group(0)
      try:
          data = json.loads(candidate)
          if isinstance(data, dict):
              return data
      except Exception:
          pass

  return None


def _parse_execution_output(raw: str) -> Optional[dict]:
  """
  Specialized parser for execution outputs.
  """
  if not isinstance(raw, str):
      raw = str(raw)

  data = _parse_llm_json(raw)
  if isinstance(data, dict):
      return data

  status_match = re.search(r'"status"\s*:\s*"([^"]+)"', raw)
  result_match = re.search(
      r'"result"\s*:\s*"([\s\S]*?)"\s*,\s*"reflection"', raw
  )
  reflection_match = re.search(
      r'"reflection"\s*:\s*"([\s\S]*?)"\s*}?', raw
  )

  if not (status_match or result_match or reflection_match):
      return None

  parsed: dict = {}
  if status_match:
      parsed["status"] = status_match.group(1)
  if result_match:
      parsed["result"] = result_match.group(1)
  if reflection_match:
      parsed["reflection"] = reflection_match.group(1)

  return parsed or None


def plan_tasks(goal: str, provider: Provider) -> List[Task]:
  clean_goal = (goal or "").strip()

  system_msg = (
      "You are a task planning assistant.\n"
      "Given a high-level goal, break it into 3 to 6 concrete tasks.\n"
      "Each task must have a title and a short description.\n"
      "Reply ONLY with valid JSON of the form:\n"
      '{ \"tasks\": [ {\"title\": \"...\", \"description\": \"...\"}, ... ] }'
  )

  user_msg = f"User goal:\n{clean_goal}"

  raw = call_llm(
      [
          {"role": "system", "content": system_msg},
          {"role": "user", "content": user_msg},
      ],
      provider=provider,
  )

  if not isinstance(raw, str):
      raw = str(raw)

  data = _parse_llm_json(raw)
  tasks: List[Task] = []

  if isinstance(data, dict):
      items = data.get("tasks", [])
      if isinstance(items, list):
          for i, t in enumerate(items, start=1):
              title = t.get("title", f"Task {i}")
              description = t.get("description", "")
              tasks.append(
                  Task(
                      id=i,
                      title=str(title),
                      description=str(description),
                  )
              )

  if tasks:
      return tasks

  return [
      Task(
          id=1,
          title="Clarify the goal",
          description="Restate the user's goal and constraints in simple terms.",
      ),
      Task(
          id=2,
          title="Draft a first version",
          description="Create a rough draft or plan that addresses the goal.",
      ),
      Task(
          id=3,
          title="Review and refine",
          description="Improve the draft, check for issues, and polish the result.",
      ),
  ]


def execute_task(state: AgentState, task: Task) -> Task:
  """
  Execution phase: ask provider to work on ONE task.
  """
  provider: Provider = state.provider

  system_msg = (
      "You are an execution agent.\n"
      "You receive the user's overall goal and a single selected task.\n"
      "You can only produce text output such as explanations, plans, code samples, summaries, or step-by-step instructions.\n"
      "You cannot browse the internet. You cannot deploy websites. You cannot run code, create real files, or create real applications.\n"
      "Be honest about what you actually did. Describe only actions that can be fully completed in text.\n"
      "If the task cannot be fully completed using text alone but you can still provide a useful draft, outline, explanation, or set of instructions, set status to \"needs_follow_up\" and explain what remains.\n"
      "If the core action of the task is impossible for you (for example sending an email, deploying a website, running code, accessing external systems, or browsing the internet) and you cannot meaningfully complete it even as a text-only draft, set status to \"failed\" and clearly explain why.\n"
      "Reply ONLY with JSON:\n"
      "{\n"
      "  \"status\": \"done\" | \"failed\" | \"needs_follow_up\",\n"
      "  \"result\": \"plain text description of what you produced or tried to do\",\n"
      "  \"reflection\": \"plain text notes on how it went and any next steps\"\n"
      "}\n"
      "Default to \"needs_follow_up\" unless the task is clearly fully completed in text or clearly impossible for you.\n"
      "Never claim that you deployed anything, ran tools, or created real files or applications.\n"
      "Never put JSON, code objects, or Python dicts inside the \"result\" string.\n"
      "Do not use Markdown, headings, bullet points, or bold text.\n"
      "Avoid sequences like \\n\\n in the result string.\n"
      "Keep result and reflection as simple plain text."
  )

  task_list_str = "\n".join(
      f"- [{t.id}] {t.title} (status: {t.status})" for t in state.tasks
  )

  user_msg = (
      f"User goal:\n{state.goal}\n\n"
      f"All tasks:\n{task_list_str}\n\n"
      f"Selected task (id {task.id}):\n"
      f"Title: {task.title}\n"
      f"Description: {task.description}\n"
  )

  raw = call_llm(
      [
          {"role": "system", "content": system_msg},
          {"role": "user", "content": user_msg},
      ],
      provider=provider,
  )

  if not isinstance(raw, str):
      raw = str(raw)

  data = _parse_execution_output(raw)

  if isinstance(data, dict):
      status = data.get("status", "needs_follow_up")
      result = data.get("result", raw)
      reflection = data.get("reflection", "")
  else:
      status = "needs_follow_up"
      result = raw
      reflection = ""

  valid_statuses = {"pending", "done", "failed", "needs_follow_up", "cancelled"}
  if status not in valid_statuses:
      status = "needs_follow_up"

  task.status = status  # type: ignore[assignment]
  task.result = str(result) if result is not None else None
  task.reflection = str(reflection) if reflection is not None else None

  state.history.append(
      f"Selected task {task.id}: {task.title}\n"
      f"Status: {task.status}\n"
      f"Result:\n{task.result}\n"
      f"Reflection:\n{task.reflection}\n"
      "-------------------------"
  )

  return task


def regenerate_task(state: AgentState, task: Task) -> Task:
  """
  Regeneration phase: rewrite ONE existing task.
  """
  provider: Provider = state.provider

  system_msg = (
      "You are a task rewriting assistant.\n"
      "You receive the user's overall goal and ONE existing task.\n"
      "Rewrite the task title and description to be clearer, more concise, "
      "and more actionable, while keeping the same intent.\n"
      "Reply ONLY with valid JSON:\n"
      '{ \"title\": \"...\", \"description\": \"...\" }'
  )

  user_msg = (
      f"User goal:\n{state.goal}\n\n"
      f"Existing task:\n"
      f"Title: {task.title}\n"
      f"Description: {task.description}\n"
  )

  raw = call_llm(
      [
          {"role": "system", "content": system_msg},
          {"role": "user", "content": user_msg},
      ],
      provider=provider,
  )

  if not isinstance(raw, str):
      raw = str(raw)

  data = _parse_llm_json(raw)
  if not isinstance(data, dict):
      raise RuntimeError("Failed to parse LLM response for regenerated task.")

  if "title" not in data:
      raise RuntimeError("Regenerated task JSON missing 'title' field.")

  new_title = data.get("title")
  new_description = data.get("description", "")

  if not isinstance(new_title, str):
      raise RuntimeError("Regenerated task 'title' must be a string.")

  if new_description is None:
      new_description = ""
  elif not isinstance(new_description, str):
      new_description = str(new_description)

  task.title = new_title
  task.description = new_description

  return task


def select_next_task(state: AgentState) -> Optional[Task]:
  for t in state.tasks:
      if t.status == "pending":
          return t
  return None


def run_execution_loop(state: AgentState) -> AgentState:
  while True:
      task = select_next_task(state)
      if task is None:
          break
      execute_task(state, task)
  return state
