package com.example.streaming;

import com.google.inject.Guice;
import com.google.inject.Injector;

public final class KafkaStreamsApplication {

    private KafkaStreamsApplication() {
    }

    public static void main(String[] args) throws InterruptedException {
        Injector injector = Guice.createInjector(new StreamProcessingModule());
        OrderStreamService service = injector.getInstance(OrderStreamService.class);
        Runtime.getRuntime().addShutdownHook(new Thread(service::close, "streams-shutdown"));

        service.start();
        Thread.currentThread().join();
    }
}
