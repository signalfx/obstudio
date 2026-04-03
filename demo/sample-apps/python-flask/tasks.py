"""Celery background tasks for async payment processing."""

import logging

import requests
from celery import Celery

from config import Config

logger = logging.getLogger(__name__)

celery_app = Celery(
    "tasks",
    broker=Config.CELERY_BROKER_URL,
    backend=Config.CELERY_RESULT_BACKEND,
)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def process_payment(self, order_id, payment_token):
    """Call external payment gateway, update order status on success."""
    try:
        resp = requests.post(
            f"{Config.PAYMENT_GATEWAY_URL}/charge",
            json={"order_id": order_id, "token": payment_token},
            timeout=Config.PAYMENT_GATEWAY_TIMEOUT,
        )
        resp.raise_for_status()
        _mark_order_paid(order_id)
        logger.info("payment_success", extra={"order_id": order_id})
    except requests.RequestException as exc:
        logger.warning(
            "payment_failed",
            extra={"order_id": order_id, "error": str(exc)},
        )
        raise self.retry(exc=exc)


def _mark_order_paid(order_id):
    import psycopg2
    conn = psycopg2.connect(Config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE orders SET status = 'paid' WHERE id = %s", (order_id,)
            )
        conn.commit()
    finally:
        conn.close()
