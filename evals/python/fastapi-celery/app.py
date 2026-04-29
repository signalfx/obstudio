import os
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from worker import celery_app

app = FastAPI(title="Order Service")

orders: dict[str, dict] = {}


class OrderCreate(BaseModel):
    product: str
    quantity: int = 1


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/orders")
def list_orders():
    return list(orders.values())


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.post("/orders", status_code=201)
def create_order(body: OrderCreate):
    order_id = str(uuid.uuid4())[:8]
    order = {
        "id": order_id,
        "product": body.product,
        "quantity": body.quantity,
        "status": "pending",
    }
    orders[order_id] = order

    celery_app.send_task("worker.fulfill_order", args=[order_id, body.product, body.quantity])
    return order


@app.delete("/orders/{order_id}", status_code=204)
def cancel_order(order_id: str):
    if order_id not in orders:
        raise HTTPException(status_code=404, detail="order not found")
    orders[order_id]["status"] = "cancelled"
    return None
