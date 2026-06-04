package com.example.kafkabatch;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Arrays;
import org.junit.jupiter.api.Test;

class PaymentBatchProcessorTest {

    private final PaymentBatchProcessor processor = new PaymentBatchProcessor(new ObjectMapper());

    @Test
    void summarizesValidFailedAndHighValuePayments() {
        BatchResult result = processor.process(Arrays.asList(
                """
                {"paymentId":"payment-1","accountId":"acct-1","amount":25.0,"currency":"USD"}
                """,
                """
                {"paymentId":"payment-2","accountId":"acct-2","amount":7500.0,"currency":"USD"}
                """,
                "{not-json",
                null));

        assertEquals(4, result.totalRecords());
        assertEquals(2, result.validRecords());
        assertEquals(2, result.failedRecords());
        assertEquals(1, result.highValuePayments());
        assertEquals(7525.0, result.totalAmount());
    }
}
