package com.example.kafka;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Duration;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.clients.producer.KafkaProducer;

public final class ProducerConsumerApplication {

    private ProducerConsumerApplication() {
    }

    public static void main(String[] args) {
        KafkaClientConfig config = KafkaClientConfig.fromEnvironment();
        OrderMessageHandler handler = new OrderMessageHandler(new ObjectMapper());

        KafkaProducer<String, String> producer = new KafkaProducer<>(config.producerProperties());
        KafkaConsumer<String, String> consumer;
        try {
            consumer = new KafkaConsumer<>(config.consumerProperties());
        } catch (RuntimeException | Error e) {
            producer.close(Duration.ofSeconds(5));
            throw e;
        }

        try (ShipmentProducer shipmentProducer = new ShipmentProducer(producer, config.shipmentsTopic());
                OrderConsumer orderConsumer = new OrderConsumer(consumer, config.ordersTopic(), handler, shipmentProducer)) {
            orderConsumer.runForever();
        }
    }
}
