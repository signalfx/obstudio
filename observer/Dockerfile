FROM debian:bookworm-slim

COPY observer/bin/obstudio /usr/local/bin/obstudio
RUN useradd --system --uid 10001 --create-home obstudio

ENV HOST=0.0.0.0
ENV PORT=3000
ENV OTLP_HTTP_PORT=4318
ENV OTLP_GRPC_PORT=4317
ENV OBSTUDIO_OWNER=codex-eval
ENV OBSTUDIO_MODE=docker-runtime-eval

EXPOSE 3000 4318 4317

USER 10001
ENTRYPOINT ["/usr/local/bin/obstudio"]
