"""Deterministic checks for the default local application-log contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
LANGUAGES = SKILLS / "otel-instrument" / "references" / "languages"


def _read(path: Path) -> str:
    assert path.is_file(), f"Expected file not found: {path}"
    return path.read_text(encoding="utf-8")


def _normalized(path: Path) -> str:
    return " ".join(_read(path).split())


def _fenced_code_after(path: Path, marker: str, language: str) -> str:
    section = _read(path).split(marker, 1)[1]
    return section.split(f"```{language}\n", 1)[1].split("\n```", 1)[0]


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def _java_launcher(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    launcher = tmp_path / "otel-entrypoint.sh"
    _write_executable(
        launcher,
        _fenced_code_after(
            LANGUAGES / "java.md",
            "Save this as `otel-entrypoint.sh`:",
            "bash",
        ),
    )
    subprocess.run(["/bin/sh", "-n", launcher], check=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "java",
        """#!/bin/sh
printf 'JAVA_CALLED=1\\n'
printf 'OTEL_LOGS_EXPORTER=%s\\n' "${OTEL_LOGS_EXPORTER-<unset>}"
for arg in "$@"; do
  printf 'ARG=%s\\n' "$arg"
done
""",
    )
    return launcher, {
        "PATH": str(fake_bin),
        "JAVA_TOOL_OPTIONS": "",
        "JDK_JAVA_OPTIONS": "",
        "_JAVA_OPTIONS": "",
    }


def test_audit_selects_missing_supported_local_logs_by_default() -> None:
    audit = _normalized(SKILLS / "otel-audit" / "SKILL.md")
    instrument = _normalized(SKILLS / "otel-instrument" / "SKILL.md")

    for term in (
        "local Observer provider/exporter/bridge",
        "`required` with `instrument_mode: default`",
        "explicitly disabled",
        "operator-owned exporter",
    ):
        assert term in audit

    for term in (
        "Default Local Application Log Export",
        "A request that excludes custom business spans limits span work only",
        "`OTEL_LOGS_EXPORTER=none` disables",
        "exactly one bridge/export path",
        "Obstudio-to-Splunk cloud forwarding is traces and metrics only",
    ):
        assert term in instrument


def test_all_language_guides_define_local_logs_and_cloud_boundary() -> None:
    expected = {
        "python.md": (
            "LoggerProvider",
            "LoggingInstrumentor",
            "BatchLogRecordProcessor",
            "OTLPLogExporter",
        ),
        "node.md": (
            "ConsoleInstrumentation",
            "BatchLogRecordProcessor",
            "OTLPLogExporter",
            "@opentelemetry/exporter-logs-otlp-proto",
            "logRecordProcessors",
        ),
        "java.md": (
            "OTEL_LOGS_EXPORTER",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
            "Logback",
            "Log4j",
            "experimental.capture-mdc-attributes",
        ),
        "go.md": (
            "sdk/log",
            "otlploghttp",
            "otelslog",
            "SetLoggerProvider",
        ),
    }

    for filename, language_terms in expected.items():
        guide = _normalized(LANGUAGES / filename)
        for term in (
            "OTEL_LOGS_EXPORTER",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
            "/v1/logs",
            "cloud forwarding remains traces and metrics only",
            *language_terms,
        ):
            assert term in guide, f"{filename} is missing {term!r}"


def test_language_guides_reject_generic_cloud_header_inheritance() -> None:
    for filename in ("python.md", "node.md", "go.md"):
        guide = _normalized(LANGUAGES / filename)
        for term in (
            "OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
            "move generic OTLP headers to trace/metric signal variables",
            "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL",
            "select the official exporter matching",
        ):
            assert term in guide, f"{filename} is missing {term!r}"

    java = _normalized(LANGUAGES / "java.md")
    assert "Move a direct-cloud `OTEL_EXPORTER_OTLP_ENDPOINT`" in java
    assert "trace- and metric-specific endpoint/header settings" in java


def test_shell_wrappers_only_add_local_log_configuration_for_otlp() -> None:
    python = _read(LANGUAGES / "python.md")
    java = _read(LANGUAGES / "java.md")

    assert 'if [ "$OTEL_LOGS_EXPORTER" = otlp ]; then' in python
    assert "every other explicit\noperator-owned exporter bypass" in python
    assert 'if [ "$OTEL_LOGS_EXPORTER" = none ]; then' in python
    python_none_branch = python.split(
        'if [ "$OTEL_LOGS_EXPORTER" = none ]; then',
        1,
    )[1].split("fi", 1)[0]
    assert "export OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION=false" in python_none_branch
    assert 'if [ "$logs_exporter" != otlp ]; then' in java
    assert 'scan_otel_options "${JAVA_TOOL_OPTIONS:-}"' in java
    assert 'for otel_jvm_arg in "$@"; do' in java
    assert '-Dotel.exporter.otlp.endpoint)' in java
    assert '[ "$generic_endpoint" != "$local_http_endpoint" ]' in java
    assert '[ "$generic_endpoint" != "$local_grpc_endpoint" ]' in java
    assert java.index('if [ "$logs_exporter" != otlp ]; then') < java.index(
        'if [ -n "$generic_endpoint" ]'
    )
    assert "OBSTUDIO_JAVA_LOG_DEFAULTS=system-properties" in java
    assert 'ENTRYPOINT ["/usr/local/bin/otel-entrypoint"]' in java
    assert 'CMD ["java", "-jar", "/opt/app.jar"]' not in java
    assert '"${otel_log_args[@]}"' not in java
    assert "including\n`OTEL_LOGS_EXPORTER=none` -- use the precedence-aware" in java
    assert 'OTEL_LOGS_EXPORTER="${OTEL_LOGS_EXPORTER:-otlp}" \\' not in java


def test_python_cli_preserves_non_otlp_bridge_ownership(tmp_path: Path) -> None:
    launcher = tmp_path / "otel-entrypoint.sh"
    _write_executable(
        launcher,
        _fenced_code_after(
            LANGUAGES / "python.md",
            "## Auto-Instrumentation (CLI Wrapper)",
            "bash",
        ),
    )
    subprocess.run(["/bin/sh", "-n", launcher], check=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "opentelemetry-instrument",
        """#!/bin/sh
printf 'AUTO=%s\\n' "${OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION-<unset>}"
""",
    )
    base_env = {"PATH": str(fake_bin)}

    operator_owned = subprocess.run(
        [launcher, "python", "app.py"],
        env={
            **base_env,
            "OTEL_LOGS_EXPORTER": "console",
            "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "true",
        },
        text=True,
        capture_output=True,
        check=True,
    )
    assert operator_owned.stdout == "AUTO=true\n"

    opted_out = subprocess.run(
        [launcher, "python", "app.py"],
        env={
            **base_env,
            "OTEL_LOGS_EXPORTER": "none",
            "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "true",
        },
        text=True,
        capture_output=True,
        check=True,
    )
    assert opted_out.stdout == "AUTO=false\n"


def test_python_logging_trace_injection_is_version_conditional() -> None:
    python = _read(LANGUAGES / "python.md")
    normalized = " ".join(python.split())

    assert python.count("inject_trace_context=True") >= 2
    assert "0.64b0+" in python
    assert "1.43.0+" in python
    assert "older locked instrumentation version" in normalized
    assert "omit the unsupported `inject_trace_context` argument" in normalized
    assert "it is not a supported `LoggingInstrumentor` option" not in python


def test_java_launcher_ignores_properties_after_the_launch_target(
    tmp_path: Path,
) -> None:
    launcher, base_env = _java_launcher(tmp_path)
    cloud_env = {
        **base_env,
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://cloud.invalid",
        "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=fake-secret",
    }

    application_property = subprocess.run(
        [launcher, "com.example.Main", "-Dotel.logs.exporter=none"],
        env=cloud_env,
        text=True,
        capture_output=True,
    )
    assert application_property.returncode == 1
    assert "move a non-local generic OTLP endpoint" in application_property.stderr
    assert "JAVA_CALLED=1" not in application_property.stdout

    option_value = subprocess.run(
        [
            launcher,
            "--class-path",
            "-Dotel.logs.exporter=none",
            "com.example.Main",
        ],
        env=cloud_env,
        text=True,
        capture_output=True,
    )
    assert option_value.returncode == 1
    assert "move a non-local generic OTLP endpoint" in option_value.stderr

    effective_property = subprocess.run(
        [
            launcher,
            "--class-path",
            "app.jar",
            "-Dotel.logs.exporter=none",
            "com.example.Main",
        ],
        env=cloud_env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "JAVA_CALLED=1" in effective_property.stdout


def test_java_launcher_accepts_local_generic_endpoint_and_empty_exporter(
    tmp_path: Path,
) -> None:
    launcher, base_env = _java_launcher(tmp_path)
    mixed_protocol = subprocess.run(
        [
            launcher,
            "-Dotel.logs.exporter=otlp",
            "-Dotel.exporter.otlp.logs.protocol=grpc",
            "-Dotel.exporter.otlp.logs.endpoint=http://localhost:4317",
            "-version",
        ],
        env={
            **base_env,
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
        },
        text=True,
        capture_output=True,
        check=True,
    )
    assert "JAVA_CALLED=1" in mixed_protocol.stdout

    empty_exporter = subprocess.run(
        [launcher, "-Dotel.logs.exporter=", "-jar", "app.jar"],
        env={
            **base_env,
            "OBSTUDIO_JAVA_LOG_DEFAULTS": "system-properties",
        },
        text=True,
        capture_output=True,
        check=True,
    )
    assert empty_exporter.stdout.count("ARG=-Dotel.logs.exporter=\n") == 1
    assert "ARG=-Dotel.logs.exporter=otlp\n" not in empty_exporter.stdout
    assert (
        "ARG=-Dotel.exporter.otlp.logs.endpoint=http://localhost:4318/v1/logs\n"
        in empty_exporter.stdout
    )


def test_java_launcher_rejects_argfiles_and_ambiguous_option_environments(
    tmp_path: Path,
) -> None:
    launcher, base_env = _java_launcher(tmp_path)

    for env_name in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"):
        argfile = subprocess.run(
            [launcher, "-version"],
            env={**base_env, env_name: "-Dreviewed=true @hidden.options"},
            text=True,
            capture_output=True,
        )
        assert argfile.returncode == 1
        assert "expand Java argument files" in argfile.stderr
        assert "JAVA_CALLED=1" not in argfile.stdout

        for ambiguous in (
            '"-Dreviewed=value with spaces" -Dotel.logs.exporter=none',
            r"-Dreviewed=value\ with\ spaces -Dotel.logs.exporter=none",
        ):
            option_env = subprocess.run(
                [launcher, "-version"],
                env={**base_env, env_name: ambiguous},
                text=True,
                capture_output=True,
            )
            assert option_env.returncode == 1
            assert env_name in option_env.stderr
            assert "move reviewed options to explicit launcher arguments" in (
                option_env.stderr
            )
            assert "JAVA_CALLED=1" not in option_env.stdout

        for control_whitespace in ("\r", "\n", "\f", "\v"):
            option_env = subprocess.run(
                [launcher, "-version"],
                env={
                    **base_env,
                    env_name: (
                        "-Dreviewed=true"
                        f"{control_whitespace}-Dotel.logs.exporter=none"
                    ),
                },
                text=True,
                capture_output=True,
            )
            assert option_env.returncode == 1
            assert env_name in option_env.stderr
            assert "unsupported non-space/tab control whitespace" in (
                option_env.stderr
            )
            assert "JAVA_CALLED=1" not in option_env.stdout

        tab_separated = subprocess.run(
            [launcher, "-version"],
            env={
                **base_env,
                env_name: "-Dreviewed=true\t-Dotel.logs.exporter=none",
            },
            text=True,
            capture_output=True,
            check=True,
        )
        assert "JAVA_CALLED=1" in tab_separated.stdout

    for launcher_args in (
        ["@hidden.options"],
        ["--class-path", "@hidden.options", "com.example.Main"],
    ):
        argfile = subprocess.run(
            [launcher, *launcher_args],
            env=base_env,
            text=True,
            capture_output=True,
        )
        assert argfile.returncode == 1
        assert "expand Java argument files" in argfile.stderr
        assert "JAVA_CALLED=1" not in argfile.stdout


def test_node_shutdown_drains_before_flushing_telemetry(tmp_path: Path) -> None:
    node = _read(LANGUAGES / "node.md")
    handler = node.split("export function installGracefulSignalHandlers", 1)[1].split(
        "```",
        1,
    )[0]

    assert handler.index("await stopAndDrain();") < handler.index(
        "await shutdownOnce();"
    )
    assert "Application drain failed" in handler
    assert "OpenTelemetry shutdown failed" in handler
    assert "signal handlers are already installed" in handler
    assert "forcedExit.unref()" not in handler
    assert "process.exit(failed ? 1 : 0)" in handler
    assert "server.close" in node
    assert "drain every detected queue/worker" in node

    lifecycle = "let shutdownPromise" + node.split("let shutdownPromise", 1)[1].split(
        "\n```",
        1,
    )[0]
    replacements = {
        "let shutdownPromise: Promise<void> | undefined;": "let shutdownPromise;",
        "export function shutdownOnce(): Promise<void> {": "function shutdownOnce() {",
        "type StopAndDrain = () => void | Promise<void>;\n": "",
        "export function installGracefulSignalHandlers(\n"
        "  stopAndDrain: StopAndDrain,\n"
        "): void {": "function installGracefulSignalHandlers(stopAndDrain) {",
        "const handleSignal = (forcedExitCode: number): void => {": (
            "const handleSignal = (forcedExitCode) => {"
        ),
        "catch (error: unknown)": "catch (error)",
    }
    for typed, javascript in replacements.items():
        assert typed in lifecycle
        lifecycle = lifecycle.replace(typed, javascript)

    def run_signal_case(name: str, stop_and_drain: str) -> subprocess.CompletedProcess[str]:
        script = tmp_path / f"{name}.js"
        script.write_text(
            "const fs = require('node:fs');\n"
            "const sdk = { shutdown: async () => fs.writeSync(1, 'FLUSHED\\n') };\n"
            f"{lifecycle}\n"
            f"installGracefulSignalHandlers({stop_and_drain});\n"
            "setInterval(() => {}, 1_000);\n"
            "setImmediate(() => process.kill(process.pid, 'SIGTERM'));\n",
            encoding="utf-8",
        )
        return subprocess.run(
            ["node", script],
            text=True,
            capture_output=True,
            timeout=5,
        )

    success = run_signal_case(
        "success",
        "async () => fs.writeSync(1, 'DRAINED\\n')",
    )
    assert success.returncode == 0
    assert success.stdout == "DRAINED\nFLUSHED\n"

    failure = run_signal_case(
        "failure",
        "async () => { throw new Error('boom'); }",
    )
    assert failure.returncode == 1
    assert failure.stdout == "FLUSHED\n"
    assert "Application drain failed" in failure.stderr


def test_node_non_otlp_exporters_never_add_obstudio_console_bridge() -> None:
    node = _read(LANGUAGES / "node.md")
    operator_owned_branch = node.split(
        "if (configured && configured !== 'otlp') {",
        1,
    )[1].split("const protocol", 1)[0]

    assert "logRecordProcessors: undefined" in operator_owned_branch
    assert "addDefaultLocalLogBridge: false" in operator_owned_branch
    assert "configured !== 'none'" not in operator_owned_branch
    assert "...(addDefaultLocalLogBridge ? [new ConsoleInstrumentation()] : [])" in node


def test_audit_nonlocal_log_conflict_is_a_locked_external_dependency() -> None:
    audit = _normalized(SKILLS / "otel-audit" / "SKILL.md")

    for term in (
        "create an `external follow-up` whose exact `required_fix` and `external_requirement` name the operator-owned configuration change",
        "create the local-log `required`/`default` finding with that external ID in `dependencies`",
        "keeps the executable finding locked",
        "never put this configuration conflict in `scan_blockers`",
    ):
        assert term in audit


def test_language_rubrics_grade_the_default_local_log_contract() -> None:
    rubric_paths = (
        ROOT / "evals/python/flask-basic/eval/qual/instrument.json",
        ROOT / "evals/node/express-basic/eval/qual/instrument.json",
        ROOT / "evals/java/springboot-basic/eval/qual/instrument.json",
        ROOT / "evals/go/kvstore/eval/qual/instrument.json",
    )

    for path in rubric_paths:
        definition = json.loads(_read(path))
        contract = " ".join(definition["rubric"])
        assert "local Observer" in contract
        assert "OTEL_LOGS_EXPORTER=none" in contract
        assert "cloud" in contract


def test_direct_no_custom_span_prompts_still_grade_default_local_logs() -> None:
    rubric_paths = (
        ROOT / "evals/python/flask-basic/eval/qual/instrument.json",
        ROOT / "evals/node/express-basic/eval/qual/instrument.json",
        ROOT / "evals/java/springboot-basic/eval/qual/instrument.json",
        ROOT / "evals/go/kvstore/eval/qual/instrument.json",
    )

    for path in rubric_paths:
        definition = json.loads(_read(path))
        direct_prompt = next(
            prompt["task"]
            for prompt in definition["prompts"]
            if prompt["id"] == "direct"
        ).lower()
        contract = " ".join(definition["rubric"]).lower()

        assert "no custom business spans" in direct_prompt
        assert "local observer" in contract
        assert "default" in contract
        assert "log" in contract

    skill = _read(ROOT / "skills/otel-instrument/SKILL.md")
    assert (
        "a direct request for the standard\n"
        "auto-instrumentation and default-local-log baseline may proceed"
    ) in skill
    assert "not applicable (direct baseline)" in skill
    assert (
        "On the permitted direct baseline\n"
        "  path, link only the absolute `.observe/otel-instrumentation.md` report"
    ) in skill
    assert (
        "When no canonical audit exists, stop before application-code edits"
        not in skill
    )


def test_audit_rubrics_grade_the_default_local_log_gap() -> None:
    rubric_paths = (
        ROOT / "evals/python/flask-basic/eval/qual/audit.json",
        ROOT / "evals/node/express-basic/eval/qual/audit.json",
        ROOT / "evals/java/springboot-basic/eval/qual/audit.json",
        ROOT / "evals/go/kvstore/eval/qual/audit.json",
    )

    for path in rubric_paths:
        definition = json.loads(_read(path))
        contract = " ".join(definition["rubric"])
        assert "required default gap" in contract
        assert "local Observer" in contract
        assert "cloud forwarding limited to traces and metrics" in contract


def test_runtime_evals_prove_structured_logs_preserved_sink_and_opt_out() -> None:
    runtime_cases = {
        ROOT / "evals/python/flask-basic/eval/runtime/instrument.json": (
            "python-flask-basic",
            1,
        ),
        ROOT / "evals/node/express-basic/eval/runtime/instrument.json": (
            "node-express-basic",
            1,
        ),
        ROOT / "evals/go/kvstore/eval/runtime/instrument.json": (
            "go-kvstore",
            3,
        ),
    }

    for path, (service_name, record_count) in runtime_cases.items():
        definition = json.loads(_read(path))
        default_check, opt_out_check = definition["checks"]

        assert default_check["environment"]["CODEX_EVAL_OTEL_LOGS_EXPORTER"] == ""
        assert default_check["stop_services_before_validation"] == ["app"]
        default_logs = next(
            endpoint
            for endpoint in default_check["expect"]["endpoints"]
            if endpoint.get("url") == "/api/query/logs"
        )
        record_check = next(
            check
            for check in default_logs["record_checks"]
            if check["id"] == "request-context-log"
            or check["id"] == "request-context-logs"
        )
        assert record_check["match"] == {"body": "runtime request completed"}
        assert record_check["field_contains"] == {"severityText": "WARN"}
        assert record_check["field_equals"] == {
            "resource.serviceName": service_name
        }
        assert record_check["non_empty"] == ["traceId", "spanId"]
        assert record_check["exact_count"] == record_count
        assert record_check["unique_by"] == ["traceId", "spanId"]
        assert record_check["correlates_with_trace"] is True

        shutdown_check = next(
            check
            for check in default_logs["record_checks"]
            if check["id"] == "shutdown-log"
        )
        assert shutdown_check == {
            "id": "shutdown-log",
            "match": {"body": "runtime shutdown completed"},
            "field_contains": {"severityText": "WARN"},
            "field_equals": {"resource.serviceName": service_name},
            "exact_count": 1,
        }

        default_sink = default_check["expect"]["service_logs"][0]
        assert default_sink["occurrences"]["runtime request completed"] == record_count
        assert default_sink["occurrences"]["runtime shutdown completed"] == 1

        assert opt_out_check["environment"]["CODEX_EVAL_OTEL_LOGS_EXPORTER"] == "none"
        assert opt_out_check["stop_services_before_validation"] == ["app"]
        opt_out_endpoints = opt_out_check["expect"]["endpoints"]
        assert {endpoint["id"] for endpoint in opt_out_endpoints} == {
            "traces",
            "metrics",
            "logs",
        }
        opt_out_logs = next(
            endpoint for endpoint in opt_out_endpoints if endpoint["id"] == "logs"
        )
        assert opt_out_logs["record_checks"] == [
            {
                "id": "no-exported-application-logs",
                "match": {"resource.serviceName": service_name},
                "exact_count": 0,
            }
        ]
        opt_out_sink = opt_out_check["expect"]["service_logs"][0]
        assert opt_out_sink["occurrences"]["runtime request completed"] == record_count
        assert opt_out_sink["occurrences"]["runtime shutdown completed"] == 1


def test_runtime_fixtures_emit_one_shutdown_marker_from_signal_lifecycle() -> None:
    fixture_sources = (
        ROOT / "evals/python/flask-basic/app.py",
        ROOT / "evals/node/express-basic/app.js",
        ROOT / "evals/go/kvstore/cmd/kvstore-server/main.go",
    )

    for path in fixture_sources:
        source = _read(path)
        assert source.count('"runtime shutdown completed"') == 1
        assert "SIGTERM" in source


def test_observer_integration_proves_trace_metric_cloud_boundary_for_logs() -> None:
    handler_test = _read(ROOT / "observer/internal/otlp/httphandler_test.go")
    boundary_case = handler_test.split(
        "func TestPostLogsRemainsLocalWhenCloudExportersConfigured",
        1,
    )[1].split("// Test 4:", 1)[0]

    for term in (
        'postJSON("/v1/traces"',
        'postJSON("/v1/metrics"',
        'postJSON("/v1/logs"',
        "case exported := <-tracesExporter.ch:",
        "case exported := <-metricsExporter.ch:",
        "logs := s.QueryLogs(1)",
        "log request unexpectedly invoked the Splunk metrics exporter",
        "log request unexpectedly invoked the Splunk traces exporter",
    ):
        assert term in boundary_case

    handler = _read(ROOT / "observer/internal/otlp/httphandler.go")
    handler_fields = handler.split("type otlpHTTPHandler struct {", 1)[1].split(
        "}", 1
    )[0]
    log_handler = handler.split(
        "func (h *otlpHTTPHandler) handleLogs",
        1,
    )[1].split("// readBody", 1)[0]
    receiver = _read(ROOT / "observer/internal/otlp/receiver.go")
    receiver_config = receiver.split("type receiverConfig struct {", 1)[1].split(
        "}", 1
    )[0]
    logs_consumer = receiver.split(
        "logsConsumer, err := consumer.NewLogs",
        1,
    )[1].split("if err != nil", 1)[0]
    for fields in (handler_fields, receiver_config):
        assert not any(
            "log" in line.lower() and "export" in line.lower()
            for line in fields.splitlines()
        )
    assert "export" not in log_handler.lower()
    assert "export" not in logs_consumer.lower()
    assert "WithLogsExporter" not in receiver

    readme = _read(ROOT / "evals/README.md")
    assert "supplies live receiver-side proof" in readme
    assert "remains semantic rubric coverage" not in readme


def test_language_rubrics_grade_each_log_acceptance_path_independently() -> None:
    rubric_paths = (
        ROOT / "evals/python/flask-basic/eval/qual/instrument.json",
        ROOT / "evals/node/express-basic/eval/qual/instrument.json",
        ROOT / "evals/java/springboot-basic/eval/qual/instrument.json",
        ROOT / "evals/go/kvstore/eval/qual/instrument.json",
    )

    for path in rubric_paths:
        rubric = [item.lower() for item in json.loads(_read(path))["rubric"]]
        assert any(
            "request-context warning" in item
            and "severity" in item
            and "trace" in item
            and "span" in item
            and "resource identity" in item
            for item in rubric
        ), f"{path} lacks a focused record-integrity rubric"
        assert any(
            "otel_logs_exporter=none" in item and "sink" in item
            for item in rubric
        ), f"{path} lacks a focused opt-out and sink-preservation rubric"
        assert any(
            "cloud" in item and "trace/metric-only" in item
            for item in rubric
        ), f"{path} lacks a focused cloud-boundary rubric"
        assert any(
            "shutdown" in item and "flush" in item
            for item in rubric
        ), f"{path} lacks a focused shutdown rubric"


def test_java_fixture_has_deterministic_request_log_and_runtime_rationale() -> None:
    controller = _read(
        ROOT
        / "evals/java/springboot-basic/src/main/java/com/example/tasks/TaskController.java"
    )
    rationale = _normalized(ROOT / "evals/README.md")

    assert 'LOGGER.warn("runtime request completed")' in controller
    for term in (
        "no live Java runtime eval",
        "checked-in OpenTelemetry Java agent",
        "could pass independently",
        "record fields",
        "opt-out",
    ):
        assert term in rationale


def test_runtime_observer_keeps_grpc_loopback_when_http_is_container_visible() -> None:
    compose_paths = (
        ROOT / "evals/go/chi-basic/eval/runtime/docker-compose.yml",
        ROOT / "evals/go/chi-partial/eval/runtime/docker-compose.yml",
        ROOT / "evals/go/kvstore/eval/runtime/docker-compose.yml",
        ROOT / "evals/node/express-basic/eval/runtime/docker-compose.yml",
        ROOT / "evals/python/fastapi-celery/eval/runtime/docker-compose.yml",
        ROOT / "evals/python/flask-basic/eval/runtime/docker-compose.yml",
    )

    for path in compose_paths:
        compose = _read(path)
        assert "HOST=0.0.0.0" in compose
        assert "OTLP_GRPC_HOST=127.0.0.1" in compose

    observer_main = _read(ROOT / "observer/cmd/obstudio/main.go")
    assert 'valueOrEnv(config.otlpGRPCHost, "OTLP_GRPC_HOST", host)' in observer_main
