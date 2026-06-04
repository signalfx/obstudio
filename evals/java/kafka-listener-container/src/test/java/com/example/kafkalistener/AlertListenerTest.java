package com.example.kafkalistener;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

class AlertListenerTest {

    @Test
    void processesCriticalAlertPayload() {
        AlertService service = new AlertService();
        AlertListener listener = new AlertListener(service, new ObjectMapper());

        listener.onAlert("""
                {
                  "alertId": "alert-1",
                  "entityId": "entity-1",
                  "severity": "CRITICAL",
                  "message": "latency high"
                }
                """);

        assertEquals(1, service.processed().size());
        assertTrue(service.processed().getFirst().pagingRequired());
    }

    @Test
    void dropsMalformedAlertPayload() {
        AlertService service = new AlertService();
        AlertListener listener = new AlertListener(service, new ObjectMapper());

        listener.onAlert("{not-json");

        assertTrue(service.processed().isEmpty());
    }
}
