"""Order Processing Service -- sample Flask app for /observe skill eval."""

from flask import Flask, jsonify, request

from config import Config
from db import get_db, close_db, init_db
from cache import redis_client
from tasks import process_payment
from services.orders import OrderService
from services.inventory import InventoryClient

app = Flask(__name__)
app.config.from_object(Config)
app.teardown_appcontext(close_db)

order_service = OrderService()
inventory_client = InventoryClient(app.config["INVENTORY_SERVICE_URL"])


@app.route("/health")
def health():
    return jsonify(status="ok")


@app.route("/orders", methods=["POST"])
def create_order():
    data = request.get_json(force=True)
    item_id = data["item_id"]
    quantity = data["quantity"]
    user_id = data["user_id"]

    available = inventory_client.check_stock(item_id, quantity)
    if not available:
        return jsonify(error="insufficient_stock"), 409

    db = get_db()
    order = order_service.create(db, user_id=user_id, item_id=item_id, quantity=quantity)

    redis_client.delete(f"user:{user_id}:orders")

    process_payment.delay(order["id"], data.get("payment_token"))

    return jsonify(order), 201


@app.route("/orders/<order_id>")
def get_order(order_id):
    cached = redis_client.get(f"order:{order_id}")
    if cached:
        import json
        return jsonify(json.loads(cached))

    db = get_db()
    order = order_service.get(db, order_id)
    if not order:
        return jsonify(error="not_found"), 404

    import json
    redis_client.setex(f"order:{order_id}", 300, json.dumps(order))
    return jsonify(order)


@app.route("/orders", methods=["GET"])
def list_orders():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify(error="user_id required"), 400

    cache_key = f"user:{user_id}:orders"
    cached = redis_client.get(cache_key)
    if cached:
        import json
        return jsonify(json.loads(cached))

    db = get_db()
    orders = order_service.list_by_user(db, user_id)

    import json
    redis_client.setex(cache_key, 60, json.dumps(orders))
    return jsonify(orders)


@app.cli.command("init-db")
def init_db_command():
    init_db()
    print("Database initialized.")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
