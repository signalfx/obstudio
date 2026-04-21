import { metrics } from "@opentelemetry/api";
import express from "express";

const app = express();
app.use(express.json());

const meter = metrics.getMeter("node-express-basic");

const tasksCreated = meter.createCounter("tasks.created.count", {
  description: "Total tasks created",
  unit: "{tasks}",
});

const tasksCompleted = meter.createCounter("tasks.completed.count", {
  description: "Total tasks marked as done",
  unit: "{tasks}",
});

const tasksDeleted = meter.createCounter("tasks.deleted.count", {
  description: "Total tasks deleted",
  unit: "{tasks}",
});

let tasks = [
  { id: 1, title: "Buy groceries", done: false },
  { id: 2, title: "Walk the dog", done: true },
];
let nextId = 3;

meter
  .createObservableGauge("tasks.active.count", {
    description: "Current number of active tasks",
    unit: "{tasks}",
  })
  .addCallback((result) => {
    result.observe(tasks.length);
  });

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.get("/tasks", (_req, res) => {
  res.json(tasks);
});

app.get("/tasks/:id", (req, res) => {
  const task = tasks.find((t) => t.id === Number(req.params.id));
  if (!task) return res.status(404).json({ error: "not found" });
  res.json(task);
});

app.post("/tasks", (req, res) => {
  const task = { id: nextId++, title: req.body.title || "", done: false };
  tasks.push(task);
  tasksCreated.add(1);
  res.status(201).json(task);
});

app.patch("/tasks/:id", (req, res) => {
  const task = tasks.find((t) => t.id === Number(req.params.id));
  if (!task) return res.status(404).json({ error: "not found" });
  const wasDone = task.done;
  if (req.body.title !== undefined) task.title = req.body.title;
  if (req.body.done !== undefined) task.done = req.body.done;
  if (!wasDone && task.done) tasksCompleted.add(1);
  res.json(task);
});

app.delete("/tasks/:id", (req, res) => {
  const before = tasks.length;
  tasks = tasks.filter((t) => t.id !== Number(req.params.id));
  if (tasks.length === before)
    return res.status(404).json({ error: "not found" });
  tasksDeleted.add(1);
  res.status(204).end();
});

const port = process.env.PORT || 8000;
app.listen(port, () => {
  console.log(`listening on :${port}`);
});
