package com.example.kafkalistener;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;

import net.jpountz.lz4.LZ4BlockInputStream;
import net.jpountz.lz4.LZ4BlockOutputStream;
import net.jpountz.lz4.LZ4Compressor;
import net.jpountz.lz4.LZ4Factory;
import org.junit.jupiter.api.Test;

class Lz4CompatibilityTest {
    @Test
    void preservesNativeAndSafeCompressionRoundtrips() throws Exception {
        byte[] input = "compression compatibility ".repeat(1024).getBytes(StandardCharsets.UTF_8);
        for (LZ4Factory factory : new LZ4Factory[]{LZ4Factory.nativeInstance(), LZ4Factory.safeInstance()}) {
            for (LZ4Compressor compressor : new LZ4Compressor[]{factory.fastCompressor(), factory.highCompressor()}) {
                ByteArrayOutputStream buffer = new ByteArrayOutputStream();
                try (LZ4BlockOutputStream output = new LZ4BlockOutputStream(buffer, 65536, compressor)) {
                    output.write(input);
                }
                try (LZ4BlockInputStream decoded = new LZ4BlockInputStream(
                        new ByteArrayInputStream(buffer.toByteArray()), factory.fastDecompressor())) {
                    assertArrayEquals(input, decoded.readAllBytes());
                }
            }
        }
    }

    @Test
    void skipsConcatenatedEmptyBlocksWithoutStackGrowth() throws Exception {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        try (LZ4BlockOutputStream output = new LZ4BlockOutputStream(buffer)) {
            output.finish();
        }
        byte[] frame = buffer.toByteArray();
        byte[] input = new byte[frame.length * 30_000];
        for (int offset = 0; offset < input.length; offset += frame.length) {
            System.arraycopy(frame, 0, input, offset, frame.length);
        }
        try (LZ4BlockInputStream decoded = new LZ4BlockInputStream(new ByteArrayInputStream(input), false)) {
            assertEquals(-1, decoded.read());
        }
    }
}
