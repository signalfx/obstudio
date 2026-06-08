package com.example.kafkalistener;

public record AlertSummary(String alertId, String entityId, boolean pagingRequired) {
}
