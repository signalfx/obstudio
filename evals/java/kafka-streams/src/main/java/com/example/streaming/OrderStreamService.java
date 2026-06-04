package com.example.streaming;

import com.google.inject.Inject;
import java.time.Duration;
import org.apache.kafka.streams.KafkaStreams;
import org.apache.kafka.streams.errors.StreamsUncaughtExceptionHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class OrderStreamService implements AutoCloseable {

    private static final Logger logger = LoggerFactory.getLogger(OrderStreamService.class);

    private final KafkaStreams streams;

    @Inject
    public OrderStreamService(KafkaStreams streams) {
        this.streams = streams;
    }

    public void start() {
        streams.setUncaughtExceptionHandler(exception -> {
            logger.error("Kafka Streams thread failed", exception);
            return StreamsUncaughtExceptionHandler.StreamThreadExceptionResponse.SHUTDOWN_CLIENT;
        });
        streams.start();
        logger.info("Order stream processor started");
    }

    @Override
    public void close() {
        streams.close(Duration.ofSeconds(10));
        logger.info("Order stream processor stopped");
    }
}
