package com.example.kafkalistener;

public record AlertEvent(String alertId, String entityId, String severity, String message) {
}
