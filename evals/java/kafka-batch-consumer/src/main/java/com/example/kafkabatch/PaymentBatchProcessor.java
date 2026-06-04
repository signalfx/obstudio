package com.example.kafkabatch;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;

public final class PaymentBatchProcessor {

    private static final double HIGH_VALUE_THRESHOLD = 5_000.0;

    private final ObjectMapper objectMapper;

    public PaymentBatchProcessor(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public BatchResult process(List<String> payloads) {
        int valid = 0;
        int failed = 0;
        int highValue = 0;
        double totalAmount = 0.0;

        for (String payload : payloads) {
            PaymentEvent payment = parse(payload);
            if (payment == null) {
                failed++;
                continue;
            }
            valid++;
            totalAmount += payment.amount();
            if (payment.amount() >= HIGH_VALUE_THRESHOLD) {
                highValue++;
            }
        }

        return new BatchResult(payloads.size(), valid, failed, highValue, totalAmount);
    }

    private PaymentEvent parse(String payload) {
        if (payload == null) {
            return null;
        }
        try {
            return objectMapper.readValue(payload, PaymentEvent.class);
        } catch (JsonProcessingException e) {
            return null;
        }
    }
}
