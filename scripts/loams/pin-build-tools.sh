#!/usr/bin/env bash
# Moves the storage Dockerfile's build-tools pin (LP-0009): rewrites the line
# `ARG BUILD_TOOLS=<image>@sha256:<digest>` and nothing else. The image must be
# an ostrium-labs image on ghcr.io pinned by a full digest; anything else is
# refused and the file is left unchanged. Used by .github/workflows/loams-build-tools.yml.
#
# Usage: pin-build-tools.sh <ghcr.io/ostrium-labs/...@sha256:<64 hex>> [Dockerfile ...]
#        (default: the repository's Dockerfile)
# Test: scripts/loams/tests/test_hygiene.sh (build_tools_pinned_by_digest).
set -euo pipefail
ref=${1:?usage: pin-build-tools.sh <image@sha256:digest> [Dockerfile ...]}
shift
if ! [[ $ref =~ ^ghcr\.io/ostrium-labs/[a-z0-9/_-]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "pin-build-tools: refused: $ref is not ghcr.io/ostrium-labs/<image>@sha256:<64 hex>" >&2
  exit 2
fi
(($#)) || set -- "$(git rev-parse --show-toplevel)/Dockerfile"
for file in "$@"; do
  n=$(grep -c '^ARG BUILD_TOOLS=' "$file" || true)
  if [[ $n != 1 ]]; then
    echo "pin-build-tools: $file has $n ARG BUILD_TOOLS lines, expected 1" >&2
    exit 1
  fi
  sed -i "s|^ARG BUILD_TOOLS=.*\$|ARG BUILD_TOOLS=$ref|" "$file"
  echo "pin-build-tools: $file -> $ref"
done
