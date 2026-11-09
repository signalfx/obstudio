#!/bin/sh
set -eu

until curl -fsS http://observer:17900/api/health >/dev/null; do
  sleep 1
done

until curl -fsS 'http://app:8000/search?word=runtime' >/dev/null; do
  sleep 1
done

for _ in 1 2 3; do
  curl -fsS -X PUT http://app:8000/kv/runtime-key --data 'runtime value' >/dev/null
  curl -fsS http://app:8000/kv/runtime-key >/dev/null
  curl -fsS 'http://app:8000/search?word=runtime' >/dev/null
done
