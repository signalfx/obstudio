FROM alpine:3.20

RUN apk add --no-cache curl siege
COPY run-traffic.sh /usr/local/bin/run-traffic
RUN chmod +x /usr/local/bin/run-traffic

CMD ["/usr/local/bin/run-traffic"]
