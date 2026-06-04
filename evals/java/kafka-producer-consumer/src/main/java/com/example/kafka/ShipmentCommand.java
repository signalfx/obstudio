package com.example.kafka;

public record ShipmentCommand(String orderId, String customerId, String warehouse, int itemCount) {
}
