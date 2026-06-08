package com.example.kafkabatch;

import java.util.Map;
import java.util.Properties;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.common.serialization.StringDeserializer;

public record BatchConsumerConfig(String bootstrapServers, String paymentsTopic, String consumerGroup) {

    public static BatchConsumerConfig fromEnvironment() {
        Map<String, String> env = System.getenv();
        return new BatchConsumerConfig(
                env.getOrDefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
                env.getOrDefault("PAYMENTS_TOPIC", "payments"),
                env.getOrDefault("KAFKA_CONSUMER_GROUP", "payment-batch-worker"));
    }

    public Properties consumerProperties() {
        Properties properties = new Properties();
        properties.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrapServers);
        properties.put(ConsumerConfig.GROUP_ID_CONFIG, consumerGroup);
        properties.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        properties.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        properties.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        properties.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
        properties.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG, "500");
        return properties;
    }
}
