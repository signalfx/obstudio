package otlp

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"mime"
	"net/http"
	"sync/atomic"

	"go.opentelemetry.io/collector/component"
	"go.opentelemetry.io/collector/consumer/consumererror"
	"go.opentelemetry.io/collector/extension/extensionmiddleware"
)

// The Collector logs partial rejection but returns nil. Keep the response's
// rejected count per call so Studio reports only the items Cloud accepted.
type splunkOTLPExportAttempt struct {
	rejected    atomic.Int64
	allowJSONOK bool
	decode      func([]byte, string) (int64, error)
}

type splunkOTLPExportAttemptKey struct{}

type splunkOTLPResponseMiddleware struct {
	component.StartFunc
	component.ShutdownFunc
}

type splunkOTLPExportHost struct{ minimalHost }

var splunkOTLPStatusMiddlewareID = component.MustNewID("obstudio_otlp_status")

func (splunkOTLPExportHost) GetExtensions() map[component.ID]component.Component {
	return map[component.ID]component.Component{splunkOTLPStatusMiddlewareID: &splunkOTLPResponseMiddleware{}}
}

func (*splunkOTLPResponseMiddleware) GetHTTPRoundTripper(context.Context) (extensionmiddleware.WrapHTTPRoundTripperFunc, error) {
	return func(_ context.Context, next http.RoundTripper) (http.RoundTripper, error) {
		return splunkOTLPResponseTransport{next}, nil
	}, nil
}

type splunkOTLPResponseTransport struct{ next http.RoundTripper }

func (t splunkOTLPResponseTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	response, err := t.next.RoundTrip(req)
	if err != nil || response.StatusCode < 200 || response.StatusCode >= 300 {
		return response, err
	}
	attempt, ok := req.Context().Value(splunkOTLPExportAttemptKey{}).(*splunkOTLPExportAttempt)
	if !ok {
		return response, nil
	}
	// Match the Collector's bounded response read and restore the body for its
	// own validation. The upstream exporter still owns delivery and retries.
	body, readErr := io.ReadAll(io.LimitReader(response.Body, 64*1024+1))
	response.Body.Close()
	response.Body = io.NopCloser(bytes.NewReader(body))
	if readErr != nil || len(body) > 64*1024 {
		response.Body.Close()
		return nil, consumererror.NewPermanent(fmt.Errorf("invalid OTLP export response body"))
	}
	if len(body) > 0 {
		contentType := response.Header.Get("Content-Type")
		if mediaType, _, err := mime.ParseMediaType(contentType); err == nil {
			contentType = mediaType
			response.Header.Set("Content-Type", mediaType)
		}
		if contentType != "application/json" && contentType != "application/x-protobuf" {
			response.Body.Close()
			return nil, consumererror.NewPermanent(fmt.Errorf("unrecognized OTLP export response content type"))
		}
		if attempt.allowJSONOK && req.URL.Path == splunkMetricsOTLPPath && response.StatusCode == http.StatusOK && contentType == "application/json" && bytes.Equal(bytes.TrimSpace(body), []byte(`"OK"`)) {
			// Splunk metrics ingest acknowledges success with a JSON string.
			// Normalize it for both our decoder and the upstream OTLP exporter.
			body = []byte("{}")
			response.Body = io.NopCloser(bytes.NewReader(body))
			response.ContentLength = int64(len(body))
			response.Header.Set("Content-Length", "2")
		}
		rejected, decodeErr := attempt.decode(body, contentType)
		if decodeErr != nil {
			response.Body.Close()
			return nil, consumererror.NewPermanent(fmt.Errorf("invalid OTLP export response body"))
		}
		attempt.rejected.Store(rejected)
	}
	return response, nil
}

type splunkOTLPPartialExportError struct {
	accepted int
	total    int
}

func (e *splunkOTLPPartialExportError) Error() string {
	return fmt.Sprintf("cloud rejected %d of %d items", e.total-e.accepted, e.total)
}

func (a *splunkOTLPExportAttempt) result(err error, total int) error {
	if err != nil {
		return err
	}
	rejected := a.rejected.Load()
	if rejected < 0 || rejected > int64(total) {
		return fmt.Errorf("invalid OTLP export rejection count")
	}
	if rejected > 0 {
		return &splunkOTLPPartialExportError{accepted: total - int(rejected), total: total}
	}
	return nil
}
