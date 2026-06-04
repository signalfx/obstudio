package com.example.kafka;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class OrderMessageHandlerTest {

    private final OrderMessageHandler handler = new OrderMessageHandler(new ObjectMapper());

    @Test
    void buildsShipmentCommandForValidOrder() {
        Optional<ShipmentCommand> command = handler.toShipmentCommand("""
                {
                  "orderId": "order-1",
                  "customerId": "customer-1",
                  "region": "us-east",
                  "itemCount": 3
                }
                """);

        assertTrue(command.isPresent());
        assertEquals("warehouse-a", command.get().warehouse());
        assertEquals(3, command.get().itemCount());
    }

    @Test
    void dropsMalformedOrders() {
        assertTrue(handler.toShipmentCommand("{not-json").isEmpty());
    }

    @Test
    void dropsNullOrders() {
        assertTrue(handler.toShipmentCommand(null).isEmpty());
    }
}
