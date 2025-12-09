"""
Unified LLM client with four modes:
- mock       : returns hardcoded JSON (no external calls)
- ollama     : calls a local Ollama model
- openai     : calls OpenAI's chat API
- hf/huggingface : calls Hugging Face Inference Providers using an
                   OpenAI-compatible chat completions API.
"""

import os
import json
import random
from typing import List, Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "mock").lower()

MAX_LLM_CALLS = 1000
LLM_CALL_COUNT = 0


class QuotaExceededError(Exception):
  pass


def _check_quota() -> None:
  global LLM_CALL_COUNT
  if LLM_CALL_COUNT >= MAX_LLM_CALLS:
      raise QuotaExceededError(
          f"Demo LLM usage limit reached ({MAX_LLM_CALLS} calls). Please try again later."
      )
  LLM_CALL_COUNT += 1


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_URL = os.getenv("OLLAMA_URL", f"{OLLAMA_HOST}/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

HF_API_KEY = os.getenv("HF_API_KEY")
HF_MODEL = os.getenv("HF_MODEL", "openai/gpt-oss-20b")


def call_llm(
  messages: List[Dict[str, str]],
  provider: Optional[str] = None,
  api_key: Optional[str] = None,
) -> str:
  prov = (provider or DEFAULT_PROVIDER).strip().lower()

  if prov == "openai":
      return _call_openai(messages)
  elif prov == "ollama":
      return _call_ollama(messages)
  elif prov in ("hf", "huggingface"):
      return _call_huggingface(messages)
  else:
      return _call_mock(messages)


def _call_mock(messages: List[Dict[str, str]]) -> str:
  full_text = " ".join(m.get("content", "") for m in messages).lower()

  is_planning = "task planning assistant" in full_text
  is_execution = "execution agent" in full_text
  is_regeneration = "task rewriting assistant" in full_text

  if is_planning:
      data = {
          "tasks": [
              {
                  "title": "Clarify the goal",
                  "description": "Restate the user's goal and constraints in simple terms.",
              },
              {
                  "title": "Draft a first version",
                  "description": "Create a rough draft or plan that addresses the goal.",
              },
              {
                  "title": "Review and refine",
                  "description": "Improve the draft, check for issues, and polish the result.",
              },
          ]
      }
      return json.dumps(data)

  if is_execution:
      data = {
          "status": "done",
          "result": (
              "Executed this task in mock mode. In a real setup, I would use an LLM "
              "to generate detailed text, analysis, or plans."
          ),
          "reflection": (
              "Execution went well. In a real system, this reflection would explain "
              "what worked and what to do next."
          ),
      }
      return json.dumps(data)

  if is_regeneration:
      variants = [
          (
              "Refined task title",
              "A clearer and more concise version of the original task description.",
          ),
          (
              "Improved task wording",
              "Updated description that keeps the same intent but is easier to follow.",
          ),
          (
              "Simplified task title",
              "A shorter description that keeps the important details and makes the task actionable.",
          ),
          (
              "Clear task statement",
              "Restated description that focuses on the main goal of the task in plain language.",
          ),
      ]
      title, description = random.choice(variants)
      data = {
          "title": title,
          "description": description,
      }
      return json.dumps(data)

  data = {
      "status": "done",
      "result": "Mock response: no specific handler detected.",
      "reflection": "This is a fallback mock reply.",
  }
  return json.dumps(data)


def _call_ollama(messages: List[Dict[str, str]]) -> str:
  payload = {
      "model": OLLAMA_MODEL,
      "messages": [
          {"role": m.get("role", "user"), "content": m.get("content", "")}
          for m in messages
      ],
      "stream": False,
  }

  try:
      resp = requests.post(OLLAMA_URL, json=payload, timeout=60)
      resp.raise_for_status()
  except requests.RequestException as e:
      raise RuntimeError(f"Error calling Ollama: {e}") from e

  data = resp.json()
  message = data.get("message", {})
  content = message.get("content")
  if not isinstance(content, str):
      raise RuntimeError("Ollama returned an unexpected response format.")
  return content


def _call_openai(messages: List[Dict[str, str]]) -> str:
  if not OPENAI_API_KEY:
      raise RuntimeError("OPENAI_API_KEY not set on the server.")

  _check_quota()

  from openai import OpenAI

  client = OpenAI(api_key=OPENAI_API_KEY)

  try:
      resp = client.chat.completions.create(
          model=OPENAI_MODEL,
          messages=messages,
          temperature=0.4,
      )
  except Exception as e:
      raise RuntimeError(f"Error calling OpenAI: {e}") from e

  content = resp.choices[0].message.content
  if not isinstance(content, str):
      content = str(content)
  return content


def _call_huggingface(messages: List[Dict[str, str]]) -> str:
  if not HF_API_KEY:
      raise RuntimeError("HF_API_KEY not set on the server.")

  _check_quota()

  from openai import OpenAI

  client = OpenAI(
      api_key=HF_API_KEY,
      base_url="https://router.huggingface.co/v1",
  )

  try:
      resp = client.chat.completions.create(
          model=HF_MODEL,
          messages=messages,
          temperature=0.4,
      )
  except Exception as e:
      raise RuntimeError(f"Error calling Hugging Face: {e}") from e

  content = resp.choices[0].message.content
  if not isinstance(content, str):
      content = str(content)
  return content
