#!/usr/bin/env bash

set -euo pipefail

API_BASE="${API_BASE:-http://localhost:52415}"
MODEL_ID="mlx-community/MiniMax-M2.5-6bit"
SHARDING="${1:-Pipeline}"
INSTANCE_META="MlxRing"
LOCAL_MLX_MAX_GB="${LOCAL_MLX_MAX_GB:-110}"
REMOTE_MLX_MAX_GB="${REMOTE_MLX_MAX_GB:-122}"
LOCAL_IOGPU_WIRED_LIMIT_MB="${LOCAL_IOGPU_WIRED_LIMIT_MB:-112640}"
REMOTE_IOGPU_WIRED_LIMIT_MB="${REMOTE_IOGPU_WIRED_LIMIT_MB:-124928}"
APPLY_LOCAL_LIMITS="${APPLY_LOCAL_LIMITS:-1}"
APPLY_REMOTE_LIMITS="${APPLY_REMOTE_LIMITS:-0}"
REMOTE_HOST="${REMOTE_HOST:-}"
REMOTE_USER="${REMOTE_USER:-}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need_cmd curl
need_cmd jq

apply_memory_limits() {
  export MLX_MAX_AGGREGATE_SIZE_GB="${LOCAL_MLX_MAX_GB}"

  if [[ "${APPLY_LOCAL_LIMITS}" == "1" ]]; then
    echo "Applying local iogpu wired memory limit (${LOCAL_IOGPU_WIRED_LIMIT_MB} MB)..."
    if [[ "$(id -u)" -eq 0 ]]; then
      sysctl "iogpu.wired_limit_mb=${LOCAL_IOGPU_WIRED_LIMIT_MB}" >/dev/null
    else
      sudo sysctl "iogpu.wired_limit_mb=${LOCAL_IOGPU_WIRED_LIMIT_MB}" >/dev/null
    fi
  fi

  echo "Local role: endpoint/communications node with dev headroom reserved."
  echo "Local memory target: ${LOCAL_MLX_MAX_GB}/128 GB (MLX_MAX_AGGREGATE_SIZE_GB)."

  if [[ "${APPLY_REMOTE_LIMITS}" == "1" ]]; then
    need_cmd ssh
    if [[ -z "${REMOTE_HOST}" ]]; then
      echo "APPLY_REMOTE_LIMITS=1 requires REMOTE_HOST to be set." >&2
      exit 1
    fi
    remote_target="${REMOTE_HOST}"
    if [[ -n "${REMOTE_USER}" ]]; then
      remote_target="${REMOTE_USER}@${REMOTE_HOST}"
    fi
    echo "Applying remote iogpu wired memory limit on ${remote_target} (${REMOTE_IOGPU_WIRED_LIMIT_MB} MB)..."
    ssh "${remote_target}" "sudo sysctl iogpu.wired_limit_mb=${REMOTE_IOGPU_WIRED_LIMIT_MB}" >/dev/null
  fi

  echo "Remote main-processor target: ${REMOTE_MLX_MAX_GB}/128 GB."
  echo "Start EXO on remote with: MLX_MAX_AGGREGATE_SIZE_GB=${REMOTE_MLX_MAX_GB} ..."
}

apply_memory_limits

echo "Checking cluster state from ${API_BASE}..."
curl -fsS "${API_BASE}/state" >/dev/null

echo "Stopping any existing ${MODEL_ID} instances before preview..."
instance_ids="$(
  curl -fsS "${API_BASE}/state" |
    jq -r --arg model "${MODEL_ID}" '
      .instances
      | to_entries[]
      | select(.value | tostring | contains($model))
      | .key
    '
)"

if [[ -n "${instance_ids}" ]]; then
  while IFS= read -r instance_id; do
    [[ -z "${instance_id}" ]] && continue
    echo "Deleting instance ${instance_id}..."
    curl -fsS -X DELETE "${API_BASE}/instance/${instance_id}" >/dev/null || true
  done <<< "${instance_ids}"
  sleep 3
fi

echo "Looking up ${MODEL_ID} preview for ${SHARDING} + ${INSTANCE_META}..."
preview_payload="$(
  curl -fsS --get "${API_BASE}/instance/previews" \
    --data-urlencode "model_id=${MODEL_ID}" |
    jq -ce --arg sharding "${SHARDING}" --arg meta "${INSTANCE_META}" '
      [
        .previews[]
        | select(.sharding == $sharding and .instance_meta == $meta and .error == null)
        | {instance: .instance}
      ][0] // error("No valid preview found for \($sharding) + \($meta)")
    '
)"

echo "Creating new ${MODEL_ID} instance..."
create_response="$(
  curl -fsS -X POST "${API_BASE}/instance" \
    -H 'Content-Type: application/json' \
    -d "${preview_payload}"
)"
echo "${create_response}" | jq .

command_id="$(echo "${create_response}" | jq -r '.command_id')"
instance_id=""

echo "Waiting for runners to reach RunnerReady..."
for _ in $(seq 1 180); do
  state_json="$(curl -fsS "${API_BASE}/state")"
  if [[ -z "${instance_id}" ]]; then
    instance_id="$(
      echo "${state_json}" |
        jq -r --arg model "${MODEL_ID}" --arg cmd "${command_id}" '
          .instances
          | to_entries[]
          | select(.value | tostring | contains($model))
          | .key
        ' | tail -n 1
    )"
  fi

  if [[ -z "${instance_id}" ]]; then
    sleep 2
    continue
  fi

  runner_ids="$(
    echo "${state_json}" |
      jq -r --arg iid "${instance_id}" '
        .instances[$iid]
        | .. | objects
        | select(has("nodeToRunner"))
        | .nodeToRunner[]
      '
  )"

  ready_count=0
  failed_messages=""
  while IFS= read -r runner_id; do
    [[ -z "${runner_id}" ]] && continue
    runner_state="$(
      echo "${state_json}" |
        jq -r --arg rid "${runner_id}" '
          .runners[$rid] | keys[0] // "Missing"
        '
    )"
    if [[ "${runner_state}" == "RunnerReady" ]]; then
      ready_count=$((ready_count + 1))
    fi
    if [[ "${runner_state}" == "RunnerFailed" ]]; then
      msg="$(
        echo "${state_json}" |
          jq -r --arg rid "${runner_id}" '
            .runners[$rid].RunnerFailed.errorMessage
          '
      )"
      failed_messages+="${msg}"$'\n'
    fi
  done <<< "${runner_ids}"

  if [[ -n "${failed_messages}" ]]; then
    echo "Runner failure detected:" >&2
    printf '%s' "${failed_messages}" >&2
    exit 1
  fi

  if [[ "${ready_count}" -ge 2 ]]; then
    echo "Cluster is ready for ${MODEL_ID}."
    echo "Instance id: ${instance_id}"
    echo "Command id: ${command_id}"
    exit 0
  fi

  sleep 2
done

echo "Timed out waiting for ${MODEL_ID} runners to become ready." >&2
exit 1
