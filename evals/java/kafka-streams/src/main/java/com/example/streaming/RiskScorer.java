package com.example.streaming;

public final class RiskScorer {

    private static final double HIGH_VALUE_THRESHOLD = 10_000.0;

    public EnrichedOrder enrich(OrderEvent event) {
        boolean highRisk = isHighRisk(event);
        return new EnrichedOrder(
                event.orderId(),
                event.customerId(),
                event.amount(),
                event.region(),
                event.status(),
                highRisk,
                highRisk ? riskReason(event) : "none");
    }

    private boolean isHighRisk(OrderEvent event) {
        return event.amount() >= HIGH_VALUE_THRESHOLD || "MANUAL_REVIEW".equalsIgnoreCase(event.status());
    }

    private String riskReason(OrderEvent event) {
        if (event.amount() >= HIGH_VALUE_THRESHOLD) {
            return "high-value-order";
        }
        if ("MANUAL_REVIEW".equalsIgnoreCase(event.status())) {
            return "manual-review-status";
        }
        return "none";
    }
}
