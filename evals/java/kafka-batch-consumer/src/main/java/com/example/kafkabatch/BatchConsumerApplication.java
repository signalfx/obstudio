package com.example.kafkabatch;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.kafka.clients.consumer.KafkaConsumer;

public final class BatchConsumerApplication {

    private BatchConsumerApplication() {
    }

    public static void main(String[] args) {
        BatchConsumerConfig config = BatchConsumerConfig.fromEnvironment();
        PaymentBatchProcessor processor = new PaymentBatchProcessor(new ObjectMapper());

        KafkaConsumer<String, String> consumer = new KafkaConsumer<>(config.consumerProperties());
        try (PaymentBatchConsumer batchConsumer = new PaymentBatchConsumer(consumer, config.paymentsTopic(), processor)) {
            batchConsumer.runForever();
        }
    }
}
