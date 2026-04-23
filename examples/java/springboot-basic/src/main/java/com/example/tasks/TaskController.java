package com.example.tasks;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class TaskController {

    private final List<Task> tasks = Collections.synchronizedList(new ArrayList<>(List.of(
            new Task(1, "Buy groceries", false),
            new Task(2, "Walk the dog", true)
    )));
    private final AtomicInteger nextId = new AtomicInteger(3);

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "ok");
    }

    @GetMapping("/tasks")
    public List<Task> list() {
        return tasks;
    }

    @GetMapping("/tasks/{id}")
    public ResponseEntity<?> get(@PathVariable int id) {
        return tasks.stream()
                .filter(t -> t.getId() == id)
                .findFirst()
                .<ResponseEntity<?>>map(ResponseEntity::ok)
                .orElse(ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(Map.of("error", "not found")));
    }

    @PostMapping("/tasks")
    public ResponseEntity<Task> create(@RequestBody Map<String, String> body) {
        Task task = new Task(nextId.getAndIncrement(), body.get("title"), false);
        tasks.add(task);
        return ResponseEntity.status(HttpStatus.CREATED).body(task);
    }

    @PatchMapping("/tasks/{id}")
    public ResponseEntity<?> update(@PathVariable int id, @RequestBody Map<String, Object> body) {
        synchronized (tasks) {
            for (Task t : tasks) {
                if (t.getId() == id) {
                    if (body.containsKey("title")) {
                        t.setTitle((String) body.get("title"));
                    }
                    if (body.containsKey("done")) {
                        t.setDone((Boolean) body.get("done"));
                    }
                    return ResponseEntity.ok(t);
                }
            }
        }
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Map.of("error", "not found"));
    }

    @DeleteMapping("/tasks/{id}")
    public ResponseEntity<Void> delete(@PathVariable int id) {
        synchronized (tasks) {
            boolean removed = tasks.removeIf(t -> t.getId() == id);
            if (removed) {
                return ResponseEntity.noContent().build();
            }
        }
        return ResponseEntity.notFound().build();
    }
}
