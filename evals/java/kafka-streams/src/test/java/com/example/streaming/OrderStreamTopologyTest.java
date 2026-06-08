package com.example.streaming;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Properties;
import java.util.UUID;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.apache.kafka.streams.StreamsConfig;
import org.apache.kafka.streams.TestInputTopic;
import org.apache.kafka.streams.TestOutputTopic;
import org.apache.kafka.streams.TopologyTestDriver;
import org.junit.jupiter.api.Test;

class OrderStreamTopologyTest {

    private static final String HIGH_VALUE_ORDER = """
            {
              "orderId": "order-100",
              "customerId": "customer-22",
              "amount": 12500.0,
              "region": "us-west",
              "status": "SUBMITTED"
            }
            """;

    private static final String NORMAL_ORDER = """
            {
              "orderId": "order-101",
              "customerId": "customer-23",
              "amount": 125.0,
              "region": "us-west",
              "status": "SUBMITTED"
            }
            """;

    private static final String MANUAL_REVIEW_ORDER = """
            {
              "orderId": "order-102",
              "customerId": "customer-24",
              "amount": 75.0,
              "region": "us-east",
              "status": "MANUAL_REVIEW"
            }
            """;

    @Test
    void routesHighRiskOrdersToEnrichedAndFraudTopics() {
        StreamConfig config = testConfig();
        OrderStreamTopology topology = new OrderStreamTopology(
                new OrderEventParser(new ObjectMapper()),
                new RiskScorer(),
                config);

        try (TopologyTestDriver driver = new TopologyTestDriver(topology.build(), testProperties(config))) {
            TestInputTopic<String, String> orders = inputTopic(driver, config);
            TestOutputTopic<String, String> enriched = outputTopic(driver, config.enrichedOrdersTopic());
            TestOutputTopic<String, String> fraud = outputTopic(driver, config.fraudAlertsTopic());

            orders.pipeInput("order-100", HIGH_VALUE_ORDER);

            assertFalse(enriched.isEmpty(), "expected enriched output");
            assertFalse(fraud.isEmpty(), "expected fraud output");
            String enrichedPayload = enriched.readValue();
            String fraudPayload = fraud.readValue();
            assertTrue(enrichedPayload.contains("\"orderId\":\"order-100\""));
            assertTrue(fraudPayload.contains("\"highRisk\":true"));
            assertTrue(fraudPayload.contains("\"riskReason\":\"high-value-order\""));
        }
    }

    @Test
    void routesNormalOrdersOnlyToEnrichedTopic() {
        StreamConfig config = testConfig();
        OrderStreamTopology topology = new OrderStreamTopology(
                new OrderEventParser(new ObjectMapper()),
                new RiskScorer(),
                config);

        try (TopologyTestDriver driver = new TopologyTestDriver(topology.build(), testProperties(config))) {
            TestInputTopic<String, String> orders = inputTopic(driver, config);
            TestOutputTopic<String, String> enriched = outputTopic(driver, config.enrichedOrdersTopic());
            TestOutputTopic<String, String> fraud = outputTopic(driver, config.fraudAlertsTopic());

            orders.pipeInput("order-101", NORMAL_ORDER);

            assertFalse(enriched.isEmpty(), "expected enriched output");
            String enrichedPayload = enriched.readValue();
            assertTrue(enrichedPayload.contains("\"orderId\":\"order-101\""));
            assertTrue(enrichedPayload.contains("\"highRisk\":false"));
            assertTrue(fraud.isEmpty());
        }
    }

    @Test
    void routesManualReviewOrdersToFraudTopic() {
        StreamConfig config = testConfig();
        OrderStreamTopology topology = new OrderStreamTopology(
                new OrderEventParser(new ObjectMapper()),
                new RiskScorer(),
                config);

        try (TopologyTestDriver driver = new TopologyTestDriver(topology.build(), testProperties(config))) {
            TestInputTopic<String, String> orders = inputTopic(driver, config);
            TestOutputTopic<String, String> enriched = outputTopic(driver, config.enrichedOrdersTopic());
            TestOutputTopic<String, String> fraud = outputTopic(driver, config.fraudAlertsTopic());

            orders.pipeInput("order-102", MANUAL_REVIEW_ORDER);

            assertFalse(enriched.isEmpty(), "expected enriched output");
            assertFalse(fraud.isEmpty(), "expected fraud output");
            String enrichedPayload = enriched.readValue();
            String fraudPayload = fraud.readValue();
            assertTrue(enrichedPayload.contains("\"orderId\":\"order-102\""));
            assertTrue(fraudPayload.contains("\"highRisk\":true"));
            assertTrue(fraudPayload.contains("\"riskReason\":\"manual-review-status\""));
        }
    }

    @Test
    void dropsMalformedOrderEvents() {
        StreamConfig config = testConfig();
        OrderStreamTopology topology = new OrderStreamTopology(
                new OrderEventParser(new ObjectMapper()),
                new RiskScorer(),
                config);

        try (TopologyTestDriver driver = new TopologyTestDriver(topology.build(), testProperties(config))) {
            TestInputTopic<String, String> orders = inputTopic(driver, config);
            TestOutputTopic<String, String> enriched = outputTopic(driver, config.enrichedOrdersTopic());
            TestOutputTopic<String, String> fraud = outputTopic(driver, config.fraudAlertsTopic());

            orders.pipeInput("bad-order", "{not-json");

            assertTrue(enriched.isEmpty());
            assertTrue(fraud.isEmpty());
        }
    }

    @Test
    void dropsNullOrderEvents() {
        StreamConfig config = testConfig();
        OrderStreamTopology topology = new OrderStreamTopology(
                new OrderEventParser(new ObjectMapper()),
                new RiskScorer(),
                config);

        try (TopologyTestDriver driver = new TopologyTestDriver(topology.build(), testProperties(config))) {
            TestInputTopic<String, String> orders = inputTopic(driver, config);
            TestOutputTopic<String, String> enriched = outputTopic(driver, config.enrichedOrdersTopic());
            TestOutputTopic<String, String> fraud = outputTopic(driver, config.fraudAlertsTopic());

            orders.pipeInput("deleted-order", (String) null);

            assertTrue(enriched.isEmpty());
            assertTrue(fraud.isEmpty());
        }
    }

    private static StreamConfig testConfig() {
        return new StreamConfig(
                "dummy:9092",
                "order-risk-stream-test",
                "orders",
                "orders.enriched",
                "orders.fraud-alerts");
    }

    private static Properties testProperties(StreamConfig config) {
        Properties properties = config.toKafkaProperties();
        properties.put(StreamsConfig.APPLICATION_ID_CONFIG, config.applicationId() + "-" + UUID.randomUUID());
        return properties;
    }

    private static TestInputTopic<String, String> inputTopic(TopologyTestDriver driver, StreamConfig config) {
        return driver.createInputTopic(config.ordersTopic(), new StringSerializer(), new StringSerializer());
    }

    private static TestOutputTopic<String, String> outputTopic(TopologyTestDriver driver, String topic) {
        return driver.createOutputTopic(topic, new StringDeserializer(), new StringDeserializer());
    }
}
