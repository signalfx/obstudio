"""Loopback-only OTLP/HTTP receiver for the native logging contract fixtures."""

from __future__ import annotations

import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import threading
import time

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)


class LogsReceiver:
    def __init__(self, output: Path):
        self.output = output
        self.lock = threading.Lock()
        self.receipts = {}
        self.releases = {}
        self.closing = False
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)

            def log_message(self, format, *args):
                pass

            def reply(self, status, body, content_type="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    # A client timeout may precede the receiver's acceptance.
                    pass

            def do_GET(self):
                if self.path.startswith("/release-stall/"):
                    key = self.path.removeprefix("/release-stall/")
                    with receiver.lock:
                        receiver.releases.setdefault(key, threading.Event()).set()
                    self.reply(200, b"{}")
                    return
                if not self.path.startswith("/evidence/"):
                    self.reply(404, b"{}")
                    return
                key = self.path.removeprefix("/evidence/")
                with receiver.lock:
                    body = json.dumps(receiver.receipts.get(key, {})).encode()
                self.reply(200, body)

            def do_POST(self):
                signal = "traces" if self.path.endswith("/v1/traces") else "logs"
                suffix = f"/v1/{signal}"
                if not self.path.endswith(suffix):
                    self.reply(404, b"{}")
                    return
                key = self.path.removeprefix("/").removesuffix(suffix)
                scenario = key.rsplit("/", 1)[-1]
                if scenario not in {"healthy", "partial", "stall", "retry", "correlation"} or (signal == "traces" and scenario != "correlation"):
                    self.reply(404, b"{}")
                    return
                try:
                    payload = self.payload()
                    if self.headers.get("Content-Encoding") == "gzip":
                        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
                            payload = compressed.read(1048577)
                    if len(payload) > 1048576:
                        raise ValueError("decoded payload too large")
                    request_type = ExportTraceServiceRequest if signal == "traces" else ExportLogsServiceRequest
                    request = request_type.FromString(payload)
                except (ValueError, OSError, EOFError, DecodeError):
                    self.reply(400, b"{}")
                    return
                if signal == "traces":
                    spans = []
                    for resource in request.resource_spans:
                        attributes = {kv.key: MessageToDict(kv.value) for kv in resource.resource.attributes}
                        for scope in resource.scope_spans:
                            for span in scope.spans:
                                spans.append({
                                    "trace_id": span.trace_id.hex(), "span_id": span.span_id.hex(),
                                    "parent_span_id": span.parent_span_id.hex(), "name": span.name,
                                    "flags": span.flags, "resource": attributes,
                                })
                    with receiver.lock:
                        receipt = receiver.receipts.setdefault(key + "/traces", {"requests": 0, "accepted": 0, "spans": []})
                        receipt["requests"] += 1
                        receipt["accepted"] += len(spans)
                        receipt["spans"].extend(spans)
                        receiver.save()
                    self.reply(200, ExportTraceServiceResponse().SerializeToString(), "application/x-protobuf")
                    return
                records = []
                for resource in request.resource_logs:
                    attributes = {kv.key: MessageToDict(kv.value) for kv in resource.resource.attributes}
                    for scope in resource.scope_logs:
                        for record in scope.log_records:
                            records.append({
                                "body": MessageToDict(record.body),
                                "trace_id": record.trace_id.hex(),
                                "span_id": record.span_id.hex(),
                                "flags": record.flags,
                                "severity": record.severity_number,
                                "timestamp_unix_nano": str(record.time_unix_nano),
                                "attributes": {kv.key: MessageToDict(kv.value) for kv in record.attributes},
                                "resource": attributes,
                            })
                rejected = min(2, len(records)) if scenario == "partial" else 0
                with receiver.lock:
                    release = receiver.releases.setdefault(key, threading.Event())
                    if receiver.closing:
                        release.set()
                    receipt = receiver.receipts.setdefault(key, {
                        "requests": 0, "received": 0, "accepted": 0,
                        "rejected": 0, "pending": 0, "retryable_records": 0, "records": [],
                    })
                    receipt["requests"] += 1
                    receipt["received"] += len(records)
                    receipt["records"].extend(records)
                    receipt["pending"] += len(records)
                    receiver.save()
                if scenario == "stall":
                    release.wait(3)
                elif scenario == "retry":
                    receiver.delay_retry_response()
                with receiver.lock:
                    receipt["pending"] -= len(records)
                    if scenario == "retry":
                        receipt["retryable_records"] += len(records)
                    else:
                        receipt["accepted"] += len(records) - rejected
                        receipt["rejected"] += rejected
                    receiver.save()
                if scenario == "retry":
                    self.reply(503, b"", "application/x-protobuf")
                    return
                response = ExportLogsServiceResponse()
                if rejected:
                    response.partial_success.rejected_log_records = rejected
                    response.partial_success.error_message = "synthetic receiver capacity"
                self.reply(200, response.SerializeToString(), "application/x-protobuf")

            def payload(self):
                if self.headers.get("Transfer-Encoding", "").lower() != "chunked":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1048576:
                        raise ValueError("invalid payload length")
                    return self.rfile.read(length)
                chunks = []
                total = 0
                for _ in range(1024):
                    line = self.rfile.readline(128)
                    if not line.endswith(b"\r\n"):
                        raise ValueError("invalid chunk header")
                    size = int(line.split(b";", 1)[0].strip(), 16)
                    if size == 0:
                        for _ in range(16):
                            if self.rfile.readline(2048) == b"\r\n":
                                return b"".join(chunks)
                        raise ValueError("oversized chunk trailers")
                    total += size
                    if size < 0 or total > 1048576:
                        raise ValueError("invalid chunk size")
                    chunk = self.rfile.read(size)
                    if len(chunk) != size or self.rfile.read(2) != b"\r\n":
                        raise ValueError("incomplete chunk")
                    chunks.append(chunk)
                raise ValueError("too many chunks")

        class Server(ThreadingHTTPServer):
            request_queue_size = 128

        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = False
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True,
        )
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def delay_retry_response(self):
        time.sleep(0.15)

    def save(self):
        temporary = self.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.receipts, indent=2) + "\n")
        temporary.replace(self.output)

    def start(self):
        self.save()
        self.thread.start()

    def close(self):
        with self.lock:
            self.closing = True
            for release in self.releases.values():
                release.set()
        if self.thread.is_alive():
            self.server.shutdown()
        self.server.server_close()
        if self.thread.ident is not None:
            self.thread.join(timeout=2)
