package main

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"strings"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

var attributeSchemas = map[string]string{
	"gen_ai.input.messages":      "model/gen-ai/gen-ai-input-messages.json",
	"gen_ai.output.messages":     "model/gen-ai/gen-ai-output-messages.json",
	"gen_ai.tool.call.arguments": "model/gen-ai/gen-ai-tool-call-arguments.json",
	"gen_ai.tool.call.result":    "model/gen-ai/gen-ai-tool-call-result.json",
	"gen_ai.tool.definitions":    "model/gen-ai/gen-ai-tool-definitions.json",
	"gen_ai.retrieval.documents": "model/gen-ai/gen-ai-retrieval-documents.json",
}

type profileSchema struct {
	whole      *jsonschema.Schema
	knownParts map[string]*jsonschema.Schema
	knownItems map[string]*jsonschema.Schema
}

func readJSON(path string) (any, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, errors.New("cannot open JSON input")
	}
	defer file.Close()
	value, err := jsonschema.UnmarshalJSON(file)
	if err != nil {
		return nil, errors.New("invalid JSON input")
	}
	return value, nil
}

func compileSchemas(profile any) (map[string]*profileSchema, error) {
	packet, ok := profile.(map[string]any)
	if !ok {
		return nil, errors.New("profile is not an object")
	}
	otel, _ := packet["otel"].(map[string]any)
	documents, _ := otel["structured_schemas"].(map[string]any)
	compiler := jsonschema.NewCompiler()
	compiler.DefaultDraft(jsonschema.Draft2020)
	compiler.UseLoader(jsonschema.SchemeURLLoader{})
	compiled := make(map[string]*profileSchema)
	for _, path := range attributeSchemas {
		document, exists := documents[path]
		if !exists {
			return nil, errors.New("profile lacks a required complete schema")
		}
		location := "https://local.invalid/" + path
		if err := compiler.AddResource(location, document); err != nil {
			return nil, errors.New("cannot register profile schema")
		}
		schema, err := compiler.Compile(location)
		if err != nil {
			return nil, errors.New("cannot compile complete profile schema")
		}
		entry := &profileSchema{whole: schema}
		if strings.HasSuffix(path, "-messages.json") || strings.HasSuffix(path, "-tool-definitions.json") {
			known := make(map[string]*jsonschema.Schema)
			object, _ := document.(map[string]any)
			definitions, _ := object["$defs"].(map[string]any)
			for name, rawDefinition := range definitions {
				definition, _ := rawDefinition.(map[string]any)
				properties, _ := definition["properties"].(map[string]any)
				typeProperty, _ := properties["type"].(map[string]any)
				kind, ok := typeProperty["const"].(string)
				if !ok {
					continue
				}
				concrete, err := compiler.Compile(location + "#/$defs/" + name)
				if err != nil {
					return nil, errors.New("cannot compile concrete profile definition")
				}
				known[kind] = concrete
			}
			if strings.HasSuffix(path, "-messages.json") {
				entry.knownParts = known
			} else {
				entry.knownItems = known
			}
		}
		compiled[path] = entry
	}
	return compiled, nil
}

func validateValue(schema *profileSchema, value any) error {
	if serialized, ok := value.(string); ok {
		var err error
		value, err = jsonschema.UnmarshalJSON(strings.NewReader(serialized))
		if err != nil {
			return errors.New("structured attribute is not valid JSON")
		}
	}
	if err := schema.whole.Validate(value); err != nil {
		return errors.New("structured attribute violates the complete schema")
	}
	items, _ := value.([]any)
	for _, item := range items {
		object, _ := item.(map[string]any)
		if err := validateKnown(schema.knownItems, object); err != nil {
			return err
		}
		if schema.knownParts != nil {
			parts, _ := object["parts"].([]any)
			for _, part := range parts {
				object, _ := part.(map[string]any)
				if err := validateKnown(schema.knownParts, object); err != nil {
					return err
				}
			}
		}
	}
	return nil
}

func validateKnown(known map[string]*jsonschema.Schema, value map[string]any) error {
	kind, _ := value["type"].(string)
	if concrete := known[kind]; concrete != nil {
		if err := concrete.Validate(value); err != nil {
			return errors.New("known type violates its concrete profile definition")
		}
	}
	return nil
}

// Receipt validation checks present fields, not operation/profile completeness.
func validateReceipt(schemas map[string]*profileSchema, receipt any) (int, error) {
	object, _ := receipt.(map[string]any)
	runs, ok := object["runs"].([]any)
	if !ok || len(runs) == 0 {
		return 0, errors.New("receipt lacks native probe runs")
	}
	var spans []any
	for _, rawRun := range runs {
		run, _ := rawRun.(map[string]any)
		requests, ok := run["native_requests"].([]any)
		if !ok {
			return 0, errors.New("run lacks native request capture")
		}
		for _, rawRequest := range requests {
			request, _ := rawRequest.(map[string]any)
			if request["path"] != "/v1/traces" {
				continue
			}
			records, ok := request["records"].([]any)
			if !ok {
				return 0, errors.New("trace request lacks decoded records")
			}
			spans = append(spans, records...)
		}
	}
	if len(spans) == 0 {
		return 0, errors.New("receipt lacks received spans")
	}
	checked := 0
	for index, rawSpan := range spans {
		span, _ := rawSpan.(map[string]any)
		attributes, ok := span["attributes"].(map[string]any)
		if !ok {
			return checked, fmt.Errorf("span %d lacks decoded attributes", index)
		}
		for attribute, path := range attributeSchemas {
			value, present := attributes[attribute]
			if !present {
				continue
			}
			if err := validateValue(schemas[path], value); err != nil {
				return checked, fmt.Errorf("span %d %s: %w", index, attribute, err)
			}
			checked++
		}
	}
	if checked == 0 {
		return 0, errors.New("receipt has no structured profile attributes to validate")
	}
	return checked, nil
}

func run() error {
	profilePath := flag.String("profile", "eval/inputs/genai-profile-evidence.json", "Complete captured schema packet")
	receiptPath := flag.String("receipt", "", "Native probe receipt with decoded spans")
	schemaPath := flag.String("schema", "", "Single model/gen-ai schema path from the packet")
	valuePath := flag.String("value", "", "JSON value file for single-schema validation")
	flag.Parse()
	if (*receiptPath == "") == (*valuePath == "") || (*schemaPath == "") != (*valuePath == "") {
		return errors.New("choose --receipt or both --schema and --value")
	}
	profile, err := readJSON(*profilePath)
	if err != nil {
		return err
	}
	schemas, err := compileSchemas(profile)
	if err != nil {
		return err
	}
	if *receiptPath != "" {
		receipt, err := readJSON(*receiptPath)
		if err != nil {
			return err
		}
		count, err := validateReceipt(schemas, receipt)
		if err != nil {
			return err
		}
		fmt.Printf("validated %d present structured attributes; operation/profile completeness requires separate source-bound checks\n", count)
		return nil
	}
	schema, ok := schemas[*schemaPath]
	if !ok {
		return errors.New("unknown profile schema")
	}
	value, err := readJSON(*valuePath)
	if err != nil {
		return err
	}
	if err := validateValue(schema, value); err != nil {
		return err
	}
	fmt.Println("validated one structured value; not a telemetry or completeness proof")
	return nil
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
