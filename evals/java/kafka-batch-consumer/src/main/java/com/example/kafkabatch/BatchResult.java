package com.example.kafkabatch;

public record BatchResult(int totalRecords, int validRecords, int failedRecords, int highValuePayments, double totalAmount) {
}
