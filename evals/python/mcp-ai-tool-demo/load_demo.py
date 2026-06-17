import argparse
import asyncio
import random
import time
from typing import Any

import httpx


AUTH = {"Authorization": "Bearer demo-token"}


async def rpc(client: httpx.AsyncClient, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = await client.post(
        "/mcp",
        headers=AUTH,
        json={"jsonrpc": "2.0", "id": random.randint(1, 100000), "method": method, "params": params or {}},
    )
    response.raise_for_status()
    return response.json()


async def initialize(client: httpx.AsyncClient) -> str:
    response = await rpc(client, "initialize")
    return response["result"]["session_id"]


async def call_tool(client: httpx.AsyncClient, session_id: str) -> None:
    tool = random.choice(["summarize_metadata", "search_knowledge"])
    arguments: dict[str, Any] = {"query": "summarize customer metadata health", "limit": random.randint(1, 5)}
    if random.random() < 0.12:
        arguments["tool_error"] = True
    if random.random() < 0.08:
        arguments["provider_error"] = True
    await rpc(client, "tools/call", {"session_id": session_id, "name": tool, "arguments": arguments})


async def stream_session(client: httpx.AsyncClient, session_id: str) -> None:
    async with client.stream("GET", f"/mcp/sessions/{session_id}/stream", headers=AUTH) as response:
        if response.status_code != 200:
            return
        async for _ in response.aiter_lines():
            pass


async def run_load(base_url: str, duration: int, concurrency: int) -> None:
    deadline = time.monotonic() + duration
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        sessions = [await initialize(client) for _ in range(max(1, concurrency))]
        await rpc(client, "tools/list")
        while time.monotonic() < deadline:
            tasks = []
            for _ in range(concurrency):
                session_id = random.choice(sessions)
                if random.random() < 0.2:
                    tasks.append(stream_session(client, session_id))
                else:
                    tasks.append(call_tool(client, session_id))
            await asyncio.gather(*tasks, return_exceptions=True)
            if random.random() < 0.1 and sessions:
                session_id = sessions.pop(0)
                await client.delete(f"/mcp/sessions/{session_id}")
                sessions.append(await initialize(client))
            await asyncio.sleep(0.2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8020")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    asyncio.run(run_load(args.base_url, args.duration, args.concurrency))


if __name__ == "__main__":
    main()
