package otlp

import "testing"

func TestValidateLoopbackAddress(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name    string
		address string
		wantErr bool
	}{
		{name: "IPv4 loopback", address: "127.0.0.1:4317"},
		{name: "IPv6 loopback", address: "[::1]:4317"},
		{name: "localhost", address: "localhost:4317"},
		{name: "wildcard IPv4", address: "0.0.0.0:4317", wantErr: true},
		{name: "wildcard IPv6", address: "[::]:4317", wantErr: true},
		{name: "non-loopback", address: "192.0.2.10:4317", wantErr: true},
		{name: "hostname", address: "example.com:4317", wantErr: true},
		{name: "missing port", address: "127.0.0.1", wantErr: true},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()
			err := validateLoopbackAddress(test.address)
			if test.wantErr && err == nil {
				t.Fatalf("validateLoopbackAddress(%q) returned nil", test.address)
			}
			if !test.wantErr && err != nil {
				t.Fatalf("validateLoopbackAddress(%q) returned %v", test.address, err)
			}
		})
	}
}
