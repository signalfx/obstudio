"""Keep Galileo's legacy session access on the patched OTLP transport."""

from galileo.otel import GalileoSpanProcessor
from requests import Session


class _GalileoSession(Session):
    def prepare_request(self, request):
        prepared = super().prepare_request(request)
        # Galileo updates these session headers for each exported batch. The
        # new OTLP client also passes its initial headers on every request.
        for name in ("project", "logstream", "experimentid"):
            if name in self.headers:
                value = self.headers[name]
                if value is None:
                    prepared.headers.pop(name, None)
                else:
                    prepared.headers[name] = value
        if "experimentid" in self.headers and "logstream" not in self.headers:
            prepared.headers.pop("logstream", None)
        if self.headers.get("logstream"):
            prepared.headers.pop("experimentid", None)
        return prepared


def create_span_processor(project: str) -> GalileoSpanProcessor:
    session = _GalileoSession()
    try:
        processor = GalileoSpanProcessor(project=project, session=session)
    except Exception:
        session.close()
        raise
    # Galileo 2.7 still accesses this field on its own exporter. Retain the
    # same session passed through OTLP's supported constructor parameter.
    processor.exporter._session = session
    return processor
