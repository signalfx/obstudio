package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/signalfx/obstudio/observer/internal/cloudstore"
	"github.com/signalfx/obstudio/observer/internal/o11yoauth"
)

const (
	defaultCloudRegistrationURL = "https://www.splunk.com/en_us/download/o11y-cloud-free-trial.html"
	defaultCloudScope           = "ingest api"
	defaultCloudRequiredScope   = "ingest"
	defaultCloudTokenName       = "Obstudio local agent token"
	cloudIssuerEnvironment      = "OBSTUDIO_O11Y_ISSUER"
	maxConnectionInputBytes     = 64 * 1024
)

type cloudDependencies struct {
	httpClient  *http.Client
	login       func(context.Context, o11yoauth.Options) (o11yoauth.Connection, error)
	openBrowser func(string) error
	revoke      func(context.Context, o11yoauth.Connection, *http.Client) error
	store       cloudstore.Store
}

type cloudLoginOptions struct {
	clientID      string
	issuer        string
	noStore       bool
	output        string
	region        string
	requiredScope string
	scope         string
	showToken     bool
	timeout       time.Duration
	tokenName     string
}

type cloudLogoutOptions struct {
	connectionStdin bool
	localOnly       bool
	output          string
}

type cloudConnectionOutput struct {
	AccessToken string `json:"accessToken,omitempty"`
	ConnectedAt string `json:"connectedAt,omitempty"`
	Connected   bool   `json:"connected"`
	Endpoint    string `json:"endpoint,omitempty"`
	ExpiresAt   string `json:"expiresAt,omitempty"`
	Issuer      string `json:"issuer,omitempty"`
	OrgID       string `json:"orgId,omitempty"`
	OrgName     string `json:"orgName,omitempty"`
	Realm       string `json:"realm,omitempty"`
	Scope       string `json:"scope,omitempty"`
	Storage     string `json:"storage,omitempty"`
	TokenID     string `json:"tokenId,omitempty"`
	TokenName   string `json:"tokenName,omitempty"`
	TokenType   string `json:"tokenType,omitempty"`
}

type cloudRegion struct {
	Realm  string `json:"realm"`
	Region string `json:"region"`
	URL    string `json:"url"`
}

var cloudRegions = []cloudRegion{
	{Realm: "us0", Region: "AWS US East (Virginia)", URL: "https://app.us0.observability.splunkcloud.com"},
	{Realm: "us1", Region: "AWS US West (Oregon)", URL: "https://app.us1.observability.splunkcloud.com"},
	{Realm: "us2", Region: "Google Cloud US West (Oregon)", URL: "https://app.us2.observability.splunkcloud.com"},
	{Realm: "eu0", Region: "AWS Europe (Dublin)", URL: "https://app.eu0.observability.splunkcloud.com"},
	{Realm: "eu1", Region: "AWS Europe (Frankfurt)", URL: "https://app.eu1.observability.splunkcloud.com"},
	{Realm: "eu2", Region: "AWS Europe (London)", URL: "https://app.eu2.observability.splunkcloud.com"},
	{Realm: "au0", Region: "AWS Asia Pacific (Sydney)", URL: "https://app.au0.observability.splunkcloud.com"},
	{Realm: "jp0", Region: "AWS Asia Pacific (Tokyo)", URL: "https://app.jp0.observability.splunkcloud.com"},
	{Realm: "sg0", Region: "AWS Asia Pacific (Singapore)", URL: "https://app.sg0.observability.splunkcloud.com"},
}

func newCloudCmd() *cobra.Command {
	return newCloudCmdWithDependencies(cloudDependencies{
		httpClient:  &http.Client{Timeout: 15 * time.Second},
		login:       o11yoauth.Login,
		openBrowser: openExternalURL,
		revoke:      o11yoauth.Revoke,
		store:       cloudstore.Keyring{},
	})
}

func newCloudCmdWithDependencies(dependencies cloudDependencies) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "cloud",
		Short: "Register, connect, inspect, or disconnect Splunk Observability Cloud",
	}
	cmd.AddCommand(newCloudRegisterCmd(dependencies))
	cmd.AddCommand(newCloudRegionsCmd())
	cmd.AddCommand(newCloudLoginCmd(dependencies))
	cmd.AddCommand(newCloudStatusCmd(dependencies))
	cmd.AddCommand(newCloudLogoutCmd(dependencies))
	return cmd
}

func newCloudRegisterCmd(dependencies cloudDependencies) *cobra.Command {
	registrationURL := defaultCloudRegistrationURL
	cmd := &cobra.Command{
		Use:   "register",
		Short: "Open Splunk Observability Cloud Free registration",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if err := dependencies.openBrowser(registrationURL); err != nil {
				fmt.Fprintf(cmd.OutOrStdout(), "Could not open the default browser automatically: %v\n", err)
			} else {
				fmt.Fprintln(cmd.OutOrStdout(), "Requested Splunk Observability Cloud registration in your default browser.")
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Registration URL: %s\n", registrationURL)
			fmt.Fprintln(cmd.OutOrStdout(), "After registration and email verification, run: obstudio cloud regions")
			fmt.Fprintln(cmd.OutOrStdout(), "Then connect with: obstudio cloud login --region <realm>")
			return nil
		},
	}
	cmd.Flags().StringVar(&registrationURL, "url", registrationURL, "Splunk Observability Cloud registration URL")
	return cmd
}

func newCloudRegionsCmd() *cobra.Command {
	output := "human"
	cmd := &cobra.Command{
		Use:   "regions",
		Short: "List supported Splunk Observability Cloud realms and direct URLs",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if err := validateCloudOutput(output); err != nil {
				return err
			}
			if output == "json" {
				return json.NewEncoder(cmd.OutOrStdout()).Encode(cloudRegions)
			}
			fmt.Fprintln(cmd.OutOrStdout(), "REALM  REGION                           DIRECT URL")
			for _, region := range cloudRegions {
				fmt.Fprintf(cmd.OutOrStdout(), "%-5s  %-31s  %s\n", region.Realm, region.Region, region.URL)
			}
			fmt.Fprintln(cmd.OutOrStdout(), "\nInternal or direct issuer: obstudio cloud login --issuer <issuer-url>")
			return nil
		},
	}
	cmd.Flags().StringVar(&output, "output", output, "Output format: human or json")
	return cmd
}

func newCloudLoginCmd(dependencies cloudDependencies) *cobra.Command {
	options := cloudLoginOptions{
		clientID:      "obstudio-cli",
		issuer:        strings.TrimSpace(os.Getenv(cloudIssuerEnvironment)),
		output:        "human",
		requiredScope: defaultCloudRequiredScope,
		scope:         defaultCloudScope,
		timeout:       5 * time.Minute,
		tokenName:     defaultCloudTokenName,
	}
	cmd := &cobra.Command{
		Use:   "login",
		Short: "Connect to an existing Splunk Observability Cloud organization",
		RunE: func(cmd *cobra.Command, _ []string) error {
			return runCloudLogin(cmd, dependencies, options)
		},
	}
	cmd.Flags().StringVar(&options.issuer, "issuer", options.issuer, "Splunk Observability Cloud organization URL (or set "+cloudIssuerEnvironment+")")
	cmd.Flags().StringVar(&options.region, "region", "", "Splunk Observability Cloud realm (run 'obstudio cloud regions')")
	cmd.Flags().StringVar(&options.clientID, "client-id", options.clientID, "Registered OAuth public client ID")
	cmd.Flags().StringVar(&options.scope, "scope", options.scope, "Space-separated OAuth scopes to offer for approval")
	cmd.Flags().StringVar(&options.requiredScope, "required-scope", options.requiredScope, "Minimum scopes required for a successful connection")
	cmd.Flags().StringVar(&options.tokenName, "token-name", options.tokenName, "Display name for the generated access token")
	cmd.Flags().DurationVar(&options.timeout, "timeout", options.timeout, "Maximum time to wait for browser authorization")
	cmd.Flags().StringVar(&options.output, "output", options.output, "Output format: human or json")
	cmd.Flags().BoolVar(&options.noStore, "no-store", false, "Keep the connection session-only instead of using the OS keychain")
	cmd.Flags().BoolVar(&options.showToken, "show-token", false, "Include the token in JSON output for a trusted integration")
	return cmd
}

func runCloudLogin(cmd *cobra.Command, dependencies cloudDependencies, options cloudLoginOptions) error {
	if strings.TrimSpace(options.region) != "" {
		if cmd.Flags().Changed("issuer") {
			return errors.New("--region and --issuer cannot be used together")
		}
		issuer, err := cloudIssuerForRegion(options.region)
		if err != nil {
			return err
		}
		options.issuer = issuer
	}
	if strings.TrimSpace(options.issuer) == "" {
		return fmt.Errorf("OAuth realm or issuer is required: pass --region, pass --issuer, or set %s", cloudIssuerEnvironment)
	}
	if err := validateCloudOutput(options.output); err != nil {
		return err
	}
	if options.showToken && options.output != "json" {
		return errors.New("--show-token requires --output=json")
	}
	if options.showToken != options.noStore {
		return errors.New("--show-token and --no-store must be used together by a trusted integration")
	}
	connection, err := dependencies.login(cmd.Context(), o11yoauth.Options{
		ClientID:      options.clientID,
		HTTPClient:    dependencies.httpClient,
		IssuerURL:     options.issuer,
		OpenBrowser:   dependencies.openBrowser,
		RequiredScope: options.requiredScope,
		Scope:         options.scope,
		Timeout:       options.timeout,
		TokenName:     options.tokenName,
	})
	if err != nil {
		return err
	}
	storage := "session-only"
	if !options.noStore {
		if err := dependencies.store.Save(connection); err != nil {
			revokeErr := dependencies.revoke(cmd.Context(), connection, dependencies.httpClient)
			if revokeErr != nil {
				return fmt.Errorf("OAuth completed, but secure persistence failed and the issued token could not be revoked: storage error: %v; revocation error: %w", err, revokeErr)
			}
			return fmt.Errorf("OAuth completed, but secure persistence is unavailable; the issued token was revoked: %w", err)
		}
		storage = "OS keychain"
	}
	return writeCloudConnection(cmd.OutOrStdout(), connection, storage, options.output, options.showToken)
}

func cloudIssuerForRegion(rawRegion string) (string, error) {
	realm := strings.ToLower(strings.TrimSpace(rawRegion))
	for _, region := range cloudRegions {
		if region.Realm == realm {
			return region.URL, nil
		}
	}
	return "", fmt.Errorf("unsupported Splunk Observability Cloud realm %q; run 'obstudio cloud regions'", rawRegion)
}

func newCloudStatusCmd(dependencies cloudDependencies) *cobra.Command {
	output := "human"
	cmd := &cobra.Command{
		Use:   "status",
		Short: "Show the stored Splunk Observability Cloud connection without exposing its token",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if err := validateCloudOutput(output); err != nil {
				return err
			}
			connection, err := dependencies.store.Load()
			if errors.Is(err, cloudstore.ErrNotFound) {
				if output == "json" {
					return json.NewEncoder(cmd.OutOrStdout()).Encode(cloudConnectionOutput{Connected: false})
				}
				fmt.Fprintln(cmd.OutOrStdout(), "Not connected to Splunk Observability Cloud.")
				return nil
			}
			if err != nil {
				return err
			}
			return writeCloudConnection(cmd.OutOrStdout(), connection, "OS keychain", output, false)
		},
	}
	cmd.Flags().StringVar(&output, "output", output, "Output format: human or json")
	return cmd
}

func newCloudLogoutCmd(dependencies cloudDependencies) *cobra.Command {
	options := cloudLogoutOptions{output: "human"}
	cmd := &cobra.Command{
		Use:   "logout",
		Short: "Revoke and forget the Splunk Observability Cloud connection",
		RunE: func(cmd *cobra.Command, _ []string) error {
			return runCloudLogout(cmd, dependencies, options)
		},
	}
	cmd.Flags().BoolVar(&options.connectionStdin, "connection-stdin", false, "Read one connection JSON object from stdin instead of the OS keychain")
	cmd.Flags().BoolVar(&options.localOnly, "local-only", false, "Forget local credentials without revoking the server-side token")
	cmd.Flags().StringVar(&options.output, "output", options.output, "Output format: human or json")
	return cmd
}

func runCloudLogout(cmd *cobra.Command, dependencies cloudDependencies, options cloudLogoutOptions) error {
	if err := validateCloudOutput(options.output); err != nil {
		return err
	}
	var connection o11yoauth.Connection
	var err error
	if options.connectionStdin {
		connection, err = readCloudConnection(cmd.InOrStdin())
	} else {
		connection, err = dependencies.store.Load()
		if errors.Is(err, cloudstore.ErrNotFound) {
			return writeCloudLogoutResult(cmd.OutOrStdout(), options.output, false)
		}
	}
	if err != nil {
		return err
	}
	if !options.localOnly {
		if err := dependencies.revoke(cmd.Context(), connection, dependencies.httpClient); err != nil {
			return err
		}
	}
	if !options.connectionStdin {
		if err := dependencies.store.Delete(); err != nil {
			return err
		}
	}
	return writeCloudLogoutResult(cmd.OutOrStdout(), options.output, !options.localOnly)
}

func readCloudConnection(reader io.Reader) (o11yoauth.Connection, error) {
	limited := io.LimitReader(reader, maxConnectionInputBytes+1)
	payload, err := io.ReadAll(limited)
	if err != nil {
		return o11yoauth.Connection{}, fmt.Errorf("read cloud connection: %w", err)
	}
	if len(payload) > maxConnectionInputBytes {
		return o11yoauth.Connection{}, errors.New("cloud connection input is too large")
	}
	var connection o11yoauth.Connection
	if err := json.Unmarshal(payload, &connection); err != nil {
		return o11yoauth.Connection{}, errors.New("cloud connection input is invalid JSON")
	}
	if strings.TrimSpace(connection.AccessToken) == "" || strings.TrimSpace(connection.Issuer) == "" {
		return o11yoauth.Connection{}, errors.New("cloud connection input is missing its access token or issuer")
	}
	return connection, nil
}

func writeCloudConnection(writer io.Writer, connection o11yoauth.Connection, storage, output string, showToken bool) error {
	if output == "json" {
		result := cloudConnectionOutput{
			ConnectedAt: connection.ConnectedAt,
			Connected:   true,
			Endpoint:    connection.Endpoint,
			ExpiresAt:   connection.ExpiresAt,
			Issuer:      connection.Issuer,
			OrgID:       connection.OrgID,
			OrgName:     connection.OrgName,
			Realm:       connection.Realm,
			Scope:       connection.Scope,
			Storage:     storage,
			TokenID:     connection.TokenID,
			TokenName:   connection.TokenName,
			TokenType:   connection.TokenType,
		}
		if showToken {
			result.AccessToken = connection.AccessToken
		}
		return json.NewEncoder(writer).Encode(result)
	}
	fmt.Fprintln(writer, "Connected to Splunk Observability Cloud.")
	if connection.OrgName != "" {
		fmt.Fprintf(writer, "Organization: %s\n", connection.OrgName)
	}
	if connection.Realm != "" {
		fmt.Fprintf(writer, "Realm: %s\n", connection.Realm)
	}
	if connection.Scope != "" {
		fmt.Fprintf(writer, "Scopes: %s\n", connection.Scope)
	}
	fmt.Fprintf(writer, "Storage: %s\n", storage)
	if storage == "OS keychain" {
		fmt.Fprintln(writer, "Restart any running standalone Obstudio process to load this connection.")
	}
	return nil
}

func writeCloudLogoutResult(writer io.Writer, output string, revoked bool) error {
	if output == "json" {
		return json.NewEncoder(writer).Encode(map[string]bool{"disconnected": true, "revoked": revoked})
	}
	if revoked {
		fmt.Fprintln(writer, "Splunk Observability Cloud token revoked and local connection removed.")
	} else {
		fmt.Fprintln(writer, "No stored Splunk Observability Cloud connection was found.")
	}
	return nil
}

func validateCloudOutput(output string) error {
	if output != "human" && output != "json" {
		return errors.New("--output must be human or json")
	}
	return nil
}

func openExternalURL(rawURL string) error {
	var command string
	var arguments []string
	switch runtime.GOOS {
	case "darwin":
		command = "open"
		arguments = []string{rawURL}
	case "windows":
		command = "rundll32"
		arguments = []string{"url.dll,FileProtocolHandler", rawURL}
	default:
		command = "xdg-open"
		arguments = []string{rawURL}
	}
	return exec.Command(command, arguments...).Run()
}
