#!/usr/bin/env bash
set -Eeuo pipefail

: "${E2E_RELEASE:?E2E_RELEASE is required}"
: "${E2E_COLLECTOR_NAMESPACE:?E2E_COLLECTOR_NAMESPACE is required}"

case "${E2E_RELEASE}" in
  *[!a-z0-9-]* | "")
    echo "error: invalid E2E_RELEASE" >&2
    exit 2
    ;;
esac
case "${E2E_COLLECTOR_NAMESPACE}" in
  *[!a-z0-9-]* | "")
    echo "error: invalid E2E_COLLECTOR_NAMESPACE" >&2
    exit 2
    ;;
esac

temp_parent="${TMPDIR:-/tmp}"
temp_parent="${temp_parent%/}"
temp_parent="$(cd "${temp_parent}" && pwd -P)"
postrender_dir="$(mktemp -d "${temp_parent}/otel-postrender.XXXXXX")"

cleanup() {
  case "${postrender_dir}" in
    "${temp_parent}"/otel-postrender.*)
      rm -rf "${postrender_dir}"
      ;;
  esac
}
trap cleanup EXIT

resources="${postrender_dir}/resources.yaml"
raw_resources="${postrender_dir}/raw-resources.yaml"
kustomization="${postrender_dir}/kustomization.yaml"
patch="${postrender_dir}/remove-token-env.yaml"

tee "${raw_resources}" >/dev/null
if [ ! -s "${raw_resources}" ]; then
  echo "error: Helm post-render input was empty" >&2
  exit 2
fi

# Helm deep-merges gateway.config. Null overrides remain as literal null
# component blocks in the embedded Collector YAML, so remove only the exact
# test-disabled components before validating or deploying the local profile.
awk '
  {
    value = $0
    sub(/^[[:space:]]+/, "", value)
    if (value == "otlp_http: null" ||
        value == "otlp_http/entities: null" ||
        value == "signalfx: null" ||
        value == "headers_setter: null" ||
        value == "http_forwarder: null" ||
        value == "http_forwarder/opamp_splunk_o11y: null" ||
        value == "opamp/splunk_o11y: null" ||
        value == "zpages: null" ||
        value == "prometheus/collector: null" ||
        value == "logs/entities: null" ||
        value == "metrics/collector: null") {
      next
    }
    print
  }
' "${raw_resources}" > "${resources}"

printf '%s\n' \
  'apiVersion: kustomize.config.k8s.io/v1beta1' \
  'kind: Kustomization' \
  'resources:' \
  '  - resources.yaml' \
  'patches:' \
  '  - path: remove-token-env.yaml' \
  '    target:' \
  '      group: apps' \
  '      version: v1' \
  '      kind: Deployment' \
  "      name: ${E2E_RELEASE}-collector" \
  "      namespace: ${E2E_COLLECTOR_NAMESPACE}" \
  > "${kustomization}"

printf '%s\n' \
  'apiVersion: apps/v1' \
  'kind: Deployment' \
  'metadata:' \
  "  name: ${E2E_RELEASE}-collector" \
  "  namespace: ${E2E_COLLECTOR_NAMESPACE}" \
  'spec:' \
  '  template:' \
  '    spec:' \
  '      containers:' \
  '        - name: otel-collector' \
  '          env:' \
  '            - name: SPLUNK_OBSERVABILITY_ACCESS_TOKEN' \
  '              $patch: delete' \
  > "${patch}"

kubectl kustomize "${postrender_dir}"
