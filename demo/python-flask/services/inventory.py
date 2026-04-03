"""Client for the external Inventory Service."""

import logging

import requests

logger = logging.getLogger(__name__)


class InventoryClient:

    def __init__(self, base_url, timeout=3):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def check_stock(self, item_id, quantity):
        try:
            resp = requests.get(
                f"{self.base_url}/items/{item_id}/stock",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("available", 0) >= quantity
        except requests.RequestException:
            logger.exception("inventory_check_failed")
            return False

    def reserve(self, item_id, quantity):
        resp = requests.post(
            f"{self.base_url}/items/{item_id}/reserve",
            json={"quantity": quantity},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
