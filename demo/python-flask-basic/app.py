from otel_setup import configure_opentelemetry

configure_opentelemetry()

from opentelemetry import metrics
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.metrics import Observation
from flask import Flask, jsonify, request

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)

meter = metrics.get_meter("python-flask-basic")

tasks_created = meter.create_counter(
    "tasks.created.count",
    description="Total tasks created",
    unit="{tasks}",
)
tasks_completed = meter.create_counter(
    "tasks.completed.count",
    description="Total tasks marked as done",
    unit="{tasks}",
)

tasks = [
    {"id": 1, "title": "Buy groceries", "done": False},
    {"id": 2, "title": "Walk the dog", "done": True},
]
next_id = 3


def _get_task_count():
    return len(tasks)


def _observe_task_count(_options):
    yield Observation(value=_get_task_count())


meter.create_observable_gauge(
    "tasks.collection.size",
    callbacks=[_observe_task_count],
    description="Current number of tasks in the collection",
    unit="{tasks}",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/tasks")
def list_tasks():
    return jsonify(tasks)


@app.get("/tasks/<int:task_id>")
def get_task(task_id):
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        return {"error": "not found"}, 404
    return jsonify(task)


@app.post("/tasks")
def create_task():
    global next_id
    body = request.get_json(force=True)
    task = {"id": next_id, "title": body.get("title", ""), "done": False}
    next_id += 1
    tasks.append(task)
    tasks_created.add(1)
    return jsonify(task), 201


@app.patch("/tasks/<int:task_id>")
def update_task(task_id):
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        return {"error": "not found"}, 404
    body = request.get_json(force=True)
    task["title"] = body.get("title", task["title"])
    was_done = task["done"]
    task["done"] = body.get("done", task["done"])
    if not was_done and task["done"]:
        tasks_completed.add(1)
    return jsonify(task)


@app.delete("/tasks/<int:task_id>")
def delete_task(task_id):
    global tasks
    before = len(tasks)
    tasks = [t for t in tasks if t["id"] != task_id]
    if len(tasks) == before:
        return {"error": "not found"}, 404
    return "", 204
