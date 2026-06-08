package com.example.streaming;

public record EnrichedOrder(
        String orderId,
        String customerId,
        double amount,
        String region,
        String status,
        boolean highRisk,
        String riskReason) {
}
