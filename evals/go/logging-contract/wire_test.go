package loggingcontract

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp"
	"go.opentelemetry.io/otel/trace"
)

type wireReceipt struct {
	Requests int `json:"requests"`
	Received int `json:"received"`
	Accepted int `json:"accepted"`
	Rejected int `json:"rejected"`
	Pending  int `json:"pending"`
	Spans    []struct {
		TraceID      string         `json:"trace_id"`
		SpanID       string         `json:"span_id"`
		ParentSpanID string         `json:"parent_span_id"`
		Resource     map[string]any `json:"resource"`
	} `json:"spans"`
	Records []struct {
		Body struct {
			String string `json:"stringValue"`
		} `json:"body"`
		TraceID   string         `json:"trace_id"`
		SpanID    string         `json:"span_id"`
		Flags     int            `json:"flags"`
		Severity  int            `json:"severity"`
		Timestamp string         `json:"timestamp_unix_nano"`
		Resource  map[string]any `json:"resource"`
	} `json:"records"`
}

func wireCase(t *testing.T, scenario string) {
	t.Helper()
	base := os.Getenv("LOGGING_CONTRACT_RECEIVER_URL")
	if base == "" {
		t.Skip("Use run_logging_contract.py for the owned loopback receiver")
	}
	parsed, err := url.Parse(base)
	if err != nil || parsed.Hostname() != "127.0.0.1" {
		t.Fatal("wire fixture requires loopback receiver")
	}
	origin := base[:strings.LastIndex(base, "/")]
	key := base[strings.LastIndex(base, "/")+1:]
	client := &http.Client{Timeout: time.Second}
	get := func(path string) wireReceipt {
		t.Helper()
		response, err := client.Get(origin + "/" + path)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		var receipt wireReceipt
		if response.StatusCode != http.StatusOK {
			t.Fatal(response.Status)
		}
		if err := json.NewDecoder(io.LimitReader(response.Body, 1048576)).Decode(&receipt); err != nil {
			t.Fatal(err)
		}
		return receipt
	}
	if scenario == "stall" {
		defer get("release-stall/" + key + "/" + scenario)
	}
	memory := &exporter{}
	_, logger, sink := faultPath(t, memory, false)
	otlp, err := otlploghttp.New(context.Background(), otlploghttp.WithEndpointURL(base+"/"+scenario+"/v1/logs"), otlploghttp.WithTimeout(200*time.Millisecond))
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		defer cancel()
		if err := otlp.Shutdown(ctx); err != nil {
			t.Error(err)
		}
	}()
	expected := 3
	if scenario == "stall" {
		expected = 1
	}
	var tid trace.TraceID
	var sid trace.SpanID
	for i := range tid {
		tid[i] = 0x11
	}
	for i := range sid {
		sid[i] = 0x22
	}
	parent := trace.ContextWithSpanContext(context.Background(), trace.NewSpanContext(trace.SpanContextConfig{TraceID: tid, SpanID: sid}))
	for i := 0; i < expected; i++ {
		logger.ErrorContext(parent, fmt.Sprintf("wire-%d", i))
	}
	started := time.Now()
	exportContext, cancelExport := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancelExport()
	exportErr := otlp.Export(exportContext, memory.records)
	if time.Since(started) >= 2*time.Second {
		t.Fatal("export timeout was not bounded")
	}
	receipt := get("evidence/" + key + "/" + scenario)
	if receipt.Received != expected {
		t.Fatalf("received=%d expected=%d", receipt.Received, expected)
	}
	for i, record := range receipt.Records {
		timestamp, err := strconv.ParseUint(record.Timestamp, 10, 64)
		if record.Body.String != fmt.Sprintf("wire-%d", i) || record.TraceID != tid.String() || record.SpanID != sid.String() || record.Flags&0xff != 0 || record.Severity != 17 || err != nil || timestamp != uint64(memory.records[i].Timestamp().UnixNano()) {
			t.Fatal("wire record lost source semantics or unsampled context")
		}
	}
	if scenario == "stall" {
		if exportErr == nil || receipt.Accepted != 0 || receipt.Pending != 1 {
			t.Fatal("timed-out export was incorrectly treated as accepted")
		}
		get("release-stall/" + key + "/" + scenario)
		deadline := time.Now().Add(time.Second)
		for receipt.Pending > 0 && time.Now().Before(deadline) {
			time.Sleep(10 * time.Millisecond)
			receipt = get("evidence/" + key + "/" + scenario)
		}
		if receipt.Accepted != 1 {
			t.Fatal("expected late acceptance despite client timeout")
		}
	} else {
		if scenario == "healthy" && exportErr != nil {
			t.Fatal(exportErr)
		}
		accepted, rejected := 3, 0
		if scenario == "partial" {
			accepted, rejected = 1, 2
			if exportErr == nil || !strings.Contains(exportErr.Error(), "2 logs rejected") {
				t.Fatalf("partial rejection not surfaced: %v", exportErr)
			}
		}
		if receipt.Requests != 1 || receipt.Accepted != accepted || receipt.Rejected != rejected {
			t.Fatal("full acceptance/retry falsely inferred from HTTP 200")
		}
	}
	if strings.Count(sink.String(), "\n") != expected {
		t.Fatal("original sink lost a record")
	}
	logger.Info("application continued")
	if !strings.Contains(sink.String(), "application continued") {
		t.Fatal("export failure stopped application logging")
	}
}

func TestOTLPWireHealthyReceipt(t *testing.T)        { wireCase(t, "healthy") }
func TestOTLPWirePartialSuccess(t *testing.T)        { wireCase(t, "partial") }
func TestOTLPWireTimeoutLateAcceptance(t *testing.T) { wireCase(t, "stall") }
