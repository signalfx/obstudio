FROM golang:1.25-bookworm AS build

WORKDIR /app
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -o /out/app ./cmd/kvstore-server

FROM debian:bookworm-slim

COPY --from=build /out/app /usr/local/bin/app
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/app", "-addr=:8000", "-data-dir=/tmp/kvstore-data"]
