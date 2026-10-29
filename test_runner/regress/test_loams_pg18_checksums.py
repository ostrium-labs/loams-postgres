"""
Loams Postgres (LP-0041, NF2 Task 5, D1111): data checksums at Postgres 18.

18's initdb turns data checksums on by default. Nothing in Loams Postgres sets
page checksums (WAL redo, image layers and basebackup all serve pages whose
checksum field is stale), so a timeline bootstrapped with them on would fail
verification on the first page the compute reads back. The pageserver
bootstraps 18 timelines with `initdb --no-data-checksums`, and the import
paths refuse a data directory with checksums on (`import_checksums_enabled`).

This test runs pgbench on an 18 timeline, then reads the same data back:
  - after the compute restarts (pages come from the pageserver, not from the
    compute's buffers);
  - after the pageserver restarts too (pages come from layer files);
  - on a branch at the last LSN (pages reconstructed for a new timeline).
Every time, data checksums are off and the tables' contents are unchanged.

Runs only at 18. It needs vendor/postgres-v18 (NF2 Task 2) in the fork's
build, so it runs in CI's 18 leg once that lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fixtures.common_types import Lsn
from fixtures.log_helper import log
from fixtures.pg_version import PgVersion
from fixtures.utils import query_scalar, run_only_on_postgres

if TYPE_CHECKING:
    from fixtures.neon_fixtures import Endpoint, NeonEnv, PgBin

# Each table's row count and a digest of its contents, in key order.
DIGESTS = {
    "pgbench_accounts": "SELECT count(*), md5(string_agg(aid || ':' || bid || ':' || abalance, ',' ORDER BY aid)) FROM pgbench_accounts",
    "pgbench_branches": "SELECT count(*), md5(string_agg(bid || ':' || bbalance, ',' ORDER BY bid)) FROM pgbench_branches",
    "pgbench_tellers": "SELECT count(*), md5(string_agg(tid || ':' || tbalance, ',' ORDER BY tid)) FROM pgbench_tellers",
    "pgbench_history": "SELECT count(*), md5(string_agg(tid || ':' || bid || ':' || aid || ':' || delta, ',' ORDER BY tid, bid, aid, delta, mtime)) FROM pgbench_history",
}


def snapshot(endpoint: Endpoint, where: str) -> dict[str, tuple[int, str]]:
    with endpoint.cursor() as cur:
        assert query_scalar(cur, "SHOW data_checksums") == "off", f"{where}: data checksums on"
        assert query_scalar(cur, "SELECT data_page_checksum_version FROM pg_control_init()") == 0, (
            f"{where}: the control file has a checksum version"
        )
        out: dict[str, tuple[int, str]] = {}
        for table, sql in DIGESTS.items():
            cur.execute(sql)
            row = cur.fetchone()
            assert row is not None
            out[table] = (int(row[0]), str(row[1]))
        # The digests read every page of the pgbench tables; read the
        # largest catalogs too. With checksums on, a stale checksum on any
        # of these pages would fail the query.
        for catalog in ("pg_class", "pg_attribute", "pg_proc", "pg_depend"):
            cur.execute(f"SELECT count(*) FROM {catalog}")
        log.info(f"{where}: {out}")
        return out


@run_only_on_postgres([PgVersion.V18], "data checksums are on by default only from 18")
def test_pgbench_checksums_survive_restart_and_branch_pg18(neon_simple_env: NeonEnv, pg_bin: PgBin):
    env = neon_simple_env
    endpoint = env.endpoints.create_start("main")

    pg_bin.run_capture(["pgbench", "-i", "-s", "4", endpoint.connstr()])
    pg_bin.run_capture(["pgbench", "-c", "4", "-j", "2", "-t", "500", endpoint.connstr()])
    before = snapshot(endpoint, "after pgbench")
    assert before["pgbench_accounts"][0] == 400_000
    assert before["pgbench_history"][0] == 2_000

    with endpoint.cursor() as cur:
        lsn = Lsn(query_scalar(cur, "SELECT pg_current_wal_flush_lsn()"))

    # The compute restarts: every page comes back from the pageserver.
    endpoint.stop()
    endpoint.start()
    assert snapshot(endpoint, "after a compute restart") == before

    # The pageserver restarts too: pages come from its layer files.
    endpoint.stop()
    env.pageserver.restart()
    endpoint.start()
    assert snapshot(endpoint, "after a pageserver restart") == before

    # A branch at the last LSN: pages reconstructed for a new timeline.
    env.create_branch("pg18_checksums_branch", ancestor_branch_name="main", ancestor_start_lsn=lsn)
    branch = env.endpoints.create_start("pg18_checksums_branch")
    assert snapshot(branch, "on a branch") == before

    # The branch takes writes, and they survive its restart.
    pg_bin.run_capture(["pgbench", "-c", "2", "-t", "200", branch.connstr()])
    after_branch_writes = snapshot(branch, "after writes on the branch")
    branch.stop()
    branch.start()
    assert snapshot(branch, "after the branch restarts") == after_branch_writes
