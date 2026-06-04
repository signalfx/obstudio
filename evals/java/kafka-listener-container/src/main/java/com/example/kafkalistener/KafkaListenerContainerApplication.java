package com.example.kafkalistener;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.kafka.annotation.EnableKafka;

@EnableKafka
@SpringBootApplication
public class KafkaListenerContainerApplication {

    public static void main(String[] args) {
        SpringApplication.run(KafkaListenerContainerApplication.class, args);
    }
}
