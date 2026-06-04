package com.example.kafka;

import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerRecord;

public final class ShipmentProducer implements AutoCloseable {

    private final KafkaProducer<String, String> producer;
    private final String topic;

    public ShipmentProducer(KafkaProducer<String, String> producer, String topic) {
        this.producer = producer;
        this.topic = topic;
    }

    public void send(ShipmentCommand command, String payload) {
        producer.send(new ProducerRecord<>(topic, command.orderId(), payload));
    }

    @Override
    public void close() {
        producer.flush();
        producer.close();
    }
}
