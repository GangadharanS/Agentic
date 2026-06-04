"""Run the five A2A agent HTTP servers locally.

Example:
    python run_agents.py

The orchestrator discovers these servers using:
    A2A_INIT_URL=http://127.0.0.1:9101
    A2A_REVIEWER_URL=http://127.0.0.1:9102
    ...
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from agent_cards import DEFAULT_PORTS


MODULES = {
    "init": "agents.init_server:app",
    "reviewer": "agents.reviewer_server:app",
    "fixer": "agents.fixer_server:app",
    "tester": "agents.tester_server:app",
    "pusher": "agents.pusher_server:app",
}


def _serve(agent_key: str, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(
        MODULES[agent_key],
        host=host,
        port=port,
        log_level=os.getenv("A2A_LOG_LEVEL", "info"),
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run local A2A agent servers")
    p.add_argument("--host", default=os.getenv("A2A_HOST", "127.0.0.1"))
    p.add_argument(
        "--agents",
        default="init,reviewer,fixer,tester,pusher",
        help="Comma-separated subset of agents to run",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    selected = [a.strip() for a in args.agents.split(",") if a.strip()]
    unknown = [a for a in selected if a not in MODULES]
    if unknown:
        raise SystemExit(f"Unknown agents: {unknown}")

    processes: list[mp.Process] = []
    for agent_key in selected:
        port = int(os.getenv(f"A2A_{agent_key.upper()}_PORT", str(DEFAULT_PORTS[agent_key])))
        proc = mp.Process(target=_serve, args=(agent_key, args.host, port), daemon=False)
        proc.start()
        processes.append(proc)
        print(f"[A2A runtime] {agent_key:8s} → http://{args.host}:{port}")

    def _shutdown(_signum, _frame):
        print("\n[A2A runtime] stopping agents…")
        for proc in processes:
            if proc.is_alive():
                proc.terminate()
        for proc in processes:
            proc.join(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    for proc in processes:
        proc.join()


if __name__ == "__main__":
    main()
