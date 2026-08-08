#!/usr/bin/env bash
# Deploy origin/main only after the exact SHA has a successful GitHub Actions CI run.
set -Eeuo pipefail

readonly REPO_URL="${OPENSHARE_REPO_URL:-https://github.com/MinionEnjoyer/OpenShare.git}"
readonly GITHUB_REPOSITORY="${OPENSHARE_GITHUB_REPOSITORY:-MinionEnjoyer/OpenShare}"
readonly BRANCH="${OPENSHARE_BRANCH:-main}"
readonly WORKFLOW_NAME="${OPENSHARE_WORKFLOW_NAME:-CI}"
readonly DEPLOY_ROOT="${OPENSHARE_DEPLOY_ROOT:-/opt/openshare-deployer}"
readonly MIRROR_DIR="${OPENSHARE_MIRROR_DIR:-${DEPLOY_ROOT}/repo.git}"
readonly RELEASES_DIR="${OPENSHARE_RELEASES_DIR:-/opt/openshare-releases}"
readonly CONFIG_DIR="${OPENSHARE_CONFIG_DIR:-/etc/openshare}"
readonly CURRENT_LINK="${OPENSHARE_CURRENT_LINK:-${RELEASES_DIR}/current}"
readonly STATE_FILE="${OPENSHARE_STATE_FILE:-${DEPLOY_ROOT}/deployed-sha}"
readonly LOCK_FILE="${OPENSHARE_LOCK_FILE:-/run/openshare-autodeploy.lock}"
readonly COMPOSE_PROJECT="${OPENSHARE_COMPOSE_PROJECT:-openshare}"
readonly CONTAINER_NAME="${OPENSHARE_CONTAINER_NAME:-openshare}"
readonly HEALTH_URL="${OPENSHARE_HEALTH_URL:-http://127.0.0.1:8800/health}"
readonly HEALTH_ATTEMPTS="${OPENSHARE_HEALTH_ATTEMPTS:-36}"
readonly HEALTH_INTERVAL="${OPENSHARE_HEALTH_INTERVAL:-5}"

CHECK_ONLY=false
EXPECTED_VERSION=""
if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--check]" >&2
  exit 2
fi

log() {
  printf 'openshare-autodeploy: %s\n' "$*"
}

valid_sha() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]]
}

require_commands() {
  local command_name
  for command_name in curl docker flock git jq; do
    command -v "$command_name" >/dev/null 2>&1 || {
      log "missing required command: ${command_name}"
      return 1
    }
  done
}

current_sha() {
  local sha=""
  if [[ -d "$CURRENT_LINK" ]]; then
    sha="$(git -C "$CURRENT_LINK" rev-parse HEAD 2>/dev/null || true)"
  fi
  if ! valid_sha "$sha" && [[ -r "$STATE_FILE" ]]; then
    sha="$(tr -d '[:space:]' < "$STATE_FILE")"
  fi
  valid_sha "$sha" && printf '%s\n' "$sha"
}

resolve_candidate() {
  local sha
  sha="$(git ls-remote --exit-code "$REPO_URL" "refs/heads/${BRANCH}" | awk 'NR == 1 { print $1 }')"
  valid_sha "$sha" || {
    log "could not resolve a full SHA for ${BRANCH}"
    return 1
  }
  printf '%s\n' "$sha"
}

ci_result() {
  local sha="$1"
  local response result
  response="$(curl --fail --silent --show-error \
    --connect-timeout 10 --max-time 30 --retry 2 \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/runs?head_sha=${sha}&event=push&per_page=50")" || {
      log "GitHub Actions lookup failed for ${sha}"
      return 1
    }

  result="$(jq -er --arg workflow "$WORKFLOW_NAME" --arg sha "$sha" '
    [.workflow_runs[]
      | select(.name == $workflow and .head_sha == $sha and .event == "push")]
    | sort_by(.created_at, .run_attempt)
    | last
    | if . == null then "missing"
      elif .status != "completed" then "pending"
      elif .conclusion == "success" then "success"
      else (.conclusion // "failed")
      end
  ' <<<"$response")" || {
    log "GitHub Actions response was invalid for ${sha}"
    return 1
  }
  printf '%s\n' "$result"
}

refresh_mirror() {
  if [[ ! -d "$MIRROR_DIR" ]]; then
    git clone --mirror "$REPO_URL" "$MIRROR_DIR"
  else
    git --git-dir="$MIRROR_DIR" remote set-url origin "$REPO_URL"
    git --git-dir="$MIRROR_DIR" fetch --quiet --prune origin \
      "+refs/heads/${BRANCH}:refs/heads/${BRANCH}"
  fi
}

prepare_release() {
  local sha="$1"
  local short_sha="${sha:0:12}"
  local release_dir="${RELEASES_DIR}/${short_sha}"
  local stage_dir="${RELEASES_DIR}/.${short_sha}.stage.$$"

  if [[ -d "$release_dir" ]]; then
    [[ "$(git -C "$release_dir" rev-parse HEAD 2>/dev/null || true)" == "$sha" ]] || {
      log "existing release path ${release_dir} does not match ${sha}"
      return 1
    }
  else
    git --git-dir="$MIRROR_DIR" cat-file -e "${sha}^{commit}"
    git clone --quiet --shared --no-checkout "$MIRROR_DIR" "$stage_dir"
    if ! git -C "$stage_dir" checkout --quiet --detach "$sha"; then
      git --git-dir="$MIRROR_DIR" worktree prune >/dev/null 2>&1 || true
      rm -rf -- "$stage_dir"
      return 1
    fi
    [[ "$(git -C "$stage_dir" rev-parse HEAD)" == "$sha" ]] || {
      rm -rf -- "$stage_dir"
      return 1
    }
    mv -- "$stage_dir" "$release_dir"
  fi

  install -m 0640 "$CONFIG_DIR/.env" "$release_dir/.env"
  printf '%s\n' "$release_dir"
}

config_value() {
  local name="$1" file="$2"
  awk -F= -v name="$name" '$1 == name { sub(/^[^=]*=/, ""); value=$0 } END { print value }' "$file"
}

validate_persistent_paths() {
  local release_dir="$1"
  local database_path storage_path
  database_path="$(config_value DB_PATH "$release_dir/.env")"
  storage_path="$(config_value STORAGE_PATH "$release_dir/.env")"
  [[ "$database_path" == /* && "$storage_path" == /* ]] || {
    log "DB_PATH and STORAGE_PATH must be absolute host paths for immutable releases"
    return 1
  }
}

compose_up() {
  local release_dir="$1"
  docker compose --project-name "$COMPOSE_PROJECT" \
    --project-directory "$release_dir" \
    --env-file "$release_dir/.env" \
    -f "$release_dir/docker-compose.yml" up -d --build
}

container_ready() {
  [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || true)" == "true" ]]
}

endpoint_ready() {
  local health
  health="$(curl --fail --silent --show-error --max-time 10 "$HEALTH_URL" 2>/dev/null || true)"
  jq -e --arg version "$EXPECTED_VERSION" \
    '.status == "ok" and .version == $version' <<<"$health" >/dev/null
}

wait_until_ready() {
  local attempt
  for ((attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt += 1)); do
    if container_ready && endpoint_ready; then
      return 0
    fi
    sleep "$HEALTH_INTERVAL"
  done
  return 1
}

record_release() {
  local sha="$1" release_dir="$2"
  local next_link="${CURRENT_LINK}.next.$$"
  local next_state="${STATE_FILE}.next.$$"
  printf '%s\n' "$sha" > "$next_state"
  chmod 0640 "$next_state"
  mv -f -- "$next_state" "$STATE_FILE"
  ln -s "$release_dir" "$next_link"
  mv -Tf -- "$next_link" "$CURRENT_LINK"
}

verify_pointer_writable() {
  local release_dir="$1"
  local probe_link="${CURRENT_LINK}.probe.$$"
  if ! ln -s "$release_dir" "$probe_link"; then
    return 1
  fi
  rm -f -- "$probe_link"
}

main() {
  [[ "$(id -u)" -eq 0 ]] || {
    log "must run as root"
    exit 1
  }
  require_commands
  mkdir -p "$DEPLOY_ROOT" "$RELEASES_DIR"
  if [[ -n "${DOCKER_CONFIG:-}" ]]; then
    mkdir -p "$DOCKER_CONFIG"
    chmod 0700 "$DOCKER_CONFIG"
  fi
  [[ -r "$CONFIG_DIR/.env" ]] || {
    log "protected runtime config is missing from ${CONFIG_DIR}"
    exit 1
  }

  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    log "another deployment is already running; skipping"
    exit 0
  fi

  local candidate deployed result previous_dir release_dir previous_version
  candidate="$(resolve_candidate)"
  deployed="$(current_sha || true)"
  result="$(ci_result "$candidate")"
  log "candidate=${candidate} deployed=${deployed:-none} ci=${result}"

  if [[ "$result" != "success" ]]; then
    log "deployment skipped because CI is ${result}"
    exit 0
  fi
  if [[ "$candidate" == "$deployed" ]]; then
    log "deployment skipped because ${candidate} is already active"
    exit 0
  fi
  if $CHECK_ONLY; then
    log "check-only: ${candidate} would be deployed"
    exit 0
  fi

  previous_dir="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
  refresh_mirror
  release_dir="$(prepare_release "$candidate")"
  validate_persistent_paths "$release_dir"
  EXPECTED_VERSION="$(tr -d '[:space:]' < "$release_dir/VERSION")"
  [[ -n "$EXPECTED_VERSION" ]] || {
    log "release VERSION is empty"
    exit 1
  }
  verify_pointer_writable "$release_dir" || {
    log "cannot atomically update ${CURRENT_LINK}; refusing to change containers"
    exit 1
  }

  if ! compose_up "$release_dir" || ! wait_until_ready || ! record_release "$candidate" "$release_dir"; then
    log "deployment of ${candidate} failed; active pointer remains unchanged"
    if [[ -n "$previous_dir" && -f "$previous_dir/docker-compose.yml" ]]; then
      previous_version="$(tr -d '[:space:]' < "$previous_dir/VERSION" 2>/dev/null || true)"
      EXPECTED_VERSION="$previous_version"
      log "attempting application rollback to ${previous_dir}"
      compose_up "$previous_dir" || log "application rollback command failed"
      [[ -n "$EXPECTED_VERSION" ]] && wait_until_ready || log "application rollback health check failed"
    fi
    exit 1
  fi

  log "deployed=${candidate} release=${release_dir} version=${EXPECTED_VERSION} health=ok"
}

main "$@"
