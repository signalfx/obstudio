package com.example.streaming;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.inject.Inject;
import java.util.Optional;

public final class OrderEventParser {

    private final ObjectMapper objectMapper;

    @Inject
    public OrderEventParser(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public Optional<OrderEvent> parse(String payload) {
        if (payload == null) {
            return Optional.empty();
        }
        try {
            return Optional.of(objectMapper.readValue(payload, OrderEvent.class));
        } catch (JsonProcessingException e) {
            return Optional.empty();
        }
    }

    public String toJson(EnrichedOrder order) {
        try {
            return objectMapper.writeValueAsString(order);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException("Unable to serialize enriched order " + order.orderId(), e);
        }
    }
}
