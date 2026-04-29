FROM golang:1.25-bookworm AS build

WORKDIR /repo
COPY observer ./observer
COPY skills ./skills
COPY docs/examples.md ./docs/examples.md

WORKDIR /repo/observer
RUN go run ./cmd/stage-skills
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -o /out/obstudio ./cmd/obstudio

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates lsof \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /out/obstudio /usr/local/bin/obstudio
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
