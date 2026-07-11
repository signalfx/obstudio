import argparse
import random
import time

import httpx


def run(base_url: str, duration: float) -> None:
    deadline = time.monotonic() + duration
    with httpx.Client(base_url=base_url, timeout=5.0) as client:
        while time.monotonic() < deadline:
            client.get("/cart")
            checkout = client.post("/checkout", json={"skus": ["sku-1", "sku-2"]})
            order_id = checkout.json()["id"]
            client.post("/payment", json={"order_id": order_id, "card_token": "tok_demo"})
            time.sleep(random.uniform(0.05, 0.2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8030")
    parser.add_argument("--duration", type=float, default=60)
    args = parser.parse_args()
    run(args.base_url, args.duration)
