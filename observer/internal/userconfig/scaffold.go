package userconfig

import (
	"strings"
	"unicode/utf8"

	"go.yaml.in/yaml/v3"
)

const scaffoldHeader = `# ~/.obstudio/config.yaml — Splunk Observability Studio local configuration.
# Per-user, per-machine; applies to every IDE/agent using this obstudio binary.
# Changes are picked up live unless noted.`

const scaffoldWidth = 80

// Scaffold returns the text of a freshly created config file.
func Scaffold() string { return renderScaffold(sections(), table()) }

func renderScaffold(secs []Section, defs []def) string {
	lines := strings.Split(scaffoldHeader, "\n")
	for _, s := range secs {
		lines = append(lines, "", "# "+s.title())
		if s.description() != "" {
			lines = append(lines, wrapComment("# ", s.description())...)
		}
		lines = append(lines, s.name+":")
		for i, d := range defsIn(s, defs) {
			if i > 0 {
				lines = append(lines, "")
			}
			v := d.view()
			lines = append(lines, wrapComment("  # ", v.Description)...)
			if values := valuesText(v); values != "" {
				lines = append(lines, wrapComment("  # ", values)...)
			}
			if v.Apply == ApplyRestart {
				lines = append(lines, "  # Requires restart.")
			}
			if v.Hint != "" {
				lines = append(lines, wrapComment("  # ", v.Hint)...)
			}
			lines = append(lines, "  "+defName(d)+": "+scalarText(v.Default))
		}
	}
	return strings.Join(lines, "\n") + "\n"
}

// valuesText lists the values a setting accepts, or "" when any value of its
// type is accepted.
func valuesText(v Definition) string {
	if v.Type == TypeBool {
		return "Values: true or false."
	}
	if v.Enum == nil {
		return ""
	}
	members := make([]string, len(v.Enum))
	for i, e := range v.Enum {
		members[i] = valueText(e)
	}
	return "Values: " + strings.Join(members, ", ") + "."
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
