package com.example.kafka;

import java.util.List;
import java.util.Map;
import java.util.Properties;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;

public record KafkaClientConfig(
        String bootstrapServers,
        String ordersTopic,
        String shipmentsTopic,
        String consumerGroup) {

    public static KafkaClientConfig fromEnvironment() {
        Map<String, String> env = System.getenv();
        return new KafkaClientConfig(
                env.getOrDefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
                env.getOrDefault("ORDERS_TOPIC", "orders"),
                env.getOrDefault("SHIPMENTS_TOPIC", "shipments"),
                env.getOrDefault("KAFKA_CONSUMER_GROUP", "shipment-worker"));
    }

    public Properties producerProperties() {
        Properties properties = new Properties();
        properties.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrapServers);
        properties.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        properties.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        properties.put(ProducerConfig.ACKS_CONFIG, "all");
        return properties;
    }

    public Properties consumerProperties() {
        Properties properties = new Properties();
        properties.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrapServers);
        properties.put(ConsumerConfig.GROUP_ID_CONFIG, consumerGroup);
        properties.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        properties.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        properties.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        return properties;
    }

    public List<String> orderTopicSubscription() {
        return List.of(ordersTopic);
    }
}
