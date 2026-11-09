import json
import http.client
import gzip
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from logging_receiver import LogsReceiver


def payload(count):
    request = ExportLogsServiceRequest()
    scope = request.resource_logs.add().scope_logs.add()
    for i in range(count):
        record = scope.log_records.add()
        record.body.string_value = f"record-{i}"
        record.trace_id = bytes.fromhex("11" * 16)
        record.span_id = bytes.fromhex("22" * 8)
        record.flags = 0
    return request.SerializeToString()


def post(url, data):
    with urlopen(Request(url, data=data, headers={"Content-Type": "application/x-protobuf"}), timeout=2) as response:
        return response.read()


def evidence(receiver, key):
    with urlopen(f"{receiver.url}/evidence/{key}", timeout=2) as response:
        return json.load(response)


def test_receiver_decodes_wire_and_reports_partial_success_without_full_acceptance(tmp_path):
    receiver = LogsReceiver(tmp_path / "receipts.json")
    receiver.start()
    try:
        response = ExportLogsServiceResponse.FromString(post(f"{receiver.url}/java-1/partial/v1/logs", payload(3)))
        assert response.partial_success.rejected_log_records == 2
        receipt = evidence(receiver, "java-1/partial")
        assert (receipt["requests"], receipt["received"], receipt["accepted"], receipt["rejected"], receipt["pending"]) == (1, 3, 1, 2, 0)
        assert receipt["records"][0]["trace_id"] == "11" * 16
        assert json.loads(receiver.output.read_text())["java-1/partial"] == receipt
    finally:
        receiver.close()


def test_invalid_request_does_not_prevent_later_independent_trial(tmp_path):
    receiver = LogsReceiver(tmp_path / "receipts.json")
    receiver.start()
    try:
        with pytest.raises(HTTPError) as error:
            post(f"{receiver.url}/python-1/healthy/v1/logs", b"broken")
        assert error.value.code == 400
        post(f"{receiver.url}/python-2/healthy/v1/logs", payload(1))
        assert evidence(receiver, "python-2/healthy")["accepted"] == 1
        assert evidence(receiver, "python-1/healthy") == {}
    finally:
        receiver.close()


def test_timed_out_client_can_have_late_acceptance_without_releasing_another_trial(tmp_path):
    receiver = LogsReceiver(tmp_path / "receipts.json")
    receiver.start()
    try:
        for key in ("go-1/stall", "node-1/stall"):
            request = Request(f"{receiver.url}/{key}/v1/logs", data=payload(1))
            with pytest.raises(TimeoutError):
                urlopen(request, timeout=0.05)
            receipt = evidence(receiver, key)
            assert (receipt["received"], receipt["accepted"], receipt["pending"]) == (1, 0, 1)
            with urlopen(f"{receiver.url}/release-stall/{key}", timeout=2):
                pass
            deadline = time.monotonic() + 1
            while evidence(receiver, key)["pending"] and time.monotonic() < deadline:
                time.sleep(0.01)
            assert evidence(receiver, key)["accepted"] == 1
    finally:
        receiver.close()


def test_chunked_sdk_requests_are_decoded_and_bad_chunk_does_not_pass(tmp_path):
    receiver = LogsReceiver(tmp_path / "receipts.json")
    receiver.start()
    connection = http.client.HTTPConnection("127.0.0.1", receiver.server.server_port, timeout=2)
    try:
        data = payload(3)
        connection.request("POST", "/node-1/healthy/v1/logs", body=iter([data[:4], data[4:]]), encode_chunked=True)
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        assert evidence(receiver, "node-1/healthy")["accepted"] == 3
        connection.close()
        connection.connect()
        connection.putrequest("POST", "/node-2/healthy/v1/logs")
        connection.putheader("Transfer-Encoding", "chunked")
        connection.endheaders(b"invalid\r\n")
        assert connection.getresponse().status == 400
        assert evidence(receiver, "node-2/healthy") == {}
    finally:
        connection.close()
        receiver.close()


@pytest.mark.parametrize("kind", ["valid", "truncated", "oversized"])
def test_gzip_is_bounded_and_invalid_compression_cannot_create_receipts(tmp_path, kind):
    receiver = LogsReceiver(tmp_path / "receipts.json")
    receiver.start()
    data = gzip.compress(payload(1) if kind != "oversized" else b"x" * 1048577)
    if kind == "truncated":
        data = data[:8]
    request = Request(f"{receiver.url}/python-1/healthy/v1/logs", data=data, headers={"Content-Encoding": "gzip"})
    try:
        if kind == "valid":
            with urlopen(request, timeout=2) as response:
                assert response.status == 200
            assert evidence(receiver, "python-1/healthy")["accepted"] == 1
        else:
            with pytest.raises(HTTPError) as error:
                urlopen(request, timeout=2)
            assert error.value.code == 400
            assert evidence(receiver, "python-1/healthy") == {}
            post(f"{receiver.url}/python-2/healthy/v1/logs", payload(1))
            assert evidence(receiver, "python-2/healthy")["accepted"] == 1
    finally:
        receiver.close()


def test_retryable_unavailability_counts_attempts_without_claiming_acceptance(tmp_path):
    receiver = LogsReceiver(tmp_path / "receipts.json")
    receiver.start()
    try:
        for _ in range(2):
            with pytest.raises(HTTPError) as error:
                post(f"{receiver.url}/java-1/retry/v1/logs", payload(1))
            assert error.value.code == 503
        receipt = evidence(receiver, "java-1/retry")
        assert (receipt["requests"], receipt["received"], receipt["retryable_records"]) == (2, 2, 2)
        assert (receipt["accepted"], receipt["rejected"], receipt["pending"]) == (0, 0, 0)
        post(f"{receiver.url}/java-2/healthy/v1/logs", payload(1))
        assert evidence(receiver, "java-2/healthy")["accepted"] == 1
    finally:
        receiver.close()


def test_delayed_retry_receipt_stays_pending_without_blocking_other_requests(tmp_path, monkeypatch):
    receiver = LogsReceiver(tmp_path / "receipts.json")
    entered = threading.Event()
    release = threading.Event()

    def hold_response():
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(receiver, "delay_retry_response", hold_response)
    receiver.start()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            request = pool.submit(post, f"{receiver.url}/java-1/retry/v1/logs", payload(1))
            try:
                assert entered.wait(1)
                receipt = evidence(receiver, "java-1/retry")
                assert (receipt["received"], receipt["pending"], receipt["accepted"]) == (1, 1, 0)
                assert not request.done()
                post(f"{receiver.url}/python-1/healthy/v1/logs", payload(1))
                assert evidence(receiver, "python-1/healthy")["accepted"] == 1
            finally:
                release.set()
            with pytest.raises(HTTPError) as error:
                request.result(timeout=2)
            assert error.value.code == 503
        receipt = evidence(receiver, "java-1/retry")
        assert (receipt["pending"], receipt["retryable_records"], receipt["accepted"]) == (0, 1, 0)
    finally:
        release.set()
        receiver.close()


def test_trace_and_log_receipts_keep_real_join_fields_separate_from_attributes(tmp_path):
    receiver = LogsReceiver(tmp_path / "receipts.json")
    receiver.start()
    try:
        request = ExportTraceServiceRequest()
        resource = request.resource_spans.add()
        service = resource.resource.attributes.add(key="service.name")
        service.value.string_value = "correlation-service"
        span = resource.scope_spans.add().spans.add(name="operation")
        span.trace_id = bytes.fromhex("11" * 16)
        span.span_id = bytes.fromhex("22" * 8)
        post(f"{receiver.url}/python-1/correlation/v1/traces", request.SerializeToString())
        logs = ExportLogsServiceRequest.FromString(payload(1))
        record = logs.resource_logs[0].scope_logs[0].log_records[0]
        record.trace_id = b""
        record.span_id = b""
        record.attributes.add(key="trace_id").value.string_value = "11" * 16
        post(f"{receiver.url}/python-1/correlation/v1/logs", logs.SerializeToString())
        trace_receipt = evidence(receiver, "python-1/correlation/traces")
        log_receipt = evidence(receiver, "python-1/correlation")
        assert trace_receipt["accepted"] == 1
        assert trace_receipt["spans"][0]["resource"]["service.name"] == {"stringValue": "correlation-service"}
        assert log_receipt["records"][0]["trace_id"] == ""
        assert log_receipt["records"][0]["span_id"] == ""
        assert log_receipt["records"][0]["attributes"]["trace_id"] == {"stringValue": "11" * 16}
    finally:
        receiver.close()
