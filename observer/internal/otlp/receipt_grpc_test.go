package otlp

import (
	"context"
	"sync"
	"testing"
	"time"

	"go.opentelemetry.io/collector/pdata/plog/plogotlp"
	"go.opentelemetry.io/collector/pdata/pmetric/pmetricotlp"
	"go.opentelemetry.io/collector/pdata/ptrace/ptraceotlp"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	"github.com/signalfx/obstudio/observer/internal/store"
)

// TestGRPCReceiptReachesStoreReceiptCallback drives one OTLP/gRPC payload per
// signal and checks each reaches the same store receipt callback as OTLP/HTTP.
func TestGRPCReceiptReachesStoreReceiptCallback(t *testing.T) {
	s := store.New()
	var mu sync.Mutex
	var receipts []store.Receipt
	s.SetReceiptCallback(func(r store.Receipt) {
		mu.Lock()
		receipts = append(receipts, r)
		mu.Unlock()
	})
	r, err := StartReceiver(context.Background(), s, "127.0.0.1:0", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer r.Shutdown(context.Background())
	conn, err := grpc.NewClient(r.connTracker.grpcLn.Addr().String(), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if _, err := ptraceotlp.NewGRPCClient(conn).Export(ctx, ptraceotlp.NewExportRequestFromTraces(createTestSpan())); err != nil {
		t.Fatal(err)
	}
	if _, err := pmetricotlp.NewGRPCClient(conn).Export(ctx, pmetricotlp.NewExportRequestFromMetrics(createTestMetric())); err != nil {
		t.Fatal(err)
	}
	if _, err := plogotlp.NewGRPCClient(conn).Export(ctx, plogotlp.NewExportRequestFromLogs(createTestLog())); err != nil {
		t.Fatal(err)
	}

	mu.Lock()
	defer mu.Unlock()
	var spans, metrics, logs int
	for _, rc := range receipts {
		spans += len(rc.Spans)
		metrics += len(rc.Metrics)
		logs += len(rc.Logs)
	}
	if len(receipts) != 3 || spans == 0 || metrics == 0 || logs == 0 {
		t.Fatalf("gRPC receipts = %d (spans %d, metrics %d, logs %d), want one per signal", len(receipts), spans, metrics, logs)
	}
}
