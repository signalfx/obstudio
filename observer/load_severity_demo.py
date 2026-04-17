import json
import os
import time
import urllib.request


def main() -> None:
    ui_port = os.environ.get("PORT", "3000")
    otlp_port = os.environ.get("OTLP_HTTP_PORT", "4318")
    host = os.environ.get("HOST", "127.0.0.1")
    ui_base = f"http://{host}:{ui_port}"
    otlp_logs = f"http://{host}:{otlp_port}/v1/logs"

    records = [
        {"timeUnixNano": "1712700000000000000", "severityText": "TRACE", "body": {"stringValue": "text only: TRACE"}},
        {"timeUnixNano": "1712700000000000001", "severityText": "DEBUG", "body": {"stringValue": "text only: DEBUG"}},
        {"timeUnixNano": "1712700000000000002", "severityText": "INFO", "body": {"stringValue": "text only: INFO"}},
        {"timeUnixNano": "1712700000000000003", "severityText": "NOTICE", "body": {"stringValue": "text only: NOTICE"}},
        {"timeUnixNano": "1712700000000000004", "severityText": "WARN", "body": {"stringValue": "text only: WARN"}},
        {"timeUnixNano": "1712700000000000005", "severityText": "WARNING", "body": {"stringValue": "text only: WARNING"}},
        {"timeUnixNano": "1712700000000000006", "severityText": "ERROR", "body": {"stringValue": "text only: ERROR"}},
        {"timeUnixNano": "1712700000000000007", "severityText": "SEVERE", "body": {"stringValue": "text only: SEVERE"}},
        {"timeUnixNano": "1712700000000000008", "severityText": "CRITICAL", "body": {"stringValue": "text only: CRITICAL"}},
        {"timeUnixNano": "1712700000000000009", "severityText": "FATAL", "body": {"stringValue": "text only: FATAL"}},
        {"timeUnixNano": "1712700000000000010", "severityText": "AUDIT", "body": {"stringValue": "text only: AUDIT"}},
        {"timeUnixNano": "1712700000000000011", "severityNumber": 1, "body": {"stringValue": "number only: TRACE"}},
        {"timeUnixNano": "1712700000000000012", "severityNumber": 5, "body": {"stringValue": "number only: DEBUG"}},
        {"timeUnixNano": "1712700000000000013", "severityNumber": 9, "body": {"stringValue": "number only: INFO"}},
        {"timeUnixNano": "1712700000000000014", "severityNumber": 13, "body": {"stringValue": "number only: WARN"}},
        {"timeUnixNano": "1712700000000000015", "severityNumber": 17, "body": {"stringValue": "number only: ERROR"}},
        {"timeUnixNano": "1712700000000000016", "severityNumber": 21, "body": {"stringValue": "number only: FATAL"}},
        {"timeUnixNano": "1712700000000000017", "severityNumber": 17, "severityText": "SEVERE", "body": {"stringValue": "both fields: aligned error"}},
        {"timeUnixNano": "1712700000000000018", "severityNumber": 9, "severityText": "SEVERE", "body": {"stringValue": "both fields: conflicting, text wins"}},
        {"timeUnixNano": "1712700000000000019", "severityNumber": 5, "severityText": "ERROR", "body": {"stringValue": "both fields: conflicting, text error wins"}},
    ]

    payload = {
        "resourceLogs": [{
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "severity-demo"}}]},
            "scopeLogs": [{
                "scope": {"name": "demo.logger"},
                "logRecords": records,
            }],
        }],
    }

    clear_req = urllib.request.Request(f"{ui_base}/api/data", method="DELETE")
    with urllib.request.urlopen(clear_req, timeout=10) as resp:
        print(f"cleared_ui_status={resp.status}", flush=True)

    post_req = urllib.request.Request(
        otlp_logs,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(post_req, timeout=10) as resp:
        print(f"posted_otlp_status={resp.status}", flush=True)

    print(f"Loaded severity demo logs into {ui_base} (service=severity-demo).", flush=True)
    print("Emitter will stay alive so Observer does not evict the records. Press Ctrl+C to stop it.", flush=True)

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
