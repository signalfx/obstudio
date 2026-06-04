package com.example.kafka;

import java.time.Duration;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;

public final class OrderConsumer implements AutoCloseable {

    private final KafkaConsumer<String, String> consumer;
    private final String ordersTopic;
    private final OrderMessageHandler handler;
    private final ShipmentProducer producer;

    public OrderConsumer(
            KafkaConsumer<String, String> consumer,
            String ordersTopic,
            OrderMessageHandler handler,
            ShipmentProducer producer) {
        this.consumer = consumer;
        this.ordersTopic = ordersTopic;
        this.handler = handler;
        this.producer = producer;
    }

    public void runForever() {
        consumer.subscribe(java.util.List.of(ordersTopic));
        while (!Thread.currentThread().isInterrupted()) {
            pollOnce(Duration.ofMillis(500));
        }
    }

    public int pollOnce(Duration timeout) {
        ConsumerRecords<String, String> records = consumer.poll(timeout);
        int produced = 0;
        for (ConsumerRecord<String, String> record : records) {
            produced += handleRecord(record);
        }
        return produced;
    }

    private int handleRecord(ConsumerRecord<String, String> record) {
        return handler.toShipmentCommand(record.value())
                .map(command -> {
                    producer.send(command, handler.toJson(command));
                    return 1;
                })
                .orElse(0);
    }

    @Override
    public void close() {
        consumer.close();
    }
}
