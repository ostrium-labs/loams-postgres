#!/usr/bin/env bash
# The gate's G1 and G2 (LP-0015, NF1 Task 16; design §51 §6.4), run by
# loams-gate.yml inside the loams-postgres-build-tools image (the toolchain, mold,
# cargo-nextest, Python and poetry), from the repository root:
#
#   gate.sh g1             Postgres for every major the code supports, then
#                          cargo nextest on G1's crates; the pageserver's unit
#                          tests run once per virtual-file I/O engine
#                          (std-fs and tokio-epoll-uring).
#   gate.sh g2-build OUT   a release build (feature testing) of the binaries,
#                          Postgres and Neon's extensions, packed into OUT
#                          (a .tar.zst) for the G2 jobs.
#   gate.sh g2 MAJOR       unpack the build, then Neon's test_runner on
#                          scripts/loams/gate-subset.txt with neon_local, for
#                          one Postgres major.
#   gate.sh upgrade FROM TO   G2's `upgrade` job: Path 1 (fast_import into a
#                          new timeline) from Postgres FROM to TO, with
#                          per-table checksums (design §62 §8, D1115). Its body
#                          lands with NF2 Task 13; until then it fails, so a
#                          pair the gate runs is never reported as a pass.
#
# Nothing here needs a secret or a cloud account: the remote-storage tests that
# need a real S3 or Azure account skip themselves without one, and test_runner
# uses its own mock S3.
set -euo pipefail

tier=${1:?usage: gate.sh g1 | g2-build OUT | g2 MAJOR | upgrade FROM TO}
jobs=$(nproc)

# G1's crates (design §51 §6.4). The features named are the ones the crates
# gate their test-only code behind.
G1_CRATES=(-p postgres_ffi -p wal_decoder -p pageserver_api -p compute_api -p compute_tools -p pageserver)
G1_FEATURES="wal_decoder/testing,pageserver_api/testing,compute_tools/testing,pageserver/testing"

section() { echo "::group::$*"; }
end() { echo "::endgroup::"; }

case "$tier" in
  g1)
    # Postgres and Neon's extensions for every major (the WAL-redo tests start
    # Postgres; postgres_ffi has bindings for each major).
    section "Postgres and Neon's extensions"
    make -s -j"$jobs" neon-pg-ext
    end
    export LD_LIBRARY_PATH="$PWD/pg_install/v17/lib"
    section "Build the tests"
    mold -run cargo nextest run --locked --features "$G1_FEATURES" "${G1_CRATES[@]}" --no-run
    end
    # Everything but the pageserver, once.
    cargo nextest run --locked --features "$G1_FEATURES" "${G1_CRATES[@]}" -E '!package(pageserver)'
    for engine in std-fs tokio-epoll-uring; do
      echo "pageserver unit tests, NEON_PAGESERVER_UNIT_TEST_VIRTUAL_FILE_IOENGINE=$engine"
      NEON_PAGESERVER_UNIT_TEST_VIRTUAL_FILE_IOENGINE=$engine \
        cargo nextest run --locked --features "$G1_FEATURES" "${G1_CRATES[@]}" -E 'package(pageserver)'
    done
    ;;

  g2-build)
    out=${2:?gate.sh g2-build OUT}
    export BUILD_TYPE=release
    section "make all (release, feature testing)"
    mold -run make -s -j"$jobs" all CARGO_BUILD_FLAGS="--locked --features testing"
    end
    section "Pack"
    # The binaries test_runner starts (NEON_BIN), Postgres per major
    # (POSTGRES_DISTRIB_DIR), and pg_regress and the isolation tester, which
    # test_pg_regress runs from the build tree.
    mkdir -p gate-bin
    cargo metadata --locked --format-version 1 --no-deps |
      python3 -c 'import json,sys; print("\n".join(t["name"] for p in json.load(sys.stdin)["packages"] for t in p["targets"] if "bin" in t["kind"]))' |
      while read -r bin; do
        if [ -f "target/release/$bin" ]; then cp "target/release/$bin" gate-bin/; fi
      done
    tar -c --zstd -f "$out" gate-bin pg_install/v* \
      build/*/src/test/regress/*.so build/*/src/test/regress/pg_regress \
      build/*/src/test/isolation/isolationtester build/*/src/test/isolation/pg_isolation_regress
    ls -lh "$out"
    end
    ;;

  g2)
    major=${2:?gate.sh g2 MAJOR}
    [[ $major =~ ^[0-9]+$ ]] || { echo "MAJOR must be a number, not $major"; exit 2; }
    [ -d "pg_install/v$major" ] || { echo "no pg_install/v$major: unpack the g2-build artifact first"; exit 2; }
    section "Python dependencies"
    ./scripts/pysync
    end
    mapfile -t args < <(python3 scripts/loams/gate.py subset-args)
    export BUILD_TYPE=release DEFAULT_PG_VERSION=$major
    export NEON_BIN="$PWD/gate-bin" POSTGRES_DISTRIB_DIR="$PWD/pg_install"
    export LD_LIBRARY_PATH="$POSTGRES_DISTRIB_DIR/v$major/lib"
    export TEST_OUTPUT="$PWD/test_output" PAGESERVER_VIRTUAL_FILE_IO_ENGINE=tokio-epoll-uring
    # Two workers: a hosted runner has 4 vCPUs, and test_pg_regress starts four
    # pageservers when sharded. loadgroup keeps tests that share a group together.
    ./scripts/pytest -n 2 --dist=loadgroup --tb=short -rA "${args[@]}"
    ;;

  upgrade)
    from=${2:?gate.sh upgrade FROM TO}
    to=${3:?gate.sh upgrade FROM TO}
    [[ $from =~ ^[0-9]+$ && $to =~ ^[0-9]+$ ]] || { echo "FROM and TO must be numbers, not $from and $to"; exit 2; }
    echo "::error title=g2-upgrade::Path 1 from Postgres $from to $to is not implemented yet (NF2 Task 13): not run, not passed"
    exit 1
    ;;

  *)
    echo "unknown tier $tier (g1, g2-build, g2, upgrade)"
    exit 2
    ;;
esac
