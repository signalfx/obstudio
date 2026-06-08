package com.example.kafka;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Optional;

public final class OrderMessageHandler {

    private final ObjectMapper objectMapper;

    public OrderMessageHandler(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public Optional<ShipmentCommand> toShipmentCommand(String payload) {
        if (payload == null) {
            return Optional.empty();
        }
        try {
            OrderEvent order = objectMapper.readValue(payload, OrderEvent.class);
            return Optional.of(new ShipmentCommand(
                    order.orderId(),
                    order.customerId(),
                    warehouseFor(order.region()),
                    order.itemCount()));
        } catch (JsonProcessingException e) {
            return Optional.empty();
        }
    }

    public String toJson(ShipmentCommand command) {
        try {
            return objectMapper.writeValueAsString(command);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException("Unable to serialize shipment command " + command.orderId(), e);
        }
    }

    private String warehouseFor(String region) {
        return switch (region) {
            case "us-east" -> "warehouse-a";
            case "eu" -> "warehouse-eu";
            default -> "warehouse-west";
        };
    }
}
