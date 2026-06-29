package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/cloudstore"
	"github.com/signalfx/obstudio/observer/internal/o11yoauth"
)

type fakeCloudStore struct {
	connection o11yoauth.Connection
	deleted    bool
	err        error
	saved      bool
}

func (store *fakeCloudStore) Save(connection o11yoauth.Connection) error {
	if store.err != nil {
		return store.err
	}
	store.connection = connection
	store.saved = true
	return nil
}

func (store *fakeCloudStore) Load() (o11yoauth.Connection, error) {
	if store.err != nil {
		return o11yoauth.Connection{}, store.err
	}
	if store.connection.AccessToken == "" {
		return o11yoauth.Connection{}, cloudstore.ErrNotFound
	}
	return store.connection, nil
}

func (store *fakeCloudStore) Delete() error {
	if store.err != nil {
		return store.err
	}
	store.deleted = true
	store.connection = o11yoauth.Connection{}
	return nil
}

func TestCloudRegisterAlwaysPrintsRegistrationURL(t *testing.T) {
	t.Parallel()
	output := new(bytes.Buffer)
	openedURL := ""
	dependencies := fakeCloudDependencies(&fakeCloudStore{})
	dependencies.openBrowser = func(rawURL string) error {
		openedURL = rawURL
		return nil
	}
	command := newCloudCmdWithDependencies(dependencies)
	command.SetOut(output)
	command.SetArgs([]string{"register"})

	if err := command.Execute(); err != nil {
		t.Fatalf("cloud register error = %v", err)
	}
	if openedURL != defaultCloudRegistrationURL {
		t.Fatalf("opened URL = %q, want %q", openedURL, defaultCloudRegistrationURL)
	}
	if !strings.Contains(output.String(), "Requested Splunk Observability Cloud registration") ||
		!strings.Contains(output.String(), "Registration URL: "+defaultCloudRegistrationURL) {
		t.Fatalf("registration output omitted browser status or URL: %s", output.String())
	}
}

func TestCloudRegisterPrintsFallbackWhenBrowserFails(t *testing.T) {
	t.Parallel()
	output := new(bytes.Buffer)
	dependencies := fakeCloudDependencies(&fakeCloudStore{})
	dependencies.openBrowser = func(string) error { return errors.New("launcher unavailable") }
	command := newCloudCmdWithDependencies(dependencies)
	command.SetOut(output)
	command.SetArgs([]string{"register"})

	if err := command.Execute(); err != nil {
		t.Fatalf("cloud register should provide a URL fallback: %v", err)
	}
	if !strings.Contains(output.String(), "Could not open the default browser automatically: launcher unavailable") ||
		!strings.Contains(output.String(), "Registration URL: "+defaultCloudRegistrationURL) {
		t.Fatalf("registration fallback output = %s", output.String())
	}
}

func TestCloudRegionsListsDirectURLs(t *testing.T) {
	t.Parallel()
	output := new(bytes.Buffer)
	command := newCloudCmdWithDependencies(fakeCloudDependencies(&fakeCloudStore{}))
	command.SetOut(output)
	command.SetArgs([]string{"regions"})

	if err := command.Execute(); err != nil {
		t.Fatalf("cloud regions error = %v", err)
	}
	for _, expected := range []string{
		"us0", "us1", "us2", "eu0", "eu1", "eu2", "au0", "jp0", "sg0",
		"https://app.us1.observability.splunkcloud.com",
		"obstudio cloud login --issuer <issuer-url>",
	} {
		if !strings.Contains(output.String(), expected) {
			t.Fatalf("cloud regions output omitted %q: %s", expected, output.String())
		}
	}
}

func TestCloudLoginRegionResolvesDirectIssuerURL(t *testing.T) {
	t.Parallel()
	store := &fakeCloudStore{}
	dependencies := fakeCloudDependencies(store)
	requestedIssuer := ""
	dependencies.login = func(_ context.Context, options o11yoauth.Options) (o11yoauth.Connection, error) {
		requestedIssuer = options.IssuerURL
		return testCloudConnection(), nil
	}
	command := newCloudCmdWithDependencies(dependencies)
	command.SetOut(new(bytes.Buffer))
	command.SetArgs([]string{"login", "--region", "US1"})

	if err := command.Execute(); err != nil {
		t.Fatalf("cloud login --region error = %v", err)
	}
	if requestedIssuer != "https://app.us1.observability.splunkcloud.com" {
		t.Fatalf("resolved issuer = %q", requestedIssuer)
	}
}

func TestCloudLoginRejectsUnknownRegion(t *testing.T) {
	t.Parallel()
	command := newCloudCmdWithDependencies(fakeCloudDependencies(&fakeCloudStore{}))
	command.SetOut(new(bytes.Buffer))
	command.SetErr(new(bytes.Buffer))
	command.SetArgs([]string{"login", "--region", "moon0"})

	if err := command.Execute(); err == nil || !strings.Contains(err.Error(), "unsupported Splunk Observability Cloud realm") {
		t.Fatalf("cloud login unknown region error = %v", err)
	}
}

func TestCloudLoginRejectsRegionAndIssuerTogether(t *testing.T) {
	t.Parallel()
	command := newCloudCmdWithDependencies(fakeCloudDependencies(&fakeCloudStore{}))
	command.SetOut(new(bytes.Buffer))
	command.SetErr(new(bytes.Buffer))
	command.SetArgs([]string{"login", "--region", "us1", "--issuer", "https://app.us1.signalfx.com"})

	if err := command.Execute(); err == nil || !strings.Contains(err.Error(), "cannot be used together") {
		t.Fatalf("cloud login conflicting region and issuer error = %v", err)
	}
}

func TestCloudLoginStoresTokenButRedactsHumanOutput(t *testing.T) {
	t.Parallel()
	store := &fakeCloudStore{}
	output := new(bytes.Buffer)
	command := newCloudCmdWithDependencies(fakeCloudDependencies(store))
	command.SetOut(output)
	command.SetErr(output)
	command.SetArgs([]string{"login", "--issuer", "http://127.0.0.1:3000"})

	if err := command.Execute(); err != nil {
		t.Fatalf("cloud login error = %v", err)
	}
	if !store.saved || store.connection.AccessToken != "secret-token" {
		t.Fatalf("connection was not stored: %+v", store)
	}
	if strings.Contains(output.String(), "secret-token") {
		t.Fatalf("human output exposed token: %s", output.String())
	}
}

func TestCloudLoginTrustedIntegrationGetsSessionOnlyJSON(t *testing.T) {
	t.Parallel()
	store := &fakeCloudStore{}
	output := new(bytes.Buffer)
	command := newCloudCmdWithDependencies(fakeCloudDependencies(store))
	command.SetOut(output)
	command.SetErr(output)
	command.SetArgs([]string{
		"login",
		"--issuer", "http://127.0.0.1:3000",
		"--client-id", "obstudio-vscode",
		"--no-store",
		"--output=json",
		"--show-token",
	})

	if err := command.Execute(); err != nil {
		t.Fatalf("cloud login error = %v", err)
	}
	if store.saved {
		t.Fatal("session-only login unexpectedly used the OS keychain")
	}
	var result cloudConnectionOutput
	if err := json.Unmarshal(output.Bytes(), &result); err != nil {
		t.Fatalf("decode output: %v\n%s", err, output.String())
	}
	if result.AccessToken != "secret-token" || result.Storage != "session-only" {
		t.Fatalf("unexpected integration output: %+v", result)
	}
}

func TestCloudLoginRejectsSessionOnlyOutputWithoutTrustedHandoff(t *testing.T) {
	t.Parallel()
	output := new(bytes.Buffer)
	command := newCloudCmdWithDependencies(fakeCloudDependencies(&fakeCloudStore{}))
	command.SetOut(output)
	command.SetErr(output)
	command.SetArgs([]string{"login", "--issuer", "http://127.0.0.1:3000", "--no-store", "--output=json"})

	if err := command.Execute(); err == nil || !strings.Contains(err.Error(), "must be used together") {
		t.Fatalf("cloud login error = %v", err)
	}
}

func TestCloudLoginRevokesTokenWhenSecureStorageFails(t *testing.T) {
	t.Parallel()
	store := &fakeCloudStore{err: errors.New("keychain unavailable")}
	revoked := false
	dependencies := fakeCloudDependencies(store)
	dependencies.revoke = func(_ context.Context, connection o11yoauth.Connection, _ *http.Client) error {
		revoked = connection.AccessToken == "secret-token"
		return nil
	}
	command := newCloudCmdWithDependencies(dependencies)
	command.SetOut(new(bytes.Buffer))
	command.SetErr(new(bytes.Buffer))
	command.SetArgs([]string{"login", "--issuer", "http://127.0.0.1:3000"})

	if err := command.Execute(); err == nil || !strings.Contains(err.Error(), "issued token was revoked") {
		t.Fatalf("cloud login error = %v", err)
	}
	if !revoked {
		t.Fatal("issued token was not revoked after keychain failure")
	}
}

func TestCloudLogoutRevokesBeforeDeleting(t *testing.T) {
	t.Parallel()
	store := &fakeCloudStore{connection: testCloudConnection()}
	revoked := false
	dependencies := fakeCloudDependencies(store)
	dependencies.revoke = func(_ context.Context, connection o11yoauth.Connection, _ *http.Client) error {
		if store.deleted {
			t.Fatal("store was deleted before revocation")
		}
		if connection.AccessToken != "secret-token" {
			t.Fatalf("unexpected revoked connection: %+v", connection)
		}
		revoked = true
		return nil
	}
	command := newCloudCmdWithDependencies(dependencies)
	command.SetOut(new(bytes.Buffer))
	command.SetArgs([]string{"logout"})

	if err := command.Execute(); err != nil {
		t.Fatalf("cloud logout error = %v", err)
	}
	if !revoked || !store.deleted {
		t.Fatalf("revoked = %v, deleted = %v", revoked, store.deleted)
	}
}

func TestCloudLogoutKeepsCredentialWhenRevocationFails(t *testing.T) {
	t.Parallel()
	store := &fakeCloudStore{connection: testCloudConnection()}
	dependencies := fakeCloudDependencies(store)
	dependencies.revoke = func(context.Context, o11yoauth.Connection, *http.Client) error {
		return errors.New("revocation failed")
	}
	command := newCloudCmdWithDependencies(dependencies)
	command.SetOut(new(bytes.Buffer))
	command.SetErr(new(bytes.Buffer))
	command.SetArgs([]string{"logout"})

	if err := command.Execute(); err == nil || !strings.Contains(err.Error(), "revocation failed") {
		t.Fatalf("cloud logout error = %v", err)
	}
	if store.deleted {
		t.Fatal("credential was deleted after failed revocation")
	}
}

func TestCloudLogoutLocalOnlyReportsNoRevocation(t *testing.T) {
	t.Parallel()
	store := &fakeCloudStore{connection: testCloudConnection()}
	output := new(bytes.Buffer)
	command := newCloudCmdWithDependencies(fakeCloudDependencies(store))
	command.SetOut(output)
	command.SetArgs([]string{"logout", "--local-only", "--output=json"})

	if err := command.Execute(); err != nil {
		t.Fatalf("cloud logout error = %v", err)
	}
	if output.String() != "{\"disconnected\":true,\"revoked\":false}\n" {
		t.Fatalf("unexpected local-only output: %s", output.String())
	}
}

func TestCloudStatusNeverOutputsToken(t *testing.T) {
	t.Parallel()
	store := &fakeCloudStore{connection: testCloudConnection()}
	output := new(bytes.Buffer)
	command := newCloudCmdWithDependencies(fakeCloudDependencies(store))
	command.SetOut(output)
	command.SetArgs([]string{"status", "--output=json"})

	if err := command.Execute(); err != nil {
		t.Fatalf("cloud status error = %v", err)
	}
	if strings.Contains(output.String(), "secret-token") || strings.Contains(output.String(), "accessToken") {
		t.Fatalf("status output exposed token: %s", output.String())
	}
}

func fakeCloudDependencies(store cloudstore.Store) cloudDependencies {
	return cloudDependencies{
		httpClient: http.DefaultClient,
		login: func(context.Context, o11yoauth.Options) (o11yoauth.Connection, error) {
			return testCloudConnection(), nil
		},
		openBrowser: func(string) error { return nil },
		revoke:      func(context.Context, o11yoauth.Connection, *http.Client) error { return nil },
		store:       store,
	}
}

func testCloudConnection() o11yoauth.Connection {
	return o11yoauth.Connection{
		AccessToken: "secret-token",
		ConnectedAt: "2026-06-29T12:00:00Z",
		Endpoint:    "https://ingest.lab0.signalfx.com",
		Issuer:      "http://127.0.0.1:3000",
		OrgID:       "org-1",
		OrgName:     "Example Org",
		Realm:       "lab0",
		Scope:       "api ingest",
		TokenID:     "token-1",
		TokenName:   "Obstudio test",
		TokenType:   "Bearer",
	}
}
