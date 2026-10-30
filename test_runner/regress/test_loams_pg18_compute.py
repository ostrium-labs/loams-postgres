"""
Loams Postgres at 18 (NF2 Tasks 3 and 6; LP-0043, LP-0044): the compute side.

read_stream_seqscan_pg18
    A sequential scan through 18's read stream returns the right checksum
    after the compute's caches are gone, and records Neon's prefetch hit rate.
    At 18 reads go through the read stream and AIO; the neon smgr has no file
    descriptors, so they complete synchronously (LP-0044, D1110) and rely on
    the read stream's advice reaching neon_prefetch(). The size defaults to
    1 GB in the gate; LOAMS_SEQSCAN_GB=10 runs the design's 10 GB.

slot_invalidation_survives_restart_pg18
    18's idle_replication_slot_timeout invalidates a logical slot at a
    checkpoint. Neon WAL-logs replication slots, so the pageserver keeps the
    slot's state; the invalidation must survive a compute restart, which
    rebuilds pg_replslot from the pageserver.
"""

from __future__ import annotations

import os
import time

import pytest
from fixtures.log_helper import log
from fixtures.neon_fixtures import NeonEnv
from fixtures.utils import query_scalar

pytestmark = pytest.mark.skipif(
    int(os.getenv("DEFAULT_PG_VERSION", "17")) < 18,
    reason="Postgres 18's read stream and idle_replication_slot_timeout",
)

ROW_BYTES = 1000


def test_read_stream_seqscan_pg18(neon_simple_env: NeonEnv):
    env = neon_simple_env
    gb = float(os.getenv("LOAMS_SEQSCAN_GB", "1"))
    rows = int(gb * 1024 * 1024 * 1024 / ROW_BYTES)
    endpoint = env.endpoints.create_start(
        "main",
        config_lines=[
            "shared_buffers=128MB",
            "neon.file_cache_size_limit=0",
            "effective_io_concurrency=64",
        ],
    )
    with endpoint.cursor() as cur:
        assert query_scalar(cur, "SHOW io_method") == "sync", "compute_ctl sets io_method (D1110)"
        cur.execute("CREATE TABLE seq (id bigint, pad text) WITH (fillfactor = 100)")
        cur.execute(
            f"INSERT INTO seq SELECT g, repeat('x', {ROW_BYTES - 40}) FROM generate_series(1, {rows}) g"
        )
        expected = query_scalar(cur, "SELECT sum(id)::text || ':' || count(*) FROM seq")

    # The pages now come only from the pageserver.
    endpoint.stop()
    endpoint.start()
    with endpoint.cursor() as cur:
        cur.execute("SET max_parallel_workers_per_gather = 0")
        cur.execute(
            "EXPLAIN (ANALYZE, BUFFERS, PREFETCH, FORMAT JSON) "
            "SELECT sum(id)::text || ':' || count(*) FROM seq"
        )
        row = cur.fetchone()
        assert row is not None
        plan = row[0][0]["Plan"]
        node = plan
        while node.get("Node Type") != "Seq Scan" and node.get("Plans"):
            node = node["Plans"][0]
        hits = int(node.get("Prefetch Hits", 0))
        misses = int(node.get("Prefetch Misses", 0))
        total = max(hits + misses, 1)
        log.info(
            f"read_stream_seqscan_pg18: {gb} GB, prefetch hits {hits}, misses {misses}, "
            f"hit rate {hits / total:.3f}"
        )
        got = query_scalar(cur, "SELECT sum(id)::text || ':' || count(*) FROM seq")
    assert got == expected, f"sequential scan at 18: {got} != {expected}"


def test_slot_invalidation_survives_restart_pg18(neon_simple_env: NeonEnv):
    env = neon_simple_env
    endpoint = env.endpoints.create_start(
        "main",
        config_lines=["wal_level=logical", "idle_replication_slot_timeout=1"],
    )

    def slot_state(cur) -> tuple[str | None, str | None]:
        cur.execute(
            "SELECT invalidation_reason, wal_status FROM pg_replication_slots WHERE slot_name = 'idle'"
        )
        row = cur.fetchone()
        assert row is not None, "the slot is gone"
        return row[0], row[1]

    with endpoint.cursor() as cur:
        cur.execute("SELECT pg_create_logical_replication_slot('idle', 'pgoutput')")
        cur.execute("CREATE TABLE t (id int)")
        reason = None
        # The timeout is in seconds; a checkpoint invalidates an idle slot.
        for _ in range(30):
            time.sleep(2)
            cur.execute("INSERT INTO t VALUES (1)")
            cur.execute("CHECKPOINT")
            reason, _ = slot_state(cur)
            if reason is not None:
                break
        assert reason == "idle_timeout", f"slot not invalidated: {reason}"

    endpoint.stop()
    endpoint.start()
    with endpoint.cursor() as cur:
        reason, wal_status = slot_state(cur)
        log.info(f"after restart: invalidation_reason={reason}, wal_status={wal_status}")
        assert reason == "idle_timeout", f"the invalidation did not survive a restart: {reason}"
        assert wal_status == "lost"
