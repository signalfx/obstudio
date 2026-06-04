package com.example.kafkabatch;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class PaymentBatchConsumer implements AutoCloseable {

    private static final Logger logger = LoggerFactory.getLogger(PaymentBatchConsumer.class);

    private final KafkaConsumer<String, String> consumer;
    private final String paymentsTopic;
    private final PaymentBatchProcessor processor;

    public PaymentBatchConsumer(
            KafkaConsumer<String, String> consumer,
            String paymentsTopic,
            PaymentBatchProcessor processor) {
        this.consumer = consumer;
        this.paymentsTopic = paymentsTopic;
        this.processor = processor;
    }

    public void runForever() {
        consumer.subscribe(List.of(paymentsTopic));
        while (!Thread.currentThread().isInterrupted()) {
            pollBatch(Duration.ofSeconds(1));
        }
    }

    public BatchResult pollBatch(Duration timeout) {
        ConsumerRecords<String, String> records = consumer.poll(timeout);
        List<String> payloads = new ArrayList<>();
        for (ConsumerRecord<String, String> record : records) {
            payloads.add(record.value());
        }

        BatchResult result = processor.process(payloads);
        if (!payloads.isEmpty()) {
            consumer.commitSync();
            logger.info("Processed payment batch: {}", result);
        }
        return result;
    }

    @Override
    public void close() {
        consumer.close();
    }
}
