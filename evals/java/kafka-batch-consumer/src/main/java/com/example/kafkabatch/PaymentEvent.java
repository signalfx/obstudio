package com.example.kafkabatch;

public record PaymentEvent(String paymentId, String accountId, double amount, String currency) {
}
