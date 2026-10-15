package main

import (
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

func TestCapturedSchemas(t *testing.T) {
	profile, err := readJSON("../genai-profile-evidence.json")
	if err != nil {
		t.Fatal(err)
	}
	schemas, err := compileSchemas(profile)
	if err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		name, schema, good, bad string
	}{
		{"input parts", "gen-ai-input-messages.json", `[{"role":"user","parts":[{"type":"text","content":"safe question"}]}]`, `[{"role":"user","content":"legacy string"}]`},
		{"output parts", "gen-ai-output-messages.json", `[{"role":"assistant","parts":[{"type":"text","content":"shipped"}],"finish_reason":"stop"}]`, `[{"role":"assistant","parts":[{"content":"missing type"}]}]`},
		{"tool argument object", "gen-ai-tool-call-arguments.json", `{"order_id":"safe"}`, `["not an object"]`},
		{"tool result object", "gen-ai-tool-call-result.json", `{"state":"shipped"}`, `null`},
		{"tool definition", "gen-ai-tool-definitions.json", `[{"type":"function","name":"lookup_order","parameters":{"type":"object"}}]`, `[{"type":"function","parameters":{"type":"object"}}]`},
		{"retrieval metadata", "gen-ai-retrieval-documents.json", `[{"content":"safe document"}]`, `[{"score":"not numeric"}]`},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			schema := schemas["model/gen-ai/"+test.schema]
			if err := validateValue(schema, test.good); err != nil {
				t.Fatal(err)
			}
			if err := validateValue(schema, test.bad); err == nil {
				t.Fatal("invalid structured source shape passed")
			}
		})
	}
	for _, encoded := range []string{`{}`, `{"runs":[]}`, `{"runs":[{"native_requests":[{"path":"/v1/traces","records":[{"attributes":{}}]}]}]}`, `{"runs":[{"native_requests":[{"path":"/v1/traces","records":[{"attributes":{"gen_ai.tool.call.result":"null"}}]}]}]}`} {
		value, err := jsonschema.UnmarshalJSON(strings.NewReader(encoded))
		if err != nil {
			t.Fatal(err)
		}
		if _, err := validateReceipt(schemas, value); err == nil {
			t.Fatal("empty or invalid receipt passed")
		}
	}
	for _, encoded := range []string{`{"runs":[{"native_requests":[{"path":"/v1/traces","records":[{"attributes":{"gen_ai.tool.call.result":"{\"state\":\"shipped\"}"}}]}]}]}`, `{"runs":[{"native_requests":[{"path":"/v1/traces","records":[{"attributes":{"gen_ai.tool.call.result":{"state":"shipped"}}}]}]}]}`} {
		value, err := jsonschema.UnmarshalJSON(strings.NewReader(encoded))
		if err != nil {
			t.Fatal(err)
		}
		if count, err := validateReceipt(schemas, value); err != nil || count != 1 {
			t.Fatalf("decoded or serialized native value rejected: count=%d error=%v", count, err)
		}
	}
}

func TestKnownDiscriminatorsDoNotFallThroughGeneric(t *testing.T) {
	profile, err := readJSON("../genai-profile-evidence.json")
	if err != nil {
		t.Fatal(err)
	}
	schemas, err := compileSchemas(profile)
	if err != nil {
		t.Fatal(err)
	}
	badParts := map[string]string{
		"text missing content":      `{"type":"text"}`,
		"text wrong content type":   `{"type":"text","content":false}`,
		"tool call missing name":    `{"type":"tool_call","arguments":{"order_id":"safe"}}`,
		"tool call numeric id":      `{"type":"tool_call","name":"lookup_order","id":42,"arguments":{}}`,
		"tool response result key":  `{"type":"tool_call_response","result":{"state":"shipped"}}`,
		"tool response numeric id":  `{"type":"tool_call_response","id":42,"response":false}`,
		"blob missing modality":     `{"type":"blob","content":"YQ=="}`,
		"uri wrong type":            `{"type":"uri","modality":"image","uri":42}`,
		"file missing id":           `{"type":"file","modality":"image"}`,
		"reasoning missing content": `{"type":"reasoning"}`,
	}
	for _, direction := range []string{"input", "output"} {
		schema := schemas["model/gen-ai/gen-ai-"+direction+"-messages.json"]
		for name, part := range badParts {
			t.Run(direction+"/"+name, func(t *testing.T) {
				if err := validateValue(schema, `[{"role":"user","parts":[`+part+`]}]`); err == nil {
					t.Fatal("malformed known part passed via GenericPart")
				}
			})
		}
		for _, part := range []string{
			`{"type":"text","content":"safe"}`,
			`{"type":"tool_call","name":"lookup_order","id":null,"arguments":{"order_id":"safe"}}`,
			`{"type":"tool_call_response","response":false}`,
			`{"type":"tool_call_response","id":null,"response":null}`,
			`{"type":"tool_call_response","response":0}`,
			`{"type":"future_extension","custom_payload":{"enabled":false}}`,
		} {
			if err := validateValue(schema, `[{"role":"user","parts":[`+part+`]}]`); err != nil {
				t.Fatalf("official valid scalar/null/extension shape rejected: %v", err)
			}
		}
	}
	definitions := schemas["model/gen-ai/gen-ai-tool-definitions.json"]
	for _, value := range []string{
		`[{"type":"function","name":"lookup_order","parameters":{"type":42}}]`,
		`[{"type":"function","name":"lookup_order","parameters":"not a schema"}]`,
	} {
		if err := validateValue(definitions, value); err == nil {
			t.Error("malformed known function definition passed via GenericToolDefinition")
		}
	}
	for _, value := range []string{
		`[{"type":"function","name":"lookup_order","parameters":{"type":"object","properties":{"order_id":{"type":"string"}}}}]`,
		`[{"type":"function","name":"lookup_order","parameters":null}]`,
		`[{"type":"future_extension","name":"custom","parameters":"extension-defined"}]`,
	} {
		if err := validateValue(definitions, value); err != nil {
			t.Fatalf("valid function or extension definition rejected: %v", err)
		}
	}
}
