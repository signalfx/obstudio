// Package freeaccount submits Splunk Observability Cloud Free Edition signup
// requests without retaining personal information after submission.
package freeaccount

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"
	"unicode"
	"unicode/utf16"
	"unicode/utf8"
)

const (
	defaultSignupURL         = "https://www.splunk.com/api/bin/observability/sfx-signup"
	defaultGeoURL            = "https://www.splunk.com/api/bin/user/location"
	defaultCountry           = "United States"
	defaultState             = "California"
	defaultRealm             = "us1"
	defaultMarketRegion      = "AMER"
	signupRegionUS           = "us"
	signupRegionIreland      = "Europe (Ireland)"
	signupRegionAustralia    = "apac-au"
	maxResponseBytes         = 64 * 1024
	maxFirstNameLength       = 40
	maxLastNameLength        = 40
	maxEmailLength           = 80
	profanityResponseMessage = "Profanity not allowed into the form values"
	successfulSignupMessage  = "Thank you for registering. Your free edition account is on its way!\n\n" +
		"You will receive an email within 10 minutes. Check your spam folder if it doesn’t arrive. If you still need help, please reach out to Splunk Support.\n\n" +
		"[Observability Docs.](https://docs.splunk.com/Observability/get-started/welcome.html#nav-Welcome-to-Splunk-Observability-Cloud) Get guidance on how to use Splunk Observability.\n\n" +
		"[Observability Cloud Demo.](https://www.splunk.com/en_us/resources/videos/watch-splunks-observability-cloud-demo.html) Watch Splunk Observability Cloud work in real-time.\n\n" +
		"[Getting Data into Splunk Observability Cloud.](https://education.splunk.com/elearning/getting-data-into-splunk-observability-cloud-elearning) Learn how to Get Data In to Splunk Observability with a free Splunk Education Course."
)

type signupResponseClassification string

const (
	signupResponseAcknowledged signupResponseClassification = "acknowledged"
	signupResponseDeniedPerson signupResponseClassification = "denied_person"
	signupResponseProfanity    signupResponseClassification = "profanity"
	signupResponseRejected     signupResponseClassification = "rejected"
	signupResponseUnrecognized signupResponseClassification = "unrecognized"
	signupResponseReadError    signupResponseClassification = "read_error"
	signupResponseTooLarge     signupResponseClassification = "too_large"
)

var errResponseTooLarge = errors.New("remote response is too large")

// ErrorCode identifies a safe, user-facing signup failure category.
type ErrorCode string

const (
	ErrorCodeValidation     ErrorCode = "validation_error"
	ErrorCodeRejected       ErrorCode = "submission_rejected"
	ErrorCodeOutcomeUnknown ErrorCode = "outcome_unknown"
	ErrorCodeCanceled       ErrorCode = "request_canceled"
)

// Error is a signup error that is safe to return through Observer APIs.
type Error struct {
	Code      ErrorCode `json:"code"`
	Message   string    `json:"error"`
	RetrySafe bool      `json:"retrySafe"`
}

func (e *Error) Error() string { return e.Message }

// Request contains the minimum user input required for signup. Region, when
// present, is an exact option value from Splunk's public Free Edition form.
type Request struct {
	FirstName     string `json:"firstName"`
	LastName      string `json:"lastName"`
	Email         string `json:"email"`
	Region        string `json:"region,omitempty"`
	TermsAccepted bool   `json:"termsAccepted"`
}

// RegionResult describes the exact public-form signup region selected from the
// coarse location returned by Splunk. Location details remain internal.
type RegionResult struct {
	Region string `json:"region"`
}

// Result describes acknowledgement of signup intake. Region is the exact
// public-form value sent to Splunk; Realm is its technical destination. The
// result does not claim that the upstream system finished provisioning an
// organization.
type Result struct {
	IntakeAcknowledged bool   `json:"intakeAcknowledged"`
	Realm              string `json:"realm"`
	Region             string `json:"region"`
	Message            string `json:"message"`
}

// Submitter is implemented by the shared signup service used by REST and MCP.
type Submitter interface {
	Submit(context.Context, Request) (Result, error)
	DetectRegion(context.Context) RegionResult
}

// Config overrides remote endpoints, timeouts, and the local diagnostic log.
// Zero values use production defaults. HTTPClient should not implement
// automatic retries. Diagnostics contain only an upstream status and an
// allowlisted response classification.
type Config struct {
	HTTPClient       *http.Client
	SignupURL        string
	GeoURL           string
	GeoTimeout       time.Duration
	SignupTimeout    time.Duration
	DiagnosticLogger *log.Logger
}

// Service resolves a coarse signup location and submits each validated request
// exactly once. It keeps no submission history.
type Service struct {
	client        *http.Client
	signupURL     string
	geoURL        string
	geoTimeout    time.Duration
	signupTimeout time.Duration
	diagnostics   *log.Logger
}

// New creates a Free Edition signup service.
func New(config Config) *Service {
	client := config.HTTPClient
	if client == nil {
		client = &http.Client{
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		}
	}
	diagnostics := config.DiagnosticLogger
	if diagnostics == nil {
		diagnostics = log.Default()
	}
	return &Service{
		client:        client,
		signupURL:     stringDefault(config.SignupURL, defaultSignupURL),
		geoURL:        stringDefault(config.GeoURL, defaultGeoURL),
		geoTimeout:    durationDefault(config.GeoTimeout, 3*time.Second),
		signupTimeout: durationDefault(config.SignupTimeout, 15*time.Second),
		diagnostics:   diagnostics,
	}
}

// Submit validates, geolocates, and submits a Free Edition request. It never
// automatically retries an upstream signup request.
func (s *Service) Submit(ctx context.Context, request Request) (Result, error) {
	identity, err := validateRequest(request)
	if err != nil {
		return Result{}, err
	}

	location := s.resolveLocation(ctx)
	return s.submitOnce(ctx, identity, location)
}

// DetectRegion resolves the supported public-form signup region without
// submitting or retaining a signup request. Lookup failures return the same
// United States fallback used by Submit.
func (s *Service) DetectRegion(ctx context.Context) RegionResult {
	location := s.resolveLocation(ctx)
	destination, ok := destinationForLocation(location)
	if !ok {
		location = fallbackLocation()
		destination, _ = destinationForLocation(location)
	}
	return RegionResult{
		Region: destination.formRegion,
	}
}

type identity struct {
	firstName string
	lastName  string
	email     string
	region    string
}

func validateRequest(request Request) (identity, error) {
	if !request.TermsAccepted {
		return identity{}, newError(ErrorCodeValidation, "Accept the Splunk Observability Cloud Free Edition Terms of Use before submitting.", true)
	}
	firstName, err := normalizeNamePart(request.FirstName, "first", maxFirstNameLength)
	if err != nil {
		return identity{}, err
	}
	lastName, err := normalizeNamePart(request.LastName, "last", maxLastNameLength)
	if err != nil {
		return identity{}, err
	}

	email := strings.TrimSpace(request.Email)
	if len(email) == 0 || len(email) > maxEmailLength || strings.ContainsAny(email, "\r\n") {
		return identity{}, newError(ErrorCodeValidation, "Enter a valid email address.", true)
	}
	if !validEmail(email) {
		return identity{}, newError(ErrorCodeValidation, "Enter a valid email address.", true)
	}
	region := strings.TrimSpace(request.Region)
	if region != "" {
		if _, ok := destinationForFormRegion(region); !ok {
			return identity{}, newError(ErrorCodeValidation, "Select a supported signup region.", true)
		}
	}
	return identity{
		firstName: firstName,
		lastName:  lastName,
		email:     email,
		region:    region,
	}, nil
}

func normalizeNamePart(value, label string, maxLength int) (string, error) {
	name := strings.Join(strings.Fields(value), " ")
	if name == "" {
		return "", newError(ErrorCodeValidation, fmt.Sprintf("Enter a %s name.", label), true)
	}
	if !utf8.ValidString(name) {
		return "", newError(ErrorCodeValidation, fmt.Sprintf("Enter a valid %s name.", label), true)
	}
	for _, character := range name {
		if unicode.IsControl(character) {
			return "", newError(ErrorCodeValidation, fmt.Sprintf("Enter a valid %s name.", label), true)
		}
	}
	if utf16Length(name) > maxLength {
		return "", newError(ErrorCodeValidation, fmt.Sprintf("%s name must be 40 characters or fewer.", strings.ToUpper(label[:1])+label[1:]), true)
	}
	return name, nil
}

func utf16Length(value string) int {
	length := 0
	for _, character := range value {
		length += utf16.RuneLen(character)
	}
	return length
}

func validEmail(value string) bool {
	if strings.Count(value, "@") != 1 {
		return false
	}
	local, domain, _ := strings.Cut(value, "@")
	if local == "" || len(local) > 64 || domain == "" || !strings.Contains(domain, ".") {
		return false
	}
	for _, character := range local {
		if !((character >= 'a' && character <= 'z') ||
			(character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') ||
			strings.ContainsRune(".!#$%&'*+-/=?^_`{|}~", character)) {
			return false
		}
	}
	if strings.HasPrefix(local, ".") || strings.HasSuffix(local, ".") || strings.Contains(local, "..") {
		return false
	}
	for _, label := range strings.Split(domain, ".") {
		if label == "" || len(label) > 63 || strings.HasPrefix(label, "-") || strings.HasSuffix(label, "-") {
			return false
		}
		for _, character := range label {
			if !((character >= 'a' && character <= 'z') ||
				(character >= 'A' && character <= 'Z') ||
				(character >= '0' && character <= '9') || character == '-') {
				return false
			}
		}
	}
	return true
}

type signupLocation struct {
	country      string
	countryCode  string
	state        string
	city         string
	postalCode   string
	marketRegion string
	source       string
}

type signupDestination struct {
	formRegion string
	realm      string
}

func destinationForFormRegion(region string) (signupDestination, bool) {
	switch region {
	case signupRegionUS:
		return signupDestination{formRegion: signupRegionUS, realm: defaultRealm}, true
	case signupRegionIreland:
		return signupDestination{formRegion: signupRegionIreland, realm: "eu0"}, true
	case signupRegionAustralia:
		return signupDestination{formRegion: signupRegionAustralia, realm: "au0"}, true
	default:
		return signupDestination{}, false
	}
}

func fallbackLocation() signupLocation {
	return signupLocation{
		country:      defaultCountry,
		countryCode:  "US",
		state:        defaultState,
		marketRegion: defaultMarketRegion,
		source:       "fallback",
	}
}

func destinationForLocation(location signupLocation) (signupDestination, bool) {
	switch strings.ToUpper(strings.TrimSpace(location.countryCode)) {
	case "US":
		return destinationForFormRegion(signupRegionUS)
	case "IE", "DE", "GB":
		return destinationForFormRegion(signupRegionIreland)
	case "AU", "NZ", "JP", "SG":
		return destinationForFormRegion(signupRegionAustralia)
	}

	switch strings.ToUpper(strings.TrimSpace(location.marketRegion)) {
	case "AMER", "LATAM":
		return destinationForFormRegion(signupRegionUS)
	case "EMEA":
		return destinationForFormRegion(signupRegionIreland)
	case "ANZ", "APAC":
		return destinationForFormRegion(signupRegionAustralia)
	default:
		return signupDestination{}, false
	}
}

func (s *Service) resolveLocation(ctx context.Context) signupLocation {
	location, err := s.lookupLocation(ctx)
	if err != nil || !validLocationValue(location.country) || !validLocationValue(location.state) {
		return fallbackLocation()
	}
	if _, ok := destinationForLocation(location); !ok {
		return fallbackLocation()
	}
	location.source = "splunk_geoip"
	return location
}

func validLocationValue(value string) bool {
	value = strings.TrimSpace(value)
	if value == "" || len(value) > 100 || !utf8.ValidString(value) {
		return false
	}
	for _, character := range value {
		if unicode.IsControl(character) {
			return false
		}
	}
	return true
}

func (s *Service) lookupLocation(ctx context.Context) (signupLocation, error) {
	lookupCtx, cancel := context.WithTimeout(ctx, s.geoTimeout)
	defer cancel()
	request, err := http.NewRequestWithContext(lookupCtx, http.MethodGet, s.geoURL, nil)
	if err != nil {
		return signupLocation{}, err
	}
	request.Header.Set("Accept", "application/json")
	response, err := s.client.Do(request)
	if err != nil {
		return signupLocation{}, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return signupLocation{}, fmt.Errorf("location lookup returned HTTP %d", response.StatusCode)
	}
	body, err := readBounded(response.Body)
	if err != nil {
		return signupLocation{}, err
	}

	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		return signupLocation{}, err
	}
	locationValues, ok := payload["data"].(map[string]any)
	if !ok {
		return signupLocation{}, errors.New("location lookup response is missing data")
	}
	marketRegion := firstString(locationValues, "salesRegion", "sales_region")
	if marketRegion == "" {
		marketRegion = firstString(payload, "region", "salesRegion", "sales_region")
	}
	return signupLocation{
		country:      firstString(locationValues, "countryName", "country_name", "country"),
		countryCode:  firstString(locationValues, "countryCode", "country_code"),
		state:        firstString(locationValues, "region", "regionName", "region_name", "state"),
		city:         optionalLocationValue(firstString(locationValues, "city"), 100),
		postalCode:   optionalLocationValue(firstString(locationValues, "postalCode", "postal_code"), 20),
		marketRegion: marketRegion,
	}, nil
}

func optionalLocationValue(value string, maxLength int) string {
	value = strings.TrimSpace(value)
	if value == "" || len(value) > maxLength || !utf8.ValidString(value) {
		return ""
	}
	for _, character := range value {
		if unicode.IsControl(character) {
			return ""
		}
	}
	return value
}

type signupPayload struct {
	FirstName          string `json:"firstName"`
	LastName           string `json:"lastName"`
	EmailAddress       string `json:"emailAddress"`
	Title              string `json:"title"`
	BusinessPhone      string `json:"busPhone"`
	Company            string `json:"company"`
	Country            string `json:"country"`
	State              string `json:"state"`
	City               string `json:"city"`
	PostalCode         string `json:"postalCode"`
	Region             string `json:"region"`
	PrivacyPolicyCheck string `json:"privacyPolicyCheck"`
	MarketingOptIn     string `json:"optInFlag1"`
	PhoneOptIn         string `json:"Phone_Opt_In__c"`
	Role               string `json:"role"`
	AssetType          string `json:"AssetType"`
	FormName           string `json:"formname"`
	URLName            string `json:"urlName"`
}

func (s *Service) submitOnce(ctx context.Context, identity identity, location signupLocation) (Result, error) {
	if ctx.Err() != nil {
		return Result{}, newError(ErrorCodeCanceled, "The signup request was canceled before it was sent.", true)
	}
	destination, ok := destinationForFormRegion(identity.region)
	if identity.region == "" {
		destination, ok = destinationForLocation(location)
		if !ok {
			location = fallbackLocation()
			destination, _ = destinationForLocation(location)
		}
	}
	payload := signupPayload{
		FirstName:          identity.firstName,
		LastName:           identity.lastName,
		EmailAddress:       identity.email,
		Title:              "Developer",
		BusinessPhone:      "",
		Company:            "dev",
		Country:            location.country,
		State:              location.state,
		City:               location.city,
		PostalCode:         location.postalCode,
		Region:             destination.formRegion,
		PrivacyPolicyCheck: "1",
		MarketingOptIn:     "0",
		PhoneOptIn:         "Undecided",
		Role:               "MKTO",
		AssetType:          "Trial",
		FormName:           "Trial",
		URLName:            "https://www.splunk.com/en_us/download/observability-cloud-free-edition.html",
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return Result{}, outcomeUnknownError()
	}

	submitCtx, cancel := context.WithTimeout(ctx, s.signupTimeout)
	defer cancel()
	request, err := http.NewRequestWithContext(submitCtx, http.MethodPost, s.signupURL, bytes.NewReader(body))
	if err != nil {
		return Result{}, outcomeUnknownError()
	}
	request.Header.Set("Accept", "application/json")
	request.Header.Set("Content-Type", "application/json; charset=utf-8")
	if submitCtx.Err() != nil {
		return Result{}, newError(ErrorCodeCanceled, "The signup request was canceled before it was sent.", true)
	}
	response, err := s.client.Do(request)
	if err != nil {
		return Result{}, outcomeUnknownError()
	}
	defer response.Body.Close()
	responseBody, err := readBounded(response.Body)
	if err != nil {
		classification := signupResponseReadError
		if errors.Is(err, errResponseTooLarge) {
			classification = signupResponseTooLarge
		}
		s.recordSignupResponseDiagnostic(response.StatusCode, classification)
		return Result{}, outcomeUnknownError()
	}

	classification := classifySignupResponse(response.StatusCode, responseBody)
	s.recordSignupResponseDiagnostic(response.StatusCode, classification)
	switch classification {
	case signupResponseAcknowledged:
		return Result{
			IntakeAcknowledged: true,
			Realm:              destination.realm,
			Region:             destination.formRegion,
			Message:            successfulSignupMessage,
		}, nil
	case signupResponseDeniedPerson:
		return Result{}, newError(
			ErrorCodeRejected,
			"Splunk returned a Denied Person response for this Free Edition signup. This may be a screening decision or a screening-service failure; contact Splunk Support before trying again.",
			true,
		)
	case signupResponseProfanity:
		return Result{}, newError(
			ErrorCodeRejected,
			"Splunk rejected this Free Edition signup because a form value triggered its profanity filter. Review the entered values before trying again.",
			true,
		)
	case signupResponseRejected:
		return Result{}, newError(
			ErrorCodeRejected,
			"Splunk returned a validation rejection for this Free Edition signup. Review the entered values before trying again.",
			true,
		)
	default:
		return Result{}, outcomeUnknownError()
	}
}

func (s *Service) recordSignupResponseDiagnostic(statusCode int, classification signupResponseClassification) {
	s.diagnostics.Printf("[freeaccount] signup_response status=%d classification=%s", statusCode, classification)
}

func classifySignupResponse(statusCode int, body []byte) signupResponseClassification {
	acceptedStatus := statusCode >= http.StatusOK && statusCode < http.StatusMultipleChoices
	rejectedStatus := statusCode == http.StatusBadRequest || statusCode == http.StatusUnprocessableEntity
	if acceptedStatus && signupIntakeAcknowledged(body) {
		return signupResponseAcknowledged
	}
	if (acceptedStatus || rejectedStatus) && signupDenied(body) {
		return signupResponseDeniedPerson
	}
	if (acceptedStatus || rejectedStatus) && signupProfanity(body) {
		return signupResponseProfanity
	}
	if rejectedStatus {
		return signupResponseRejected
	}
	return signupResponseUnrecognized
}

func signupIntakeAcknowledged(body []byte) bool {
	trimmed := strings.TrimSpace(string(body))
	if trimmed == "OK" {
		return true
	}
	var value string
	return json.Unmarshal(body, &value) == nil && value == "OK"
}

func signupDenied(body []byte) bool {
	return signupResponseMessageIs(body, "Denied Person")
}

func signupProfanity(body []byte) bool {
	return signupResponseMessageIs(body, profanityResponseMessage)
}

func signupResponseMessageIs(body []byte, expected string) bool {
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		return false
	}
	message, _ := payload["message"].(string)
	return strings.EqualFold(strings.TrimSpace(message), expected)
}

func readBounded(reader io.Reader) ([]byte, error) {
	body, err := io.ReadAll(io.LimitReader(reader, maxResponseBytes+1))
	if err != nil {
		return nil, err
	}
	if len(body) > maxResponseBytes {
		return nil, errResponseTooLarge
	}
	return body, nil
}

func firstString(values map[string]any, keys ...string) string {
	for _, key := range keys {
		if value, ok := values[key].(string); ok && strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

func newError(code ErrorCode, message string, retrySafe bool) *Error {
	return &Error{Code: code, Message: message, RetrySafe: retrySafe}
}

func outcomeUnknownError() *Error {
	return newError(
		ErrorCodeOutcomeUnknown,
		"The signup outcome is unknown. Check your email before trying again.",
		false,
	)
}

func stringDefault(value, fallback string) string {
	if strings.TrimSpace(value) != "" {
		return strings.TrimSpace(value)
	}
	return fallback
}

func durationDefault(value, fallback time.Duration) time.Duration {
	if value > 0 {
		return value
	}
	return fallback
}
