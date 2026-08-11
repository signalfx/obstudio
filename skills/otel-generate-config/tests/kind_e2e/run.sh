#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FIXTURES_DIR="${SCRIPT_DIR}/fixtures"
COLLECTOR_GENERATOR="${SKILL_DIR}/scripts/generate_collector.py"
COLLECTOR_VALIDATOR="${SKILL_DIR}/scripts/validate_collector.py"
APPLICATION_GENERATOR="${SKILL_DIR}/scripts/generate_application.py"
APPLICATION_VALIDATOR="${SKILL_DIR}/scripts/validate_application.py"
CONFIG_VALIDATOR="${SKILL_DIR}/scripts/validate_config.py"

COLLECTOR_VERSION="${OTEL_E2E_COLLECTOR_VERSION:-0.157.0}"
KIND_NODE_IMAGE="${OTEL_E2E_KIND_NODE_IMAGE:-kindest/node:v1.31.0}"
WAIT_TIMEOUT="${OTEL_E2E_TIMEOUT:-300s}"

while IFS= read -r environment_name; do
  case "${environment_name}" in
    SPLUNK_*TOKEN*|SPLUNK_*SECRET*|SPLUNK_*PASSWORD*|SPLUNK_*CREDENTIAL*|SPLUNK_*API*KEY*|SIGNALFX_*TOKEN*|SIGNALFX_*SECRET*|SIGNALFX_*PASSWORD*|SIGNALFX_*CREDENTIAL*|SIGNALFX_*API*KEY*|SFX_*TOKEN*|SFX_*SECRET*|SFX_*PASSWORD*|SFX_*CREDENTIAL*|SFX_*API*KEY*|OTEL_EXPORTER_*_HEADER|OTEL_EXPORTER_*_HEADERS)
      echo "error: refuse to run while a telemetry credential environment variable is set" >&2
      exit 2
      ;;
  esac
done < <(compgen -e)

if [ -n "${OTEL_E2E_KIND_CLUSTER:-}" ]; then
  echo "error: existing Kind cluster reuse is not supported; unset OTEL_E2E_KIND_CLUSTER" >&2
  exit 2
fi

for command_name in bash docker kind kubectl python3 rg sed; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "error: required command is unavailable: ${command_name}" >&2
    exit 2
  fi
done

for required_file in \
  "${COLLECTOR_GENERATOR}" \
  "${COLLECTOR_VALIDATOR}" \
  "${APPLICATION_GENERATOR}" \
  "${APPLICATION_VALIDATOR}" \
  "${CONFIG_VALIDATOR}"; do
  if [ ! -f "${required_file}" ]; then
    echo "error: required file is unavailable: ${required_file}" >&2
    exit 2
  fi
done

docker info >/dev/null

temp_parent="${TMPDIR:-/tmp}"
temp_parent="${temp_parent%/}"
temp_parent="$(cd "${temp_parent}" && pwd -P)"
WORK_ROOT="$(mktemp -d "${temp_parent}/obstudio-otel-kind.XXXXXX")"
KUBECONFIG_PATH="${WORK_ROOT}/kubeconfig"
export KUBECONFIG="${KUBECONFIG_PATH}"

run_stamp="$(date -u +%H%M%S)-$$"
CLUSTER_NAME="ogc-e2e-${run_stamp}"
CONTEXT="kind-${CLUSTER_NAME}"
CLUSTER_CREATED=false
CLUSTER_AVAILABLE=false
YAML_MANIFESTS=()
TEST_NAMESPACES=()

kubectl_cmd() {
  kubectl --kubeconfig "${KUBECONFIG_PATH}" --context "${CONTEXT}" "$@"
}

diagnostics() {
  local namespace
  if [ "${CLUSTER_AVAILABLE}" != true ]; then
    return
  fi
  echo "Kind E2E diagnostics:" >&2
  kubectl_cmd get nodes -o wide >&2 || true
  for namespace in "${TEST_NAMESPACES[@]}"; do
    echo "namespace ${namespace}:" >&2
    kubectl_cmd -n "${namespace}" get all -o wide >&2 || true
    kubectl_cmd -n "${namespace}" get events --sort-by=.lastTimestamp >&2 || true
  done
}

cleanup() {
  local exit_status="$?"
  local cleanup_status=0
  local namespace manifest
  trap - EXIT INT TERM
  set +e

  if [ "${exit_status}" -ne 0 ]; then
    diagnostics
  fi

  if [ "${CLUSTER_AVAILABLE}" = true ]; then
    for manifest in "${YAML_MANIFESTS[@]-}"; do
      [ -n "${manifest}" ] || continue
      kubectl_cmd delete -f "${manifest}" --ignore-not-found --wait=false >/dev/null 2>&1 \
        || cleanup_status=1
    done
    for namespace in "${TEST_NAMESPACES[@]-}"; do
      [ -n "${namespace}" ] || continue
      kubectl_cmd delete namespace "${namespace}" --ignore-not-found --wait=true --timeout=60s >/dev/null 2>&1 \
        || cleanup_status=1
      if kubectl_cmd get namespace "${namespace}" >/dev/null 2>&1; then
        echo "error: E2E namespace remains after cleanup: ${namespace}" >&2
        cleanup_status=1
      fi
    done
  fi
  if [ "${CLUSTER_CREATED}" = true ]; then
    kind delete cluster --name "${CLUSTER_NAME}" >/dev/null 2>&1 \
      || cleanup_status=1
    if kind get clusters | rg -x -F "${CLUSTER_NAME}" >/dev/null; then
      echo "error: disposable Kind cluster remains after cleanup: ${CLUSTER_NAME}" >&2
      cleanup_status=1
    fi
  fi

  case "${WORK_ROOT}" in
    "${temp_parent}"/obstudio-otel-kind.*)
      rm -rf "${WORK_ROOT}" || cleanup_status=1
      ;;
  esac
  if [ "${cleanup_status}" -ne 0 ]; then
    echo "error: Kind E2E cleanup was incomplete" >&2
    if [ "${exit_status}" -eq 0 ]; then
      exit_status=1
    fi
  fi
  exit "${exit_status}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

fail() {
  echo "error: $*" >&2
  return 1
}

create_owned_namespace() {
  local namespace="$1"
  local existing
  if ! existing="$(kubectl_cmd get namespace "${namespace}" --ignore-not-found -o name)"; then
    fail "could not preflight namespace ownership: ${namespace}"
  fi
  if [ -n "${existing}" ]; then
    fail "refuse to reuse existing namespace: ${namespace}"
  fi
  kubectl_cmd create namespace "${namespace}"
  TEST_NAMESPACES+=("${namespace}")
}

assert_manifest_absent() {
  local manifest="$1"
  local existing
  if ! existing="$(kubectl_cmd get -f "${manifest}" --ignore-not-found -o name)"; then
    fail "could not preflight manifest ownership: ${manifest}"
  fi
  if [ -n "${existing}" ]; then
    printf '%s\n' "${existing}" >&2
    fail "refuse to replace existing resources from manifest: ${manifest}"
  fi
}

assert_runtime_safe() {
  local manifest="$1"
  local secret_name="$2"
  if rg -n -i \
    'observability\.splunkcloud\.com|signalfx\.com|SPLUNK_OBSERVABILITY_ACCESS_TOKEN|splunk_observability_access_token|X-SF-Token|secretKeyRef:|^[[:space:]]*kind:[[:space:]]*Secret[[:space:]]*$|^[[:space:]]*(otlp_http|otlp_http/entities|signalfx|headers_setter|http_forwarder|http_forwarder/opamp_splunk_o11y|opamp/splunk_o11y|zpages|prometheus/collector|logs/entities|metrics/collector):[[:space:]]*null[[:space:]]*$|REPLACE_AT_DEPLOY_TIME' \
    "${manifest}"; then
    fail "unsafe cloud or Secret material in runtime manifest: ${manifest}"
  fi
  if rg -n -F "${secret_name}" "${manifest}"; then
    fail "runtime manifest still references the generated Secret name: ${manifest}"
  fi
}

assert_no_namespace_secrets() {
  local namespace="$1"
  local secrets
  if ! secrets="$(kubectl_cmd -n "${namespace}" get secrets -o name)"; then
    fail "could not verify that namespace has no Secrets: ${namespace}"
  fi
  if [ -n "${secrets}" ]; then
    echo "${secrets}" >&2
    fail "namespace contains a Secret: ${namespace}"
  fi
}

render_checkout_fixture() {
  local app_root="$1"
  local app_namespace="$2"
  local case_id="$3"
  local source_dir="${FIXTURES_DIR}/checkout/kubernetes"
  local destination_dir="${app_root}/kubernetes"
  local trace_id span_id
  trace_id="$(python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:32])' "${case_id}")"
  span_id="$(python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[32:48])' "${case_id}")"
  mkdir -p "${destination_dir}"
  sed \
    -e "s/@@APP_NAMESPACE@@/${app_namespace}/g" \
    -e "s/@@E2E_CASE_VALUE@@/${case_id}/g" \
    "${source_dir}/deployment.yaml.tmpl" \
    > "${destination_dir}/deployment.yaml"
  sed \
    -e "s/@@APP_NAMESPACE@@/${app_namespace}/g" \
    "${source_dir}/kustomization.yaml.tmpl" \
    > "${destination_dir}/kustomization.yaml"
  sed \
    -e "s/@@TRACE_ID@@/${trace_id}/g" \
    -e "s/@@SPAN_ID@@/${span_id}/g" \
    "${source_dir}/traces.json" \
    > "${destination_dir}/traces.json"
  cp "${source_dir}/metrics.json" "${destination_dir}/metrics.json"
  if ! rg -F 's/@@CASE_ID@@/${E2E_CASE_ID}/g' \
    "${destination_dir}/deployment.yaml" >/dev/null \
    || ! rg -F "value: \"${case_id}\"" \
    "${destination_dir}/deployment.yaml" >/dev/null; then
    fail "checkout fixture lost its two-stage case-id substitution contract"
  fi
}

wait_for_debug_evidence() {
  local collector_namespace="$1"
  local release="$2"
  local service_name="$3"
  local case_id="$4"
  local logs_file="$5"
  local attempts=0
  while [ "${attempts}" -lt 60 ]; do
    kubectl_cmd -n "${collector_namespace}" \
      logs "deployment/${release}-collector" --since=5m \
      > "${logs_file}" 2>&1 || true
    if rg -F "${service_name}" "${logs_file}" >/dev/null \
      && rg -F "checkout-kind-${case_id}" "${logs_file}" >/dev/null \
      && rg -F 'checkout.e2e.requests' "${logs_file}" >/dev/null \
      && rg -F "${case_id}" "${logs_file}" >/dev/null; then
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 2
  done
  cat "${logs_file}" >&2 || true
  fail "Collector debug exporter did not show both signals for ${case_id}"
}

render_local_debug_yaml_manifest() {
  local source_manifest="$1"
  local destination_manifest="$2"
  local release="$3"
  local namespace="$4"
  local patch_dir="${destination_manifest%.yaml}-patch"
  local resources="${patch_dir}/resources.yaml"
  local kustomization="${patch_dir}/kustomization.yaml"
  local config_patch="${patch_dir}/collector-config-debug.yaml"
  local env_patch="${patch_dir}/collector-env-debug.yaml"

  mkdir -p "${patch_dir}"
  cp "${source_manifest}" "${resources}"
  cat > "${kustomization}" <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - resources.yaml
patches:
  - path: collector-config-debug.yaml
  - path: collector-env-debug.yaml
EOF
  cat > "${config_patch}" <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: ${release}-collector
  namespace: ${namespace}
data:
  collector.yaml: |
    extensions:
      health_check:
        endpoint: 0.0.0.0:13133

    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318

    processors:
      memory_limiter:
        check_interval: 1s
        limit_percentage: 75
        spike_limit_percentage: 15
      batch: {}

    exporters:
      debug:
        verbosity: detailed
        sampling_initial: 100
        sampling_thereafter: 1

    service:
      extensions:
        - health_check
      pipelines:
        metrics:
          receivers:
            - otlp
          processors:
            - memory_limiter
            - batch
          exporters:
            - debug
        traces:
          receivers:
            - otlp
          processors:
            - memory_limiter
            - batch
          exporters:
            - debug
EOF
  cat > "${env_patch}" <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${release}-collector
  namespace: ${namespace}
spec:
  template:
    spec:
      containers:
        - name: otel-collector
          env:
            - name: SPLUNK_REALM
              \$patch: delete
            - name: SPLUNK_ACCESS_TOKEN
              \$patch: delete
EOF
  kubectl kustomize "${patch_dir}" > "${destination_manifest}"
}

run_case() {
  local short_mode="y"
  local case_id="${short_mode}-${run_stamp}"
  local release="ogc-${case_id}"
  local collector_namespace="ogc-${short_mode}-c-${run_stamp}"
  local app_namespace="ogc-${short_mode}-a-${run_stamp}"
  local secret_name="unused-${case_id}"
  local service_name="checkout-${case_id}"
  local collector_service="${release}-collector"
  local expected_endpoint="http://${collector_service}.${collector_namespace}.svc.cluster.local:4318"
  local case_root="${WORK_ROOT}/yaml"
  local collector_bundle="${case_root}/deploy/otel-collector"
  local app_root="${case_root}/checkout"
  local application_output="${app_root}/deploy/otel-config"
  local production_manifest="${collector_bundle}/kubernetes/collector.yaml"
  local runtime_manifest="${case_root}/collector-runtime.yaml"
  local application_manifest="${case_root}/application-runtime.yaml"
  local logs_file="${case_root}/collector-debug.log"
  local applied_config applied_config_name applied_deployment ready_endpoints application_env expected

  mkdir -p "${case_root}"
  render_checkout_fixture "${app_root}" "${app_namespace}" "${case_id}"

  create_owned_namespace "${collector_namespace}"
  create_owned_namespace "${app_namespace}"

  python3 "${COLLECTOR_GENERATOR}" \
    --output "${collector_bundle}" \
    --realm us0 \
    --cluster-name "${CLUSTER_NAME}" \
    --environment kind-e2e \
    --namespace "${collector_namespace}" \
    --release-name "${release}" \
    --secret-name "${secret_name}" \
    --distribution other \
    --collector-version "${COLLECTOR_VERSION}" \
    --gateway
  python3 "${COLLECTOR_VALIDATOR}" "${collector_bundle}"

  kubectl_cmd apply \
    --dry-run=server \
    --validate=strict \
    -f "${production_manifest}" \
    >/dev/null

  render_local_debug_yaml_manifest \
    "${production_manifest}" \
    "${runtime_manifest}" \
    "${release}" \
    "${collector_namespace}"
  assert_runtime_safe "${runtime_manifest}" "${secret_name}"

  (
    cd "${case_root}"
    python3 "${APPLICATION_GENERATOR}" \
      --workspace-root "${case_root}" \
      --app "${app_root}" \
      --platform kubernetes \
      --realm us0 \
      --collector-namespace "${collector_namespace}" \
      --collector-release "${release}" \
      --topology gateway \
      --secret-name "${secret_name}" \
      --collector-evidence "${production_manifest}" \
      --protocol http/protobuf \
      --base kubernetes \
      --application-namespace "${app_namespace}" \
      --workload-kind Deployment \
      --workload-name checkout \
      --container checkout \
      --service-name "${service_name}"
  )
  python3 "${APPLICATION_VALIDATOR}" "${application_output}"
  python3 "${CONFIG_VALIDATOR}" \
    --collector "${collector_bundle}" \
    --application "${application_output}"
  kubectl kustomize "${application_output}/kubernetes" > "${application_manifest}"
  assert_runtime_safe "${application_manifest}" "${secret_name}"
  kubectl_cmd apply \
    --dry-run=server \
    --validate=strict \
    -f "${application_manifest}" \
    >/dev/null

  assert_manifest_absent "${runtime_manifest}"

  applied_config_name="${release}-collector"
  kubectl_cmd apply -f "${runtime_manifest}"
  YAML_MANIFESTS+=("${runtime_manifest}")

  kubectl_cmd -n "${collector_namespace}" rollout status \
    "deployment/${release}-collector" \
    --timeout "${WAIT_TIMEOUT}"

  applied_config="${case_root}/collector-applied-config.yaml"
  applied_deployment="${case_root}/collector-applied-deployment.yaml"
  kubectl_cmd -n "${collector_namespace}" get \
    "configmap/${applied_config_name}" -o yaml \
    > "${applied_config}"
  kubectl_cmd -n "${collector_namespace}" get \
    "deployment/${release}-collector" -o yaml \
    > "${applied_deployment}"
  assert_runtime_safe "${applied_config}" "${secret_name}"
  assert_runtime_safe "${applied_deployment}" "${secret_name}"
  assert_no_namespace_secrets "${collector_namespace}"

  ready_endpoints="$(kubectl_cmd -n "${collector_namespace}" \
    get endpointslices \
    -l "kubernetes.io/service-name=${collector_service}" \
    -o jsonpath='{range .items[*].endpoints[*]}{.conditions.ready}{"\n"}{end}')"
  if ! printf '%s\n' "${ready_endpoints}" | rg -x 'true' >/dev/null; then
    fail "Collector Service has no ready endpoint: ${collector_service}"
  fi

  assert_manifest_absent "${application_manifest}"
  kubectl_cmd apply -k "${application_output}/kubernetes"
  kubectl_cmd -n "${app_namespace}" rollout status deployment/checkout \
    --timeout "${WAIT_TIMEOUT}"

  application_env="$(kubectl_cmd -n "${app_namespace}" get deployment checkout \
    -o jsonpath='{range .spec.template.spec.containers[?(@.name=="checkout")].env[*]}{.name}={.value}{"\n"}{end}')"
  for expected in \
    "OTEL_SERVICE_NAME=${service_name}" \
    "OTEL_EXPORTER_OTLP_ENDPOINT=${expected_endpoint}" \
    "OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf" \
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${expected_endpoint}/v1/traces" \
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=${expected_endpoint}/v1/metrics"; do
    if ! printf '%s\n' "${application_env}" | rg -x -F "${expected}" >/dev/null; then
      printf '%s\n' "${application_env}" >&2
      fail "application is missing generated environment value: ${expected}"
    fi
  done

  assert_no_namespace_secrets "${app_namespace}"
  wait_for_debug_evidence \
    "${collector_namespace}" \
    "${release}" \
    "${service_name}" \
    "${case_id}" \
    "${logs_file}"

  echo "PASS yaml: ${service_name} sent a trace and metric to ${expected_endpoint}"
}

if ! existing_clusters="$(kind get clusters)"; then
  fail "could not preflight Kind cluster ownership"
fi
if printf '%s\n' "${existing_clusters}" | rg -x -F "${CLUSTER_NAME}" >/dev/null; then
  fail "refuse to replace existing Kind cluster: ${CLUSTER_NAME}"
else
  match_status="$?"
  if [ "${match_status}" -ne 1 ]; then
    fail "could not preflight Kind cluster collision: ${CLUSTER_NAME}"
  fi
fi
echo "Creating disposable Kind cluster ${CLUSTER_NAME}"
kind create cluster \
  --name "${CLUSTER_NAME}" \
  --image "${KIND_NODE_IMAGE}" \
  --kubeconfig "${KUBECONFIG_PATH}" \
  --wait "${WAIT_TIMEOUT}"
CLUSTER_CREATED=true
CLUSTER_AVAILABLE=true
server="$(kubectl_cmd config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
case "${server}" in
  https://127.0.0.1:* | https://localhost:*)
    ;;
  *)
    fail "refuse to use non-loopback Kubernetes API endpoint: ${server}"
    ;;
esac
kubectl_cmd wait --for=condition=Ready nodes --all --timeout "${WAIT_TIMEOUT}"

run_case

echo "PASS: generated Kubernetes YAML deployment path accepted unique traces and metrics"
echo "No Kubernetes Secret was created and no cloud endpoint was applied."
echo "Temporary cluster and files will now be removed."
