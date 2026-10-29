#!/usr/bin/env bash
# Runs scripts/loams/gate.sh inside the build-tools image $BUILD_TOOLS, on a
# GitHub-hosted runner (LP-0015, NF1 Task 16; loams-gate.yml).
#
#   gate-docker.sh <gate.sh arguments>
#
# The image's user is nonroot (uid 1000), and Postgres refuses to run as root,
# so the checkout is handed to uid 1000 for the run and back to the runner's
# user afterwards (the checkout's cleanup and the cache steps run as the
# runner). The cargo registry and ~/.cache (poetry, pip) live under
# $RUNNER_TEMP/home, which the workflow caches.
#
# --security-opt seccomp=unconfined: Docker's default profile refuses
# io_uring, which the pageserver's tokio-epoll-uring engine needs (G1, G2).
# --ulimit memlock: io_uring's rings count as locked memory on older kernels.
set -euo pipefail
: "${BUILD_TOOLS:?set BUILD_TOOLS to the build-tools image}"
ws=${GITHUB_WORKSPACE:-$PWD}
home=${RUNNER_TEMP:?}/home
mkdir -p "$home/cargo/registry" "$home/cargo/git" "$home/cache"

me="$(id -u):$(id -g)"
restore() { sudo chown -R "$me" "$ws" "$home"; }
trap restore EXIT
sudo chown -R 1000:1000 "$ws" "$home"

for i in 1 2 3; do docker pull -q "$BUILD_TOOLS" && break; [ "$i" -lt 3 ] || exit 1; sleep $((i * 15)); done
docker run --rm --init --shm-size=512mb --ulimit memlock=67108864:67108864 \
  --security-opt seccomp=unconfined \
  -e CI=true -e GITHUB_ACTIONS=true -e "GIT_VERSION=${GITHUB_SHA:-}" -e CARGO_TERM_COLOR=always \
  -v "$ws:/w" -w /w \
  -v "$home/cargo/registry:/home/nonroot/.cargo/registry" \
  -v "$home/cargo/git:/home/nonroot/.cargo/git" \
  -v "$home/cache:/home/nonroot/.cache" \
  "$BUILD_TOOLS" scripts/loams/gate.sh "$@"
