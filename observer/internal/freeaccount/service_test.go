package freeaccount

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestSubmitUsesSplunkGeoIPAndSendsCompleteUS1PayloadForEveryCall(t *testing.T) {
	var geoCalls atomic.Int32
	var signupCalls atomic.Int32
	var submitted []signupPayload
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/geo":
			geoCalls.Add(1)
			if r.Method != http.MethodGet {
				t.Errorf("geo method = %q, want GET", r.Method)
			}
			if r.URL.RawQuery != "" {
				t.Errorf("geo query = %q, want empty", r.URL.RawQuery)
			}
			_, _ = w.Write([]byte(`{"code":"REQ_SUCCESS","data":{"countryName":"United States","region":"Virginia","city":"Ashburn","postalCode":"20149"},"region":"AMER"}`))
		case "/signup":
			signupCalls.Add(1)
			if got := r.Header.Get("Content-Type"); got != "application/json; charset=utf-8" {
				t.Errorf("Content-Type = %q", got)
			}
			var payload signupPayload
			if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
				t.Errorf("decode signup: %v", err)
			}
			submitted = append(submitted, payload)
			_, _ = w.Write([]byte(`"OK"`))
		default:
			t.Fatalf("unexpected request path %s", r.URL.Path)
		}
	}))
	defer server.Close()

	service := newTestService(t, Config{
		HTTPClient: server.Client(),
		GeoURL:     server.URL + "/geo",
		SignupURL:  server.URL + "/signup",
	})
	request := Request{
		FirstName:     "Ada",
		LastName:      "Lovelace Byron",
		Email:         "ada@example.com",
		TermsAccepted: true,
	}
	result, err := service.Submit(context.Background(), request)
	if err != nil {
		t.Fatalf("Submit() error = %v", err)
	}
	if !result.IntakeAcknowledged || result.Realm != "us1" || result.Region != signupRegionUS {
		t.Fatalf("unexpected result: %+v", result)
	}
	if result.Message != successfulSignupMessage {
		t.Fatalf("message = %q", result.Message)
	}

	if len(submitted) != 1 {
		t.Fatalf("submitted payloads = %d, want 1", len(submitted))
	}
	firstPayload := submitted[0]
	if firstPayload.FirstName != "Ada" || firstPayload.LastName != "Lovelace Byron" || firstPayload.EmailAddress != "ada@example.com" {
		t.Fatalf("unexpected identity payload: %+v", firstPayload)
	}
	if firstPayload.Company != "dev" || firstPayload.Title != "Developer" || firstPayload.Region != "us" {
		t.Fatalf("unexpected fixed signup values: %+v", firstPayload)
	}
	if firstPayload.Country != "United States" || firstPayload.State != "Virginia" || firstPayload.City != "Ashburn" || firstPayload.PostalCode != "20149" {
		t.Fatalf("unexpected location payload: %+v", firstPayload)
	}
	if firstPayload.PrivacyPolicyCheck != "1" || firstPayload.MarketingOptIn != "0" || firstPayload.PhoneOptIn != "Undecided" {
		t.Fatalf("unexpected consent payload: %+v", firstPayload)
	}
	if firstPayload.BusinessPhone != "" || firstPayload.Role != "MKTO" || firstPayload.AssetType != "Trial" || firstPayload.FormName != "Trial" {
		t.Fatalf("unexpected form payload: %+v", firstPayload)
	}
	if !strings.Contains(firstPayload.URLName, "observability-cloud-free-edition") {
		t.Fatalf("unexpected urlName: %q", firstPayload.URLName)
	}

	resubmitted, err := service.Submit(context.Background(), Request{
		FirstName:     "  ADA ",
		LastName:      " LOVELACE   BYRON ",
		Email:         "ADA@EXAMPLE.COM",
		TermsAccepted: true,
	})
	if err != nil {
		t.Fatalf("second Submit() error = %v", err)
	}
	if !resubmitted.IntakeAcknowledged || resubmitted.Realm != "us1" || resubmitted.Region != signupRegionUS {
		t.Fatalf("second result = %+v, want fresh acknowledged submission", resubmitted)
	}
	if signupCalls.Load() != 2 || geoCalls.Load() != 2 || len(submitted) != 2 {
		t.Fatalf("calls after resubmit: signup=%d geo=%d payloads=%d, want two each", signupCalls.Load(), geoCalls.Load(), len(submitted))
	}
	if submitted[1].FirstName != "ADA" || submitted[1].LastName != "LOVELACE BYRON" || submitted[1].EmailAddress != "ADA@EXAMPLE.COM" {
		t.Fatalf("second payload was not freshly submitted: %+v", submitted[1])
	}
}

func TestSubmitUsesOneGeoRequestAndLegacyGeoFields(t *testing.T) {
	var geoCalls atomic.Int32
	var signupCalls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/geo":
			geoCalls.Add(1)
			if r.URL.RawQuery != "" {
				t.Errorf("geo query = %q, want empty", r.URL.RawQuery)
			}
			_, _ = w.Write([]byte(`{"region":"ANZ","data":{"country_name":"Australia","country_code":"AU","region_name":"Queensland","city":"South Brisbane","postal_code":"4101"}}`))
		case "/signup":
			signupCalls.Add(1)
			var payload signupPayload
			if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
				t.Errorf("decode signup: %v", err)
			}
			if payload.Country != "Australia" || payload.State != "Queensland" || payload.PostalCode != "4101" || payload.City != "South Brisbane" {
				t.Errorf("unexpected location payload: %+v", payload)
			}
			if payload.Region != signupRegionAustralia {
				t.Errorf("signup region = %q, want %q", payload.Region, signupRegionAustralia)
			}
			_, _ = w.Write([]byte("OK"))
		default:
			t.Fatalf("unexpected request path %s", r.URL.Path)
		}
	}))
	defer server.Close()

	service := newTestService(t, Config{
		HTTPClient: server.Client(),
		GeoURL:     server.URL + "/geo",
		SignupURL:  server.URL + "/signup",
	})
	result, err := service.Submit(context.Background(), Request{
		FirstName:     "Grace",
		LastName:      "Hopper",
		Email:         "grace@example.com",
		TermsAccepted: true,
	})
	if err != nil {
		t.Fatalf("Submit() error = %v", err)
	}
	if geoCalls.Load() != 1 {
		t.Fatalf("unexpected result/calls: result=%+v geoCalls=%d", result, geoCalls.Load())
	}
	if result.Realm != "au0" || result.Region != signupRegionAustralia {
		t.Fatalf("destination = realm %q, region %q; want au0, %q", result.Realm, result.Region, signupRegionAustralia)
	}
	resubmitted, err := service.Submit(context.Background(), Request{
		FirstName:     "Grace",
		LastName:      "Hopper",
		Email:         "grace@example.com",
		TermsAccepted: true,
	})
	if err != nil || !resubmitted.IntakeAcknowledged || resubmitted.Realm != "au0" || resubmitted.Region != signupRegionAustralia {
		t.Fatalf("resubmitted result = %+v, error = %v", resubmitted, err)
	}
	if geoCalls.Load() != 2 || signupCalls.Load() != 2 {
		t.Fatalf("calls after resubmit: geo=%d signup=%d, want two each", geoCalls.Load(), signupCalls.Load())
	}
}

func TestOptionalGeoIPLocationFieldsAreBoundedAndSanitized(t *testing.T) {
	tests := []struct {
		name      string
		value     string
		maxLength int
		want      string
	}{
		{name: "trimmed city", value: "  San Jose  ", maxLength: 100, want: "San Jose"},
		{name: "postal boundary", value: strings.Repeat("1", 20), maxLength: 20, want: strings.Repeat("1", 20)},
		{name: "overlong postal", value: strings.Repeat("1", 21), maxLength: 20},
		{name: "control character", value: "San\nJose", maxLength: 100},
		{name: "invalid UTF-8", value: string([]byte{0xff}), maxLength: 100},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := optionalLocationValue(test.value, test.maxLength); got != test.want {
				t.Fatalf("optionalLocationValue(%q, %d) = %q, want %q", test.value, test.maxLength, got, test.want)
			}
		})
	}
}

func TestDestinationForLocationMapsOnlySupportedSignupRegions(t *testing.T) {
	tests := []struct {
		name           string
		location       signupLocation
		wantFormRegion string
		wantRealm      string
		wantOK         bool
	}{
		{name: "US country code", location: signupLocation{countryCode: " us ", marketRegion: "EMEA"}, wantFormRegion: "us", wantRealm: "us1", wantOK: true},
		{name: "country code overrides conflicting sales region", location: signupLocation{country: "United States", countryCode: "IE", marketRegion: "AMER"}, wantFormRegion: "Europe (Ireland)", wantRealm: "eu0", wantOK: true},
		{name: "Ireland", location: signupLocation{country: "Ireland", marketRegion: "EMEA"}, wantFormRegion: "Europe (Ireland)", wantRealm: "eu0", wantOK: true},
		{name: "Germany", location: signupLocation{countryCode: "DE", marketRegion: "EMEA"}, wantFormRegion: "Europe (Ireland)", wantRealm: "eu0", wantOK: true},
		{name: "United Kingdom", location: signupLocation{country: "Great Britain", marketRegion: "EMEA"}, wantFormRegion: "Europe (Ireland)", wantRealm: "eu0", wantOK: true},
		{name: "Australia", location: signupLocation{countryCode: "AU", marketRegion: "ANZ"}, wantFormRegion: "apac-au", wantRealm: "au0", wantOK: true},
		{name: "New Zealand", location: signupLocation{countryCode: "NZ", marketRegion: "ANZ"}, wantFormRegion: "apac-au", wantRealm: "au0", wantOK: true},
		{name: "Japan", location: signupLocation{country: "Japan", marketRegion: "APAC"}, wantFormRegion: "apac-au", wantRealm: "au0", wantOK: true},
		{name: "country name does not override sales region", location: signupLocation{country: "Ireland", marketRegion: "APAC"}, wantFormRegion: "apac-au", wantRealm: "au0", wantOK: true},
		{name: "US country name does not override EMEA", location: signupLocation{country: "United States", marketRegion: "EMEA"}, wantFormRegion: "Europe (Ireland)", wantRealm: "eu0", wantOK: true},
		{name: "Singapore", location: signupLocation{countryCode: "SG", marketRegion: "APAC"}, wantFormRegion: "apac-au", wantRealm: "au0", wantOK: true},
		{name: "generic EMEA", location: signupLocation{country: "France", marketRegion: " emea "}, wantFormRegion: "Europe (Ireland)", wantRealm: "eu0", wantOK: true},
		{name: "generic APAC", location: signupLocation{country: "India", marketRegion: "APAC"}, wantFormRegion: "apac-au", wantRealm: "au0", wantOK: true},
		{name: "generic ANZ", location: signupLocation{country: "Fiji", marketRegion: "ANZ"}, wantFormRegion: "apac-au", wantRealm: "au0", wantOK: true},
		{name: "LATAM", location: signupLocation{country: "Brazil", marketRegion: "LATAM"}, wantFormRegion: "us", wantRealm: "us1", wantOK: true},
		{name: "AMER", location: signupLocation{country: "Canada", marketRegion: "AMER"}, wantFormRegion: "us", wantRealm: "us1", wantOK: true},
		{name: "unrecognized", location: signupLocation{country: "Atlantis", marketRegion: "UNKNOWN"}, wantOK: false},
		{name: "country name alone is not a mapping input", location: signupLocation{country: "Ireland"}, wantOK: false},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			destination, ok := destinationForLocation(test.location)
			if ok != test.wantOK {
				t.Fatalf("ok = %t, want %t; destination = %+v", ok, test.wantOK, destination)
			}
			if destination.formRegion != test.wantFormRegion || destination.realm != test.wantRealm {
				t.Fatalf("destination = %+v, want formRegion=%q realm=%q", destination, test.wantFormRegion, test.wantRealm)
			}
		})
	}
}

func TestDestinationForFormRegionAcceptsExactlyPublicFormValues(t *testing.T) {
	tests := []struct {
		region    string
		wantRealm string
		wantOK    bool
	}{
		{region: signupRegionUS, wantRealm: "us1", wantOK: true},
		{region: signupRegionIreland, wantRealm: "eu0", wantOK: true},
		{region: signupRegionAustralia, wantRealm: "au0", wantOK: true},
		{region: "United States", wantOK: false},
		{region: "Ireland", wantOK: false},
		{region: "Europe (Frankfurt)", wantOK: false},
		{region: "Europe (London)", wantOK: false},
		{region: "Asia Pacific (Australia)", wantOK: false},
		{region: "apac-jp", wantOK: false},
		{region: "Asia Pacific (Singapore)", wantOK: false},
		{region: "europe (ireland)", wantOK: false},
		{region: "APAC-AU", wantOK: false},
		{region: "us0", wantOK: false},
		{region: "us1", wantOK: false},
		{region: "eu0", wantOK: false},
		{region: "", wantOK: false},
	}
	for _, test := range tests {
		t.Run(test.region, func(t *testing.T) {
			destination, ok := destinationForFormRegion(test.region)
			if ok != test.wantOK {
				t.Fatalf("destinationForFormRegion(%q) = %+v, %t", test.region, destination, ok)
			}
			if ok && (destination.formRegion != test.region || destination.realm != test.wantRealm) {
				t.Fatalf("destination = %+v, want formRegion %q and realm %q", destination, test.region, test.wantRealm)
			}
		})
	}
}

func TestDetectRegionUsesGeoIPWithoutSubmittingSignup(t *testing.T) {
	var geoCalls atomic.Int32
	var signupCalls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/geo":
			geoCalls.Add(1)
			if r.Method != http.MethodGet || r.URL.RawQuery != "" {
				t.Errorf("geo request = %s %q, want GET without query", r.Method, r.URL.RawQuery)
			}
			_, _ = w.Write([]byte(`{"data":{"countryName":"Germany","countryCode":"DE","region":"Hesse","salesRegion":"EMEA"}}`))
		case "/signup":
			signupCalls.Add(1)
		default:
			t.Fatalf("unexpected request path %s", r.URL.Path)
		}
	}))
	defer server.Close()

	service := newTestService(t, Config{HTTPClient: server.Client(), GeoURL: server.URL + "/geo", SignupURL: server.URL + "/signup"})
	result := service.DetectRegion(context.Background())
	if result.Region != signupRegionIreland {
		t.Fatalf("DetectRegion() = %+v", result)
	}
	if geoCalls.Load() != 1 || signupCalls.Load() != 0 {
		t.Fatalf("calls: geo=%d signup=%d, want 1 and 0", geoCalls.Load(), signupCalls.Load())
	}
}

func TestDetectRegionDoesNotCacheLocationForSubmit(t *testing.T) {
	var geoCalls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/geo":
			call := geoCalls.Add(1)
			if call == 1 {
				_, _ = w.Write([]byte(`{"data":{"countryName":"Ireland","countryCode":"IE","region":"Leinster","salesRegion":"EMEA"}}`))
				return
			}
			_, _ = w.Write([]byte(`{"data":{"countryName":"United States","countryCode":"US","region":"California","salesRegion":"AMER"}}`))
		case "/signup":
			_, _ = w.Write([]byte("OK"))
		default:
			t.Fatalf("unexpected request path %s", r.URL.Path)
		}
	}))
	defer server.Close()

	service := newTestService(t, Config{HTTPClient: server.Client(), GeoURL: server.URL + "/geo", SignupURL: server.URL + "/signup"})
	if result := service.DetectRegion(context.Background()); result.Region != signupRegionIreland {
		t.Fatalf("DetectRegion() = %+v", result)
	}
	result, err := service.Submit(context.Background(), Request{
		FirstName: "Ada", LastName: "Lovelace", Email: "ada@example.com", TermsAccepted: true,
	})
	if err != nil {
		t.Fatalf("Submit() error = %v", err)
	}
	if result.Region != signupRegionUS || result.Realm != defaultRealm {
		t.Fatalf("Submit() = %+v, want a fresh United States lookup", result)
	}
	if geoCalls.Load() != 2 {
		t.Fatalf("GeoIP calls = %d, want one for detection and one for submission", geoCalls.Load())
	}
}

func TestDetectRegionFallsBackToPublicUSValueWithoutSubmittingSignup(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer server.Close()
	service := newTestService(t, Config{HTTPClient: server.Client(), GeoURL: server.URL + "/geo", SignupURL: server.URL + "/signup"})

	result := service.DetectRegion(context.Background())
	if result.Region != signupRegionUS {
		t.Fatalf("DetectRegion() fallback = %+v", result)
	}
	if calls.Load() != 1 {
		t.Fatalf("remote calls = %d, want only one GeoIP request", calls.Load())
	}
}

func TestSubmitRegionOverrideChangesOnlyDestination(t *testing.T) {
	tests := []struct {
		region string
		realm  string
	}{
		{region: signupRegionUS, realm: "us1"},
		{region: signupRegionIreland, realm: "eu0"},
		{region: signupRegionAustralia, realm: "au0"},
	}
	for _, test := range tests {
		t.Run(test.region, func(t *testing.T) {
			var submitted signupPayload
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch r.URL.Path {
				case "/geo":
					_, _ = w.Write([]byte(`{"data":{"countryName":"United States","countryCode":"US","region":"California","salesRegion":"AMER"}}`))
				case "/signup":
					if err := json.NewDecoder(r.Body).Decode(&submitted); err != nil {
						t.Errorf("decode signup: %v", err)
					}
					_, _ = w.Write([]byte("OK"))
				default:
					t.Fatalf("unexpected request path %s", r.URL.Path)
				}
			}))
			defer server.Close()
			service := newTestService(t, Config{HTTPClient: server.Client(), GeoURL: server.URL + "/geo", SignupURL: server.URL + "/signup"})

			result, err := service.Submit(context.Background(), Request{
				FirstName: "Ada", LastName: "Lovelace", Email: "ada@example.com", Region: "  " + test.region + "  ", TermsAccepted: true,
			})
			if err != nil {
				t.Fatalf("Submit() error = %v", err)
			}
			if result.Realm != test.realm || result.Region != test.region {
				t.Fatalf("Submit() result = %+v", result)
			}
			if submitted.Region != test.region || submitted.Country != "United States" || submitted.State != "California" {
				t.Fatalf("signup payload = %+v", submitted)
			}
		})
	}
}

func TestSubmitFallsBackAtomicallyWithoutRetryingGeo(t *testing.T) {
	tests := []struct {
		name      string
		geoStatus int
		geoBody   string
		geoDelay  time.Duration
	}{
		{
			name:      "geo request blocked",
			geoStatus: http.StatusForbidden,
		},
		{
			name:    "geo result incomplete",
			geoBody: `{"data":{"countryName":"Canada"}}`,
		},
		{
			name:    "geo region unrecognized",
			geoBody: `{"region":"UNKNOWN","data":{"countryName":"Atlantis","region":"Poseidon"}}`,
		},
		{
			name:     "geo timeout",
			geoBody:  `{"data":{"countryName":"Canada","region":"Ontario"}}`,
			geoDelay: 50 * time.Millisecond,
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			var geoCalls atomic.Int32
			var submitted signupPayload
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch r.URL.Path {
				case "/geo":
					if r.URL.RawQuery != "" {
						t.Errorf("geo query = %q, want empty", r.URL.RawQuery)
					}
					if test.geoDelay > 0 {
						time.Sleep(test.geoDelay)
					}
					if test.geoStatus != 0 {
						w.WriteHeader(test.geoStatus)
					}
					_, _ = w.Write([]byte(test.geoBody))
				case "/signup":
					if err := json.NewDecoder(r.Body).Decode(&submitted); err != nil {
						t.Errorf("decode signup: %v", err)
					}
					_, _ = w.Write([]byte("OK"))
				default:
					t.Fatalf("unexpected request path %s", r.URL.Path)
				}
			}))
			defer server.Close()
			baseTransport := server.Client().Transport
			client := &http.Client{Transport: freeAccountRoundTripFunc(func(request *http.Request) (*http.Response, error) {
				if request.URL.Path == "/geo" {
					geoCalls.Add(1)
				}
				return baseTransport.RoundTrip(request)
			})}

			service := newTestService(t, Config{
				HTTPClient: client,
				GeoURL:     server.URL + "/geo",
				SignupURL:  server.URL + "/signup",
				GeoTimeout: 10 * time.Millisecond,
			})
			request := Request{FirstName: "Fallback", LastName: "User", Email: "fallback@example.com", TermsAccepted: true}
			result, err := service.Submit(context.Background(), request)
			if err != nil {
				t.Fatalf("Submit() error = %v", err)
			}
			if result.Realm != defaultRealm || result.Region != signupRegionUS || submitted.Region != signupRegionUS {
				t.Fatalf("fallback destination result=%+v payloadRegion=%q", result, submitted.Region)
			}
			if submitted.Country != defaultCountry || submitted.State != defaultState || submitted.City != "" || submitted.PostalCode != "" {
				t.Fatalf("payload = %+v, want atomic fallback without inferred city/postal", submitted)
			}
			if geoCalls.Load() != 1 {
				t.Fatalf("geo calls = %d, want exactly one", geoCalls.Load())
			}
		})
	}
}

func TestSubmitValidatesBeforeCallingRemoteServices(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		calls.Add(1)
	}))
	defer server.Close()
	service := newTestService(t, Config{HTTPClient: server.Client(), GeoURL: server.URL, SignupURL: server.URL})

	tests := []Request{
		{FirstName: "Ada", LastName: "Lovelace", Email: "ada@example.com", TermsAccepted: false},
		{LastName: "Lovelace", Email: "ada@example.com", TermsAccepted: true},
		{FirstName: "Ada", Email: "ada@example.com", TermsAccepted: true},
		{FirstName: "Ada", LastName: "Lovelace", Email: "not-an-email", TermsAccepted: true},
		{FirstName: "Ada", LastName: "Lovelace", Email: "Ada <ada@example.com>", TermsAccepted: true},
		{FirstName: strings.Repeat("a", 41), LastName: "Lovelace", Email: "ada@example.com", TermsAccepted: true},
		{FirstName: "Ada", LastName: strings.Repeat("l", 41), Email: "ada@example.com", TermsAccepted: true},
		{FirstName: "Ada\x00", LastName: "Lovelace", Email: "ada@example.com", TermsAccepted: true},
		{FirstName: "Ada", LastName: "Love\x00lace", Email: "ada@example.com", TermsAccepted: true},
		{FirstName: "Ada", LastName: "Lovelace", Email: strings.Repeat("a", 69) + "@example.com", TermsAccepted: true},
		{FirstName: "Ada", LastName: "Lovelace", Email: "ada@example.com", Region: "us1", TermsAccepted: true},
		{FirstName: "Ada", LastName: "Lovelace", Email: "ada@example.com", Region: "eu0", TermsAccepted: true},
		{FirstName: "Ada", LastName: "Lovelace", Email: "ada@example.com", Region: "United States", TermsAccepted: true},
		{FirstName: "Ada", LastName: "Lovelace", Email: "ada@example.com", Region: "Ireland", TermsAccepted: true},
		{FirstName: "Ada", LastName: "Lovelace", Email: "ada@example.com", Region: "Asia Pacific (Australia)", TermsAccepted: true},
		{FirstName: "Ada", LastName: "Lovelace", Email: "ada@example.com", Region: "us0", TermsAccepted: true},
	}
	for _, request := range tests {
		_, err := service.Submit(context.Background(), request)
		assertSignupError(t, err, ErrorCodeValidation, true)
	}
	if calls.Load() != 0 {
		t.Fatalf("remote calls = %d, want 0", calls.Load())
	}
}

func TestValidateRequestAcceptsCapturedFormLengthBoundaries(t *testing.T) {
	firstName := strings.Repeat("a", maxFirstNameLength)
	lastName := strings.Repeat("l", maxLastNameLength)
	email := strings.Repeat("e", 64) + "@examplelong.com"
	if len(email) != maxEmailLength {
		t.Fatalf("test email length = %d, want %d", len(email), maxEmailLength)
	}
	identity, err := validateRequest(Request{
		FirstName:     firstName,
		LastName:      lastName,
		Email:         email,
		TermsAccepted: true,
	})
	if err != nil {
		t.Fatalf("validateRequest() error = %v", err)
	}
	if identity.firstName != firstName || identity.lastName != lastName || identity.email != email {
		t.Fatalf("identity = %+v, want captured form boundaries", identity)
	}
}

func TestSubmitDefiniteRejectionCanBeCorrectedAndResubmitted(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/signup" {
			calls.Add(1)
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"message":"Denied Person"}`))
			return
		}
		t.Fatalf("unexpected request path %s", r.URL.Path)
	}))
	defer server.Close()
	service := newTestService(t, Config{HTTPClient: server.Client(), GeoURL: ":", SignupURL: server.URL + "/signup"})
	request := Request{FirstName: "Denied", LastName: "User", Email: "denied@example.com", TermsAccepted: true}

	for range 2 {
		_, err := service.Submit(context.Background(), request)
		assertSignupError(t, err, ErrorCodeRejected, true)
	}
	if calls.Load() != 2 {
		t.Fatalf("signup calls = %d, want 2 after definite rejections", calls.Load())
	}
}

func TestSubmitClassifiesAndLogsOnlySafeUpstreamResponseDiagnostics(t *testing.T) {
	tests := []struct {
		name               string
		status             int
		body               string
		wantClassification signupResponseClassification
		wantCode           ErrorCode
		wantMessagePart    string
	}{
		{
			name:               "acknowledged",
			status:             http.StatusOK,
			body:               `"OK"`,
			wantClassification: signupResponseAcknowledged,
		},
		{
			name:               "denied person",
			status:             http.StatusOK,
			body:               `{"message":"Denied Person","private":"must-not-be-logged"}`,
			wantClassification: signupResponseDeniedPerson,
			wantCode:           ErrorCodeRejected,
			wantMessagePart:    "Denied Person response",
		},
		{
			name:               "profanity",
			status:             http.StatusBadRequest,
			body:               `{"message":"Profanity not allowed into the form values","private":"must-not-be-logged"}`,
			wantClassification: signupResponseProfanity,
			wantCode:           ErrorCodeRejected,
			wantMessagePart:    "profanity filter",
		},
		{
			name:               "generic bad request",
			status:             http.StatusBadRequest,
			body:               `{"message":"must-not-be-logged"}`,
			wantClassification: signupResponseRejected,
			wantCode:           ErrorCodeRejected,
			wantMessagePart:    "validation rejection",
		},
		{
			name:               "generic unprocessable entity",
			status:             http.StatusUnprocessableEntity,
			body:               `{"message":"must-not-be-logged"}`,
			wantClassification: signupResponseRejected,
			wantCode:           ErrorCodeRejected,
			wantMessagePart:    "validation rejection",
		},
		{
			name:               "unrecognized",
			status:             http.StatusInternalServerError,
			body:               `{"message":"must-not-be-logged"}`,
			wantClassification: signupResponseUnrecognized,
			wantCode:           ErrorCodeOutcomeUnknown,
			wantMessagePart:    "outcome is unknown",
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			var diagnostics bytes.Buffer
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(test.status)
				_, _ = w.Write([]byte(test.body))
			}))
			defer server.Close()
			service := newTestService(t, Config{
				HTTPClient:       server.Client(),
				GeoURL:           ":",
				SignupURL:        server.URL,
				DiagnosticLogger: log.New(&diagnostics, "", 0),
			})

			result, err := service.Submit(context.Background(), Request{
				FirstName: "Private", LastName: "Identity", Email: "private.identity@example.com", TermsAccepted: true,
			})
			if test.wantCode == "" {
				if err != nil || !result.IntakeAcknowledged {
					t.Fatalf("Submit() = %+v, %v; want acknowledged", result, err)
				}
			} else {
				assertSignupError(t, err, test.wantCode, test.wantCode == ErrorCodeRejected)
				if !strings.Contains(err.Error(), test.wantMessagePart) {
					t.Fatalf("error = %q, want category %q", err, test.wantMessagePart)
				}
			}

			logLine := diagnostics.String()
			wantLogLine := "[freeaccount] signup_response status=" + strconv.Itoa(test.status) + " classification=" + string(test.wantClassification) + "\n"
			if logLine != wantLogLine {
				t.Fatalf("diagnostic = %q, want %q", logLine, wantLogLine)
			}
			for _, privateValue := range []string{"Private", "Identity", "private.identity@example.com", "must-not-be-logged"} {
				if strings.Contains(logLine, privateValue) {
					t.Fatalf("diagnostic %q exposed %q", logLine, privateValue)
				}
			}
		})
	}
}

func TestSubmitLogsBoundedResponseFailuresWithoutResponseContents(t *testing.T) {
	t.Run("too large", func(t *testing.T) {
		var diagnostics bytes.Buffer
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			_, _ = io.WriteString(w, strings.Repeat("private-response", maxResponseBytes))
		}))
		defer server.Close()
		service := newTestService(t, Config{
			HTTPClient:       server.Client(),
			GeoURL:           ":",
			SignupURL:        server.URL,
			DiagnosticLogger: log.New(&diagnostics, "", 0),
		})

		_, err := service.Submit(context.Background(), Request{
			FirstName: "Private", LastName: "Identity", Email: "private.identity@example.com", TermsAccepted: true,
		})
		assertSignupError(t, err, ErrorCodeOutcomeUnknown, false)
		if got, want := diagnostics.String(), "[freeaccount] signup_response status=200 classification=too_large\n"; got != want {
			t.Fatalf("diagnostic = %q, want %q", got, want)
		}
	})

	t.Run("read error", func(t *testing.T) {
		var diagnostics bytes.Buffer
		client := &http.Client{Transport: freeAccountRoundTripFunc(func(request *http.Request) (*http.Response, error) {
			return &http.Response{
				StatusCode: http.StatusBadGateway,
				Header:     make(http.Header),
				Body:       freeAccountReadErrorBody{},
				Request:    request,
			}, nil
		})}
		service := newTestService(t, Config{
			HTTPClient:       client,
			GeoURL:           ":",
			SignupURL:        "https://signup.invalid",
			DiagnosticLogger: log.New(&diagnostics, "", 0),
		})

		_, err := service.Submit(context.Background(), Request{
			FirstName: "Private", LastName: "Identity", Email: "private.identity@example.com", TermsAccepted: true,
		})
		assertSignupError(t, err, ErrorCodeOutcomeUnknown, false)
		if got, want := diagnostics.String(), "[freeaccount] signup_response status=502 classification=read_error\n"; got != want {
			t.Fatalf("diagnostic = %q, want %q", got, want)
		}
		if strings.Contains(diagnostics.String(), "private read failure") {
			t.Fatalf("diagnostic exposed read error: %q", diagnostics.String())
		}
	})
}

func TestSubmitAmbiguousOutcomeIsNotAutomaticallyRetriedAndLaterCallCanResubmit(t *testing.T) {
	tests := []struct {
		name   string
		status int
		body   string
		delay  time.Duration
	}{
		{name: "unexpected 200", status: http.StatusOK, body: `{"status":"queued"}`},
		{name: "upstream 408", status: http.StatusRequestTimeout, body: "timeout"},
		{name: "upstream 409", status: http.StatusConflict, body: "conflict"},
		{name: "upstream 425", status: http.StatusTooEarly, body: "too early"},
		{name: "upstream 429", status: http.StatusTooManyRequests, body: "rate limited"},
		{name: "unknown upstream 4xx", status: http.StatusTeapot, body: "unexpected client response"},
		{name: "upstream 500", status: http.StatusInternalServerError, body: "failed"},
		{name: "transport timeout", status: http.StatusOK, body: "OK", delay: 50 * time.Millisecond},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			var calls atomic.Int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				if test.delay > 0 {
					time.Sleep(test.delay)
				}
				w.WriteHeader(test.status)
				_, _ = w.Write([]byte(test.body))
			}))
			defer server.Close()
			baseTransport := server.Client().Transport
			client := &http.Client{Transport: freeAccountRoundTripFunc(func(request *http.Request) (*http.Response, error) {
				calls.Add(1)
				return baseTransport.RoundTrip(request)
			})}
			service := newTestService(t, Config{
				HTTPClient:    client,
				GeoURL:        ":",
				SignupURL:     server.URL,
				SignupTimeout: 10 * time.Millisecond,
			})
			request := Request{FirstName: "Unknown", LastName: "User", Email: "unknown@example.com", TermsAccepted: true}

			for range 2 {
				_, err := service.Submit(context.Background(), request)
				assertSignupError(t, err, ErrorCodeOutcomeUnknown, false)
			}
			if calls.Load() != 2 {
				t.Fatalf("signup calls = %d, want one POST per explicit call", calls.Load())
			}
		})
	}
}

func TestSubmitAllowsSameEmailToPostConcurrently(t *testing.T) {
	started := make(chan struct{}, 2)
	release := make(chan struct{})
	released := false
	defer func() {
		if !released {
			close(release)
		}
	}()
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		started <- struct{}{}
		<-release
		_, _ = w.Write([]byte("OK"))
	}))
	defer server.Close()
	service := newTestService(t, Config{HTTPClient: server.Client(), GeoURL: ":", SignupURL: server.URL})
	requests := []Request{
		{FirstName: "Concurrent", LastName: "User", Email: "concurrent@example.com", TermsAccepted: true},
		{FirstName: "Changed", LastName: "Name", Email: "CONCURRENT@EXAMPLE.COM", TermsAccepted: true},
	}

	errors := make(chan error, len(requests))
	for _, request := range requests {
		request := request
		go func() {
			_, err := service.Submit(context.Background(), request)
			errors <- err
		}()
	}
	for count := 0; count < len(requests); count++ {
		select {
		case <-started:
		case <-time.After(time.Second):
			t.Fatalf("only %d same-email requests reached POST concurrently", count)
		}
	}
	close(release)
	released = true
	for range requests {
		if err := <-errors; err != nil {
			t.Fatalf("concurrent Submit() error = %v", err)
		}
	}
	if calls.Load() != 2 {
		t.Fatalf("signup calls = %d, want 2", calls.Load())
	}
}

func TestSubmitAllowsDifferentEmailsToPostConcurrently(t *testing.T) {
	started := make(chan struct{}, 2)
	release := make(chan struct{})
	released := false
	defer func() {
		if !released {
			close(release)
		}
	}()
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		started <- struct{}{}
		<-release
		_, _ = w.Write([]byte("OK"))
	}))
	defer server.Close()

	service := newTestService(t, Config{HTTPClient: server.Client(), GeoURL: ":", SignupURL: server.URL})
	first := Request{FirstName: "Parallel", LastName: "One", Email: "parallel-one@example.com", TermsAccepted: true}
	second := Request{FirstName: "Parallel", LastName: "Two", Email: "parallel-two@example.com", TermsAccepted: true}

	errors := make(chan error, 2)
	for _, request := range []Request{first, second} {
		request := request
		go func() {
			_, submitErr := service.Submit(context.Background(), request)
			errors <- submitErr
		}()
	}
	for count := 0; count < 2; count++ {
		select {
		case <-started:
		case <-time.After(time.Second):
			t.Fatalf("only %d different-email requests reached POST concurrently", count)
		}
	}
	close(release)
	released = true
	for range 2 {
		if err := <-errors; err != nil {
			t.Fatalf("concurrent Submit() error = %v", err)
		}
	}
	if calls.Load() != 2 {
		t.Fatalf("signup calls = %d, want 2", calls.Load())
	}
}

func TestSubmitCanceledBeforePostAllowsLaterCall(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		_, _ = w.Write([]byte("OK"))
	}))
	defer server.Close()
	service := newTestService(t, Config{HTTPClient: server.Client(), GeoURL: ":", SignupURL: server.URL})
	request := Request{FirstName: "Canceled", LastName: "User", Email: "canceled@example.com", TermsAccepted: true}
	canceled, cancel := context.WithCancel(context.Background())
	cancel()

	_, err := service.Submit(canceled, request)
	assertSignupError(t, err, ErrorCodeCanceled, true)
	if calls.Load() != 0 {
		t.Fatalf("signup calls = %d, want no POST for pre-canceled context", calls.Load())
	}
	result, err := service.Submit(context.Background(), request)
	if err != nil || !result.IntakeAcknowledged {
		t.Fatalf("fresh Submit() after pre-send cancellation = %+v, %v", result, err)
	}
	if calls.Load() != 1 {
		t.Fatalf("signup calls = %d, want 1 after fresh request", calls.Load())
	}
}

func TestErrorsAndResultsDoNotExposePII(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()
	service := newTestService(t, Config{HTTPClient: server.Client(), GeoURL: ":", SignupURL: server.URL})
	request := Request{
		FirstName:     "Secret",
		LastName:      "Person",
		Email:         "secret.person@example.com",
		TermsAccepted: true,
	}
	_, err := service.Submit(context.Background(), request)
	assertSignupError(t, err, ErrorCodeOutcomeUnknown, false)
	for _, secret := range []string{"Secret", "secret.person@example.com"} {
		if strings.Contains(err.Error(), secret) {
			t.Fatalf("error %q exposed %q", err, secret)
		}
	}
}

type freeAccountRoundTripFunc func(*http.Request) (*http.Response, error)

func (roundTrip freeAccountRoundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return roundTrip(request)
}

type freeAccountReadErrorBody struct{}

func (freeAccountReadErrorBody) Read([]byte) (int, error) {
	return 0, errors.New("private read failure")
}

func (freeAccountReadErrorBody) Close() error { return nil }

func newTestService(t *testing.T, config Config) *Service {
	t.Helper()
	return New(config)
}

func assertSignupError(t *testing.T, err error, code ErrorCode, retrySafe bool) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected %s error", code)
	}
	var signupErr *Error
	if !errors.As(err, &signupErr) {
		t.Fatalf("error type = %T, want *Error", err)
	}
	if signupErr.Code != code || signupErr.RetrySafe != retrySafe {
		t.Fatalf("error = %+v, want code=%s retrySafe=%t", signupErr, code, retrySafe)
	}
}
