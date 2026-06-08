package com.example.streaming;

public record OrderEvent(
        String orderId,
        String customerId,
        double amount,
        String region,
        String status) {
}
