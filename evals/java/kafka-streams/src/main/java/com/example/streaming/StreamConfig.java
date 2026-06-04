package com.example.streaming;

import java.util.Map;
import java.util.Properties;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.StreamsConfig;

public record StreamConfig(
        String bootstrapServers,
        String applicationId,
        String ordersTopic,
        String enrichedOrdersTopic,
        String fraudAlertsTopic) {

    public static StreamConfig fromEnvironment() {
        Map<String, String> env = System.getenv();
        return new StreamConfig(
                env.getOrDefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
                env.getOrDefault("KAFKA_APPLICATION_ID", "order-risk-stream"),
                env.getOrDefault("ORDERS_TOPIC", "orders"),
                env.getOrDefault("ENRICHED_ORDERS_TOPIC", "orders.enriched"),
                env.getOrDefault("FRAUD_ALERTS_TOPIC", "orders.fraud-alerts"));
    }

    public Properties toKafkaProperties() {
        Properties properties = new Properties();
        properties.put(StreamsConfig.APPLICATION_ID_CONFIG, applicationId);
        properties.put(StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrapServers);
        properties.put(StreamsConfig.DEFAULT_KEY_SERDE_CLASS_CONFIG, Serdes.StringSerde.class.getName());
        properties.put(StreamsConfig.DEFAULT_VALUE_SERDE_CLASS_CONFIG, Serdes.StringSerde.class.getName());
        properties.put(StreamsConfig.PROCESSING_GUARANTEE_CONFIG, StreamsConfig.AT_LEAST_ONCE);
        properties.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        return properties;
    }
}
