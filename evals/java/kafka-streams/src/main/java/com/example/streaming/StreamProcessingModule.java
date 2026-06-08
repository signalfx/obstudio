package com.example.streaming;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.inject.AbstractModule;
import com.google.inject.Provides;
import com.google.inject.Singleton;
import org.apache.kafka.streams.KafkaStreams;

public final class StreamProcessingModule extends AbstractModule {

    @Override
    protected void configure() {
        bind(StreamConfig.class).toInstance(StreamConfig.fromEnvironment());
        bind(OrderEventParser.class).in(Singleton.class);
        bind(RiskScorer.class).in(Singleton.class);
        bind(OrderStreamTopology.class).in(Singleton.class);
        bind(OrderStreamService.class).in(Singleton.class);
    }

    @Provides
    @Singleton
    ObjectMapper objectMapper() {
        return new ObjectMapper();
    }

    @Provides
    @Singleton
    KafkaStreams kafkaStreams(StreamConfig config, OrderStreamTopology topology) {
        return new KafkaStreams(topology.build(), config.toKafkaProperties());
    }
}
