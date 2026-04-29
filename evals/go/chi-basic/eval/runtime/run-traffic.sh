#!/bin/sh
set -eu

until curl -fsS http://observer:3000/api/health >/dev/null; do
  sleep 1
done

until curl -fsS http://app:8000/health >/dev/null; do
  sleep 1
done

siege -q -b -c 2 -r 3 http://app:8000/health
siege -q -b -c 2 -r 3 http://app:8000/tasks

curl -fsS -X POST http://app:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"runtime task"}' >/dev/null
