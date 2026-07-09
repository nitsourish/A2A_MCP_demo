#!/usr/bin/env python3
"""
End-to-end demo: launches the Weather Agent and Activity Planner Agent as
separate processes (each with its own internal MCP server), waits for both
to come up, then sends a few sample A2A requests to the Activity Planner
and prints the full agent-to-agent exchange.

Run with:
    uv run python run_demo.py
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common.env  # noqa: E402,F401 - loads .env as an import side effect
from common.a2a_protocol import A2AClient  # noqa: E402

ROOT = Path(__file__).resolve().parent
WEATHER_AGENT_URL = "http://localhost:8001"
ACTIVITY_AGENT_URL = "http://localhost:8002"

SAMPLE_QUERIES = [
    "What should we do in Paris, FR today?",
    "Plan something fun in New York, NY.",
    "What can we do in Tokyo, JP today?",
]


def _start(script: str, args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(ROOT / script), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


async def _wait_until_up(url: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(f"{url}/.well-known/agent.json", timeout=2.0)
                if resp.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise TimeoutError(f"{url} did not come up within {timeout}s")


async def main() -> None:
    print("Starting Weather Agent on :8001 ...")
    weather_proc = _start("weather_agent/agent.py", ["--port", "8001"])
    print("Starting Activity Planner Agent on :8002 ...")
    activity_proc = _start(
        "activity_agent/agent.py",
        ["--port", "8002", "--weather-agent-url", WEATHER_AGENT_URL],
    )

    try:
        await _wait_until_up(WEATHER_AGENT_URL)
        await _wait_until_up(ACTIVITY_AGENT_URL)
        print("Both agents are up.\n")

        weather_client = A2AClient(WEATHER_AGENT_URL)
        activity_client = A2AClient(ACTIVITY_AGENT_URL)

        weather_card = await weather_client.get_agent_card()
        activity_card = await activity_client.get_agent_card()
        print(f"Discovered agent: {weather_card.name} - {weather_card.description}")
        print(f"Discovered agent: {activity_card.name} - {activity_card.description}\n")

        for query in SAMPLE_QUERIES:
            print(f"USER -> Activity Planner Agent: {query}")
            reply = await activity_client.send_message(query)
            print(f"Activity Planner Agent -> USER: {reply}\n")

        await weather_client.aclose()
        await activity_client.aclose()

    finally:
        print("Shutting down agents...")
        for proc in (weather_proc, activity_proc):
            proc.terminate()
        for proc in (weather_proc, activity_proc):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        # Surface subprocess logs if something went wrong.
        for name, proc in (("weather_agent", weather_proc), ("activity_agent", activity_proc)):
            if proc.returncode not in (0, None, -15):
                print(f"--- {name} output ---")
                if proc.stdout:
                    print(proc.stdout.read())


if __name__ == "__main__":
    asyncio.run(main())
