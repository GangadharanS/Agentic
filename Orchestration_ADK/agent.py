"""ADK entry module — exposes `root_agent` for `adk run` / `adk web` discovery.

The orchestrator reads the PR target from ``session.state`` (repo_owner,
repo_name, pr_number, ...). The CLI in ``main.py`` seeds that state before
running. When using ``adk web``/``adk run`` directly you must pre-populate the
session state with those keys (see README).
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from agents.orchestrator import build_orchestrator

root_agent = build_orchestrator()
