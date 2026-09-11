package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/freeaccount"
	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
)

type cancelAwareFreeAccountSubmitter struct {
	started  chan struct{}
	canceled chan struct{}
}

type failingStdioWriter struct {
	attempted chan struct{}
	once      sync.Once
}

type saturatingFreeAccountSubmitter struct {
	started chan struct{}
}

type keyedCancelFreeAccountSubmitter struct {
	started  chan string
	canceled chan string
}

type channelStdioWriter struct {
	writes chan []byte
}

func (w *failingStdioWriter) Write([]byte) (int, error) {
	w.once.Do(func() { close(w.attempted) })
	return 0, errors.New("stdio output closed")
}

func (w *channelStdioWriter) Write(data []byte) (int, error) {
	copyOfData := append([]byte(nil), data...)
	w.writes <- copyOfData
	return len(data), nil
}

func (f *cancelAwareFreeAccountSubmitter) Submit(ctx context.Context, _ freeaccount.Request) (freeaccount.Result, error) {
	close(f.started)
	<-ctx.Done()
	close(f.canceled)
	return freeaccount.Result{}, &freeaccount.Error{
		Code:      freeaccount.ErrorCodeCanceled,
		Message:   "The signup request was canceled before it was sent.",
		RetrySafe: true,
	}
}

func (f *cancelAwareFreeAccountSubmitter) DetectRegion(context.Context) freeaccount.RegionResult {
	return freeaccount.RegionResult{Region: "us"}
}

func (s *saturatingFreeAccountSubmitter) Submit(ctx context.Context, _ freeaccount.Request) (freeaccount.Result, error) {
	s.started <- struct{}{}
	<-ctx.Done()
	return freeaccount.Result{}, &freeaccount.Error{
		Code:      freeaccount.ErrorCodeCanceled,
		Message:   "The signup request was canceled before it was sent.",
		RetrySafe: true,
	}
}

func (s *saturatingFreeAccountSubmitter) DetectRegion(context.Context) freeaccount.RegionResult {
	return freeaccount.RegionResult{Region: "us"}
}

func (s *keyedCancelFreeAccountSubmitter) Submit(ctx context.Context, request freeaccount.Request) (freeaccount.Result, error) {
	s.started <- request.Email
	<-ctx.Done()
	s.canceled <- request.Email
	return freeaccount.Result{}, &freeaccount.Error{
		Code:      freeaccount.ErrorCodeCanceled,
		Message:   "The signup request was canceled before it was sent.",
		RetrySafe: true,
	}
}

func (s *keyedCancelFreeAccountSubmitter) DetectRegion(context.Context) freeaccount.RegionResult {
	return freeaccount.RegionResult{Region: "us"}
}

func TestRunStdioSplunkConnectionRealmUsesMetricsAndTraces(t *testing.T) {
	s := store.New()
	metricsController, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Realm:       "us0",
		AccessToken: "not-returned-by-realm-tool",
	})
	if err != nil {
		t.Fatalf("create metrics export controller: %v", err)
	}
	tracesController, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Realm:       "us0",
		AccessToken: "not-returned-by-realm-tool",
	})
	if err != nil {
		t.Fatalf("create traces export controller: %v", err)
	}

	req := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"observer_splunk_connection_realm","arguments":{}}}` + "\n"
	var out bytes.Buffer
	RunStdio(s, io.NopCloser(strings.NewReader(req)), &out, metricsController, tracesController)

	var resp jsonRPCResponse
	if err := json.Unmarshal(bytes.TrimSpace(out.Bytes()), &resp); err != nil {
		t.Fatalf("unmarshal stdio response %q: %v", out.String(), err)
	}
	if resp.Error != nil {
		t.Fatalf("unexpected stdio error: %+v", resp.Error)
	}
	result := toMapAny(resp.Result)
	content := toSliceAny(result["content"])
	if len(content) != 1 {
		t.Fatalf("content = %#v, want one text result", content)
	}
	text, _ := toMapAny(content[0])["text"].(string)
	var payload map[string]any
	if err := json.Unmarshal([]byte(text), &payload); err != nil {
		t.Fatalf("unmarshal tool payload %q: %v", text, err)
	}
	if payload["realm"] != "us0" {
		t.Fatalf("realm = %v, want us0", payload["realm"])
	}
}

func TestRunStdioCancelsPendingFreeAccountRequest(t *testing.T) {
	inputReader, inputWriter := io.Pipe()
	submitter := &cancelAwareFreeAccountSubmitter{
		started:  make(chan struct{}),
		canceled: make(chan struct{}),
	}
	var out bytes.Buffer
	done := make(chan struct{})
	go func() {
		RunStdio(store.New(), inputReader, &out, submitter)
		close(done)
	}()

	request := `{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"observer_splunk_free_account_create","arguments":{"firstName":"Ada","lastName":"Lovelace","email":"ada@example.com","termsAccepted":true}}}` + "\n"
	if _, err := io.WriteString(inputWriter, request); err != nil {
		t.Fatalf("write request: %v", err)
	}
	select {
	case <-submitter.started:
	case <-time.After(time.Second):
		t.Fatal("free-account request did not start")
	}

	cancellation := `{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":7,"reason":"client stopped"}}` + "\n"
	if _, err := io.WriteString(inputWriter, cancellation); err != nil {
		t.Fatalf("write cancellation: %v", err)
	}
	if err := inputWriter.Close(); err != nil {
		t.Fatalf("close input: %v", err)
	}

	select {
	case <-submitter.canceled:
	case <-time.After(time.Second):
		t.Fatal("free-account request context was not canceled")
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("stdio server did not stop after cancellation and EOF")
	}
	if !strings.Contains(out.String(), "request_canceled") {
		t.Fatalf("stdio response did not report cancellation: %s", out.String())
	}
}

func TestRunStdioPreservesLargeNumericIDsForCancellation(t *testing.T) {
	inputReader, inputWriter := io.Pipe()
	submitter := &keyedCancelFreeAccountSubmitter{
		started:  make(chan string, 2),
		canceled: make(chan string, 2),
	}
	var out bytes.Buffer
	done := make(chan struct{})
	go func() {
		RunStdio(store.New(), inputReader, &out, submitter)
		close(done)
	}()

	requests := []struct {
		id    string
		email string
	}{
		{id: "9007199254740992", email: "first@example.com"},
		{id: "9007199254740993", email: "second@example.com"},
	}
	for _, request := range requests {
		line := fmt.Sprintf(`{"jsonrpc":"2.0","id":%s,"method":"tools/call","params":{"name":"observer_splunk_free_account_create","arguments":{"firstName":"Ada","lastName":"Lovelace","email":%q,"termsAccepted":true}}}`+"\n", request.id, request.email)
		if _, err := io.WriteString(inputWriter, line); err != nil {
			t.Fatalf("write request %s: %v", request.id, err)
		}
		select {
		case email := <-submitter.started:
			if email != request.email {
				t.Fatalf("started request = %q, want %q", email, request.email)
			}
		case <-time.After(time.Second):
			t.Fatalf("request %s did not start", request.id)
		}
	}

	cancellation := `{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":9007199254740993}}` + "\n"
	if _, err := io.WriteString(inputWriter, cancellation); err != nil {
		t.Fatalf("write cancellation: %v", err)
	}
	select {
	case email := <-submitter.canceled:
		if email != "second@example.com" {
			t.Fatalf("canceled request = %q, want second@example.com", email)
		}
	case <-time.After(time.Second):
		t.Fatal("large-ID cancellation did not cancel its request")
	}

	if err := inputWriter.Close(); err != nil {
		t.Fatalf("close input: %v", err)
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("stdio server did not stop after large-ID cancellation and EOF")
	}
	for _, request := range requests {
		if !strings.Contains(out.String(), `"id":`+request.id) {
			t.Fatalf("stdio response did not preserve request ID %s: %s", request.id, out.String())
		}
	}
}

func TestRunStdioRejectsInvalidRequestIDType(t *testing.T) {
	request := `{"jsonrpc":"2.0","id":true,"method":"tools/list"}` + "\n"
	var out bytes.Buffer
	RunStdio(store.New(), io.NopCloser(strings.NewReader(request)), &out)

	var response struct {
		ID    json.RawMessage `json:"id"`
		Error *jsonRPCError   `json:"error"`
	}
	if err := json.Unmarshal(bytes.TrimSpace(out.Bytes()), &response); err != nil {
		t.Fatalf("unmarshal invalid-ID response %q: %v", out.String(), err)
	}
	if string(response.ID) != "null" || response.Error == nil || response.Error.Code != -32600 {
		t.Fatalf("invalid-ID response = %#v, want null ID and -32600", response)
	}
}

func TestRunStdioRejectsRequestsAboveConcurrencyLimit(t *testing.T) {
	inputReader, inputWriter := io.Pipe()
	outputWriter := &channelStdioWriter{writes: make(chan []byte, maxConcurrentStdioRequests+1)}
	submitter := &saturatingFreeAccountSubmitter{started: make(chan struct{}, maxConcurrentStdioRequests)}
	done := make(chan struct{})
	go func() {
		RunStdio(store.New(), inputReader, outputWriter, submitter)
		close(done)
	}()

	for id := 1; id <= maxConcurrentStdioRequests; id++ {
		request := `{"jsonrpc":"2.0","id":` + fmt.Sprint(id) + `,"method":"tools/call","params":{"name":"observer_splunk_free_account_create","arguments":{"firstName":"Ada","lastName":"Lovelace","email":"ada@example.com","termsAccepted":true}}}` + "\n"
		if _, err := io.WriteString(inputWriter, request); err != nil {
			t.Fatalf("write request %d: %v", id, err)
		}
		select {
		case <-submitter.started:
		case <-time.After(time.Second):
			t.Fatalf("request %d did not start", id)
		}
	}

	if _, err := io.WriteString(inputWriter, `{"jsonrpc":"2.0","id":99,"method":"tools/list"}`+"\n"); err != nil {
		t.Fatalf("write overflow request: %v", err)
	}
	select {
	case encoded := <-outputWriter.writes:
		line := strings.TrimSpace(string(encoded))
		var response jsonRPCResponse
		if err := json.Unmarshal([]byte(line), &response); err != nil {
			t.Fatalf("unmarshal overflow response %q: %v", line, err)
		}
		if response.ID != float64(99) || response.Error == nil || response.Error.Code != stdioServerBusyErrorCode {
			t.Fatalf("overflow response = %#v, want request 99 server-busy error", response)
		}
	case <-time.After(time.Second):
		t.Fatal("stdio server did not reject the overflow request")
	}

	if err := inputWriter.Close(); err != nil {
		t.Fatalf("close input: %v", err)
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("stdio server did not stop after canceling saturated requests")
	}
}

func TestRunStdioStopsAfterAsyncWriteFailure(t *testing.T) {
	inputReader, inputWriter := io.Pipe()
	defer inputWriter.Close()
	submitter := &cancelAwareFreeAccountSubmitter{
		started:  make(chan struct{}),
		canceled: make(chan struct{}),
	}
	out := &failingStdioWriter{attempted: make(chan struct{})}
	done := make(chan struct{})
	go func() {
		RunStdio(store.New(), inputReader, out, submitter)
		close(done)
	}()

	pendingRequest := `{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"observer_splunk_free_account_create","arguments":{"firstName":"Ada","lastName":"Lovelace","email":"ada@example.com","termsAccepted":true}}}` + "\n"
	if _, err := io.WriteString(inputWriter, "\n"+pendingRequest); err != nil {
		t.Fatalf("write pending request: %v", err)
	}
	select {
	case <-submitter.started:
	case <-time.After(time.Second):
		t.Fatal("free-account request did not start")
	}

	responseRequest := `{"jsonrpc":"2.0","id":8,"method":"tools/list"}` + "\n"
	if _, err := io.WriteString(inputWriter, responseRequest); err != nil {
		t.Fatalf("write response request: %v", err)
	}
	select {
	case <-out.attempted:
	case <-time.After(time.Second):
		t.Fatal("stdio server did not attempt a response write")
	}
	select {
	case <-submitter.canceled:
	case <-time.After(time.Second):
		t.Fatal("write failure did not cancel the pending request")
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("stdio server did not stop after an asynchronous write failure")
	}
	if _, err := io.WriteString(inputWriter, responseRequest); err == nil {
		t.Fatal("stdio server left its input open after the output failed")
	}
}

func TestRunStdioCancelsIDLessRequestOnEOF(t *testing.T) {
	inputReader, inputWriter := io.Pipe()
	submitter := &cancelAwareFreeAccountSubmitter{
		started:  make(chan struct{}),
		canceled: make(chan struct{}),
	}
	var out bytes.Buffer
	done := make(chan struct{})
	go func() {
		RunStdio(store.New(), inputReader, &out, submitter)
		close(done)
	}()

	request := `{"jsonrpc":"2.0","method":"tools/call","params":{"name":"observer_splunk_free_account_create","arguments":{"firstName":"Ada","lastName":"Lovelace","email":"ada@example.com","termsAccepted":true}}}` + "\n"
	if _, err := io.WriteString(inputWriter, request); err != nil {
		t.Fatalf("write id-less request: %v", err)
	}
	select {
	case <-submitter.started:
	case <-time.After(time.Second):
		t.Fatal("id-less free-account request did not start")
	}
	if err := inputWriter.Close(); err != nil {
		t.Fatalf("close input: %v", err)
	}

	select {
	case <-submitter.canceled:
	case <-time.After(time.Second):
		t.Fatal("EOF did not cancel the id-less request context")
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("stdio server did not stop after canceling the id-less request")
	}
}

func TestRunStdioCancelsValidationRefreshOnEOF(t *testing.T) {
	inputReader, inputWriter := io.Pipe()
	validationStore := validator.NewStore()
	started := make(chan struct{})
	canceled := make(chan struct{})
	runner := &fakeValidationRunner{
		onRun: func(ctx context.Context) validator.Summary {
			summary := validationStore.StartRun("run-eof", time.Now())
			close(started)
			go func() {
				<-ctx.Done()
				close(canceled)
			}()
			return summary
		},
	}
	done := make(chan struct{})
	go func() {
		RunStdio(store.New(), inputReader, io.Discard, validationStore, runner)
		close(done)
	}()

	request := `{"jsonrpc":"2.0","method":"tools/call","params":{"name":"observer_validation_refresh","arguments":{"timeoutSeconds":300}}}` + "\n"
	if _, err := io.WriteString(inputWriter, request); err != nil {
		t.Fatalf("write validation request: %v", err)
	}
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("validation request did not start")
	}
	if err := inputWriter.Close(); err != nil {
		t.Fatalf("close input: %v", err)
	}

	select {
	case <-canceled:
	case <-time.After(time.Second):
		t.Fatal("EOF did not cancel the validation request context")
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("stdio server did not stop after canceling validation")
	}
}
