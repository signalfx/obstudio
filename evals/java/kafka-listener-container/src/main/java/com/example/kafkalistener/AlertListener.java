package com.example.kafkalistener;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Optional;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class AlertListener {

    private final AlertService service;
    private final ObjectMapper objectMapper;

    public AlertListener(AlertService service, ObjectMapper objectMapper) {
        this.service = service;
        this.objectMapper = objectMapper;
    }

    @KafkaListener(topics = "${alerts.topic:alerts}", groupId = "${alerts.group:alerts-worker}")
    public void onAlert(String payload) {
        parse(payload).ifPresent(service::process);
    }

    Optional<AlertEvent> parse(String payload) {
        if (payload == null) {
            return Optional.empty();
        }
        try {
            return Optional.of(objectMapper.readValue(payload, AlertEvent.class));
        } catch (JsonProcessingException e) {
            return Optional.empty();
        }
    }
}
