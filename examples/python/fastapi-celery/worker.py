import os
import time

from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("worker", broker=redis_url, backend=redis_url)
celery_app.conf.task_track_started = True


@celery_app.task(name="worker.fulfill_order")
def fulfill_order(order_id: str, product: str, quantity: int):
    time.sleep(1)
    return {"order_id": order_id, "product": product, "quantity": quantity, "fulfilled": True}


@celery_app.task(name="worker.send_notification")
def send_notification(order_id: str, channel: str = "email"):
    time.sleep(0.5)
    return {"order_id": order_id, "channel": channel, "sent": True}
