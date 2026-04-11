import express from "express";

const app = express();
app.use(express.json());

let tasks = [
  { id: 1, title: "Buy groceries", done: false },
  { id: 2, title: "Walk the dog", done: true },
];
let nextId = 3;

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
  res.status(201).json(task);
});

app.patch("/tasks/:id", (req, res) => {
  const task = tasks.find((t) => t.id === Number(req.params.id));
  if (!task) return res.status(404).json({ error: "not found" });
  if (req.body.title !== undefined) task.title = req.body.title;
  if (req.body.done !== undefined) task.done = req.body.done;
  res.json(task);
});

app.delete("/tasks/:id", (req, res) => {
  const before = tasks.length;
  tasks = tasks.filter((t) => t.id !== Number(req.params.id));
  if (tasks.length === before) return res.status(404).json({ error: "not found" });
  res.status(204).end();
});

const port = process.env.PORT || 8000;
app.listen(port, () => {
  console.log(`listening on :${port}`);
});
