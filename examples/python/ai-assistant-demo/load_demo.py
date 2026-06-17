import argparse
import asyncio
import random
import time

import httpx


PROMPTS = [
    "summarize metadata health for workspace alpha",
    "search docs and lookup customer routing",
    "truncate this response because the context is large",
    "tool_error while looking up the customer profile",
    "too_long " + "metadata " * 1500,
]


async def post_chat(client: httpx.AsyncClient, prompt: str) -> None:
    response = await client.post(
        "/v1/chat",
        json={
            "session_id": f"demo-{random.randint(1, 5)}",
            "prompt": prompt,
            "tools": ["search_docs", "lookup_customer"],
        },
    )
    if response.status_code not in {200, 413}:
        response.raise_for_status()


async def post_stream(client: httpx.AsyncClient, prompt: str) -> None:
    async with client.stream(
        "POST",
        "/v1/chat/stream",
        json={
            "session_id": f"stream-{random.randint(1, 3)}",
            "prompt": prompt,
            "tools": ["search_docs"],
        },
    ) as response:
        if response.status_code != 200:
            return
        async for _ in response.aiter_lines():
            pass


async def post_feedback(client: httpx.AsyncClient) -> None:
    await client.post(
        "/v1/feedback",
        json={
            "session_id": f"demo-{random.randint(1, 5)}",
            "rating": random.randint(1, 5),
            "comment": "demo feedback",
        },
    )
    if random.random() < 0.25:
        await client.post("/v1/feedback/export")


async def run_load(base_url: str, duration: int, concurrency: int) -> None:
    deadline = time.monotonic() + duration
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        while time.monotonic() < deadline:
            tasks = []
            for _ in range(concurrency):
                prompt = random.choice(PROMPTS)
                if random.random() < 0.2:
                    tasks.append(post_stream(client, prompt))
                elif random.random() < 0.3:
                    tasks.append(post_feedback(client))
                else:
                    tasks.append(post_chat(client, prompt))
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0.2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8010")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    asyncio.run(run_load(args.base_url, args.duration, args.concurrency))


if __name__ == "__main__":
    main()
