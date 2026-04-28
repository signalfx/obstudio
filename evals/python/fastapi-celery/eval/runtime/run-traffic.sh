#!/bin/sh
set -eu

until curl -fsS http://observer:3000/api/health >/dev/null; do
  sleep 1
done

until curl -fsS http://api:8000/health >/dev/null; do
  sleep 1
done

siege -q -b -c 2 -r 3 http://api:8000/health
siege -q -b -c 2 -r 3 http://api:8000/orders

curl -fsS -X POST http://api:8000/orders \
  -H 'Content-Type: application/json' \
  -d '{"product":"widget","quantity":1}' >/dev/null
