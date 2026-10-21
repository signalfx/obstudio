package userconfig

import (
	"strings"
	"unicode/utf8"

	"go.yaml.in/yaml/v3"
)

const scaffoldHeader = `# ~/.obstudio/config.yaml — Splunk Observability Studio local configuration.
# Per-user, per-machine; applies to every IDE/agent using this obstudio binary.
# Changes are picked up live unless noted. Values: use true/false, not yes/no/on/off.
# To stop sending anonymous usage data, run: obstudio telemetry disable`

const scaffoldWidth = 80

// Scaffold returns the text of a freshly created config file.
func Scaffold() string { return renderScaffold(sections(), table()) }

func renderScaffold(secs []Section, defs []def) string {
	lines := strings.Split(scaffoldHeader, "\n")
	for _, s := range secs {
		lines = append(lines, "", s.name+":")
		for i, d := range defsIn(s, defs) {
			if i > 0 {
				lines = append(lines, "")
			}
			v := d.view()
			lines = append(lines, wrapComment("  # ", v.Description)...)
			if v.Apply == ApplyRestart {
				lines = append(lines, "  # Requires restart.")
			}
			lines = append(lines, "  "+defName(d)+": "+scalarText(v.Default))
		}
	}
	return strings.Join(lines, "\n") + "\n"
}

// wrapComment fills words greedily so each line, prefix included, is at most
// scaffoldWidth code points.
func wrapComment(prefix, text string) []string {
	var lines []string
	line := ""
	for _, w := range strings.Split(text, " ") {
		if line == "" {
			line = prefix + w
			continue
		}
		if utf8.RuneCountInString(line)+1+utf8.RuneCountInString(w) > scaffoldWidth {
			lines = append(lines, line)
			line = prefix + w
			continue
		}
		line += " " + w
	}
	return append(lines, line)
}

func scalarText(v any) string {
	out, err := yaml.Marshal(encodeScalar(v))
	if err != nil {
		// A scalar node of a bool, int or string always encodes.
		panic(err)
	}
	return strings.TrimSuffix(string(out), "\n")
}
