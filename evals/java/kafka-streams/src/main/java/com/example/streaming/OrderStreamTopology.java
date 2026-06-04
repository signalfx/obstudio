package com.example.streaming;

import com.google.inject.Inject;
import java.util.List;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.StreamsBuilder;
import org.apache.kafka.streams.Topology;
import org.apache.kafka.streams.kstream.Consumed;
import org.apache.kafka.streams.kstream.KStream;
import org.apache.kafka.streams.kstream.Produced;

public final class OrderStreamTopology {

    private final OrderEventParser parser;
    private final RiskScorer riskScorer;
    private final StreamConfig config;

    @Inject
    public OrderStreamTopology(OrderEventParser parser, RiskScorer riskScorer, StreamConfig config) {
        this.parser = parser;
        this.riskScorer = riskScorer;
        this.config = config;
    }

    public Topology build() {
        StreamsBuilder builder = new StreamsBuilder();
        KStream<String, String> rawOrders = builder.stream(
                config.ordersTopic(),
                Consumed.with(Serdes.String(), Serdes.String()));

        KStream<String, EnrichedOrder> enrichedOrders = rawOrders.flatMapValues(payload ->
                parser.parse(payload)
                        .map(riskScorer::enrich)
                        .map(List::of)
                        .orElseGet(List::of));

        enrichedOrders
                .mapValues(parser::toJson)
                .to(config.enrichedOrdersTopic(), Produced.with(Serdes.String(), Serdes.String()));

        enrichedOrders
                .filter((key, order) -> order.highRisk())
                .mapValues(parser::toJson)
                .to(config.fraudAlertsTopic(), Produced.with(Serdes.String(), Serdes.String()));

        return builder.build();
    }
}
