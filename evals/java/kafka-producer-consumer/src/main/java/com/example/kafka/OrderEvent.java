package com.example.kafka;

public record OrderEvent(String orderId, String customerId, String region, int itemCount) {
}
