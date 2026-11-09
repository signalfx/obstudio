package com.example.kafkalistener;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.logging.log4j.message.MapMessage;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.function.Executable;
import org.xerial.snappy.Snappy;
import org.xerial.snappy.SnappyInputStream;
import org.xerial.snappy.SnappyOutputStream;

class DependencySecurityTest {
    @Test
    void snappyPreservesNativeAndStreamRoundtrips() throws Exception {
        byte[] input = "compression compatibility ".repeat(1024).getBytes(StandardCharsets.UTF_8);
        assertArrayEquals(input, Snappy.uncompress(Snappy.compress(input)));
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        try (SnappyOutputStream output = new SnappyOutputStream(buffer)) {
            output.write(input);
        }
        try (SnappyInputStream decoded = new SnappyInputStream(new ByteArrayInputStream(buffer.toByteArray()))) {
            assertArrayEquals(input, decoded.readAllBytes());
        }
    }

    @Test
    void snappyRejectsInvalidCopyRangesBeforeNativeCopy() throws Exception {
        byte[] source = {1, 2, 3};
        byte[] target = new byte[3];
        Snappy.arrayCopy(source, 0, source.length, target, 0);
        assertArrayEquals(source, target);
        assertInvalidRange(() -> Snappy.arrayCopy(source, -1, 1, target, 0));
        assertInvalidRange(() -> Snappy.arrayCopy(source, 0, -1, target, 0));
        assertInvalidRange(() -> Snappy.arrayCopy(source, 0, Integer.MAX_VALUE, target, 0));
        assertInvalidRange(() -> Snappy.arrayCopy(source, 0, 1, target, target.length));
    }

    @Test
    void log4jMapMessageProducesStrictJsonForNonFiniteNumbers() {
        ObjectMapper mapper = new ObjectMapper();
        for (double value : new double[]{Double.NaN, Double.POSITIVE_INFINITY, Double.NEGATIVE_INFINITY}) {
            var message = new MapMessage<>(Map.of("number", value));
            String json = message.getFormattedMessage(new String[]{"JSON"});
            assertDoesNotThrow(() -> mapper.readTree(json));
        }
    }

    private static void assertInvalidRange(Executable operation) {
        RuntimeException failure = assertThrows(RuntimeException.class, operation);
        assertTrue(failure instanceof IndexOutOfBoundsException || failure instanceof IllegalArgumentException);
    }
}
