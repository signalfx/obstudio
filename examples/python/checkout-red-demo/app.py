import random
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Checkout API")

CART_ITEMS = [
    {"sku": "sku-1", "name": "Widget", "price_cents": 1999},
    {"sku": "sku-2", "name": "Gadget", "price_cents": 4999},
]

orders: dict[str, dict] = {}


class CheckoutRequest(BaseModel):
    skus: list[str]


class PaymentRequest(BaseModel):
    order_id: str
    card_token: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/cart")
def get_cart():
    time.sleep(random.uniform(0.005, 0.02))
    return {"items": CART_ITEMS}


@app.post("/checkout", status_code=201)
def do_checkout(body: CheckoutRequest):
    time.sleep(random.uniform(0.01, 0.05))
    total_cents = sum(item["price_cents"] for item in CART_ITEMS if item["sku"] in body.skus)
    order_id = str(uuid.uuid4())[:8]
    orders[order_id] = {"id": order_id, "skus": body.skus, "total_cents": total_cents, "status": "pending"}
    return orders[order_id]


@app.post("/payment")
def do_payment(body: PaymentRequest):
    order = orders.get(body.order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")

    time.sleep(random.uniform(0.02, 0.15))
    if random.random() < 0.15:
        order["status"] = "payment_failed"
        raise HTTPException(status_code=502, detail="payment gateway timeout")

    order["status"] = "paid"
    return order
