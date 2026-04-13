from otel_setup import configure_opentelemetry

configure_opentelemetry()

from opentelemetry import metrics, trace  # noqa: E402
from opentelemetry.instrumentation.flask import FlaskInstrumentor  # noqa: E402
from opentelemetry.metrics import Observation  # noqa: E402

from flask import Flask, jsonify, request  # noqa: E402

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)

tracer = trace.get_tracer("python-flask-basic.tasks")
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
tasks_deleted = meter.create_counter(
    "tasks.deleted.count",
    description="Total tasks deleted",
    unit="{tasks}",
)

tasks = [
    {"id": 1, "title": "Buy groceries", "done": False},
    {"id": 2, "title": "Walk the dog", "done": True},
]
next_id = 3


def _observe_active_task_count(_options):
    return [Observation(len(tasks))]


meter.create_observable_gauge(
    "tasks.active.count",
    callbacks=[_observe_active_task_count],
    description="Current number of tasks in the store",
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
        span = trace.get_current_span()
        span.set_status(trace.StatusCode.ERROR, "task not found")
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
        span = trace.get_current_span()
        span.set_status(trace.StatusCode.ERROR, "task not found")
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
        span = trace.get_current_span()
        span.set_status(trace.StatusCode.ERROR, "task not found")
        return {"error": "not found"}, 404
    tasks_deleted.add(1)
    return "", 204
