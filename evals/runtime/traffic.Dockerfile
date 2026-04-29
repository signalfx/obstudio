FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl siege \
    && rm -rf /var/lib/apt/lists/*

COPY run-traffic.sh /usr/local/bin/run-traffic
RUN chmod +x /usr/local/bin/run-traffic

CMD ["/usr/local/bin/run-traffic"]
