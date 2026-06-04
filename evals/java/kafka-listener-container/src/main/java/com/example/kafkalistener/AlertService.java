package com.example.kafkalistener;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.springframework.stereotype.Service;

@Service
public class AlertService {

    private final List<AlertSummary> processed = Collections.synchronizedList(new ArrayList<>());

    public AlertSummary process(AlertEvent event) {
        boolean pagingRequired = "CRITICAL".equalsIgnoreCase(event.severity());
        AlertSummary summary = new AlertSummary(event.alertId(), event.entityId(), pagingRequired);
        processed.add(summary);
        return summary;
    }

    public List<AlertSummary> processed() {
        return List.copyOf(processed);
    }
}
