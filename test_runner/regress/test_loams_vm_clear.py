"""
Loams Postgres (LP-0016, NF1 Task 17): visibility-map clears on heap changes,
read back through the pageserver and a replica.

Upstream Postgres 17.11 ("Fix VM clear WAL logging by registering VM blocks",
c0d9864f) registers the visibility-map page in heap WAL records that clear VM
bits, because the WAL summarizer (incremental backups) and full-page images
only see registered blocks. Loams Postgres keeps the fork's heap record format
without that block reference (owner, 2026-10-17; docs/loams/pg17-vm-clear.md):
the pageserver derives the VM clear from the record's *_ALL_VISIBLE_CLEARED /
XLH_LOCK_ALL_FROZEN_CLEARED flags and stores it on the VM page itself, and a
compute WAL-logs every VM page it evicts.

This test is the upstream bug's scenario on Neon's storage model: VM bits set
by VACUUM FREEZE, then cleared by an insert, a multi-insert (COPY), a delete,
an update and a row lock. Each clear must be visible
  - on a branch created at the LSN right after the changes (pages
    reconstructed by the pageserver from WAL, with the primary's buffers large
    enough that no VM page was evicted and logged as a full page first);
  - on the primary after its buffers are cleared;
  - on a hot-standby replica;
and, as a guard on the record format, no heap change record of these tables
registers a visibility-map block (the merge of 17.11 must not bring upstream's
extra block reference into the fork's records).
"""

from __future__ import annotations

from io import StringIO

import pytest
from fixtures.log_helper import log
from fixtures.neon_fixtures import NeonEnv, fork_at_current_lsn, wait_replica_caughtup
from fixtures.pg_version import PgVersion

TABLES = ("vm_insert", "vm_copy", "vm_delete", "vm_update", "vm_lock")
# pg_visibility_map(rel, 0) after the change: (all_visible, all_frozen)
EXPECTED = {
    "vm_insert": (False, False),
    "vm_copy": (False, False),
    "vm_delete": (False, False),
    "vm_update": (False, False),
    # A row lock clears only all-frozen (XLH_LOCK_ALL_FROZEN_CLEARED).
    "vm_lock": (True, False),
}


def vm_bits(cur, table: str) -> tuple[bool, bool]:
    cur.execute(f"SELECT all_visible, all_frozen FROM pg_visibility_map('{table}', 0)")
    row = cur.fetchone()
    assert row is not None
    return (bool(row[0]), bool(row[1]))


def check_cleared(cur, where: str):
    for t in TABLES:
        got = vm_bits(cur, t)
        log.info(f"{where}: {t} page 0 VM bits {got}")
        assert got == EXPECTED[t], f"{where}: {t} page 0 has VM bits {got}, expected {EXPECTED[t]}"
    # An index-only scan must not return the deleted row.
    cur.execute("SET enable_seqscan = off; SET enable_bitmapscan = off; SET enable_indexscan = on")
    cur.execute("SELECT id FROM vm_delete WHERE id = 1")
    assert cur.fetchall() == [], f"{where}: index-only scan returned a deleted row"


def test_loams_vm_clear_without_vm_block_reference(neon_simple_env: NeonEnv):
    env = neon_simple_env
    if env.pg_version < PgVersion.V16:
        pytest.skip("pg_get_wal_block_info needs Postgres 16")
    primary = env.endpoints.create_start(
        "main",
        config_lines=[
            # No VM page is evicted (and logged as a full page) before the branch point.
            "shared_buffers = 128MB",
            # pg_walinspect names the fork's custom resource manager.
            "shared_preload_libraries = 'neon,neon_rmgr'",
        ],
    )
    conn = primary.connect()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION neon_test_utils")
    cur.execute("CREATE EXTENSION pg_visibility")
    cur.execute("CREATE EXTENSION pg_walinspect")

    for t in TABLES:
        cur.execute(f"CREATE TABLE {t} (id integer PRIMARY KEY, v text)")
        cur.execute(f"INSERT INTO {t} SELECT g, 'x' FROM generate_series(1, 10) g")
        cur.execute(f"VACUUM (FREEZE, ANALYZE) {t}")
        assert vm_bits(cur, t) == (True, True), f"VACUUM FREEZE did not set the VM bits of {t}"

    replica = env.endpoints.new_replica_start(origin=primary, endpoint_id="vm_replica")

    cur.execute("SELECT pg_current_wal_insert_lsn()")
    start_lsn = cur.fetchone()[0]

    cur.execute("INSERT INTO vm_insert VALUES (100, 'y')")
    cur.copy_expert("COPY vm_copy FROM STDIN", StringIO("".join(f"{i}\ty\n" for i in range(100, 120))))
    cur.execute("DELETE FROM vm_delete WHERE id = 1")
    cur.execute("UPDATE vm_update SET v = 'y' WHERE id = 1")
    cur.execute("BEGIN")
    cur.execute("SELECT id FROM vm_lock WHERE id = 1 FOR UPDATE")
    cur.execute("COMMIT")

    cur.execute("SELECT pg_current_wal_insert_lsn()")
    end_lsn = cur.fetchone()[0]

    # The record format: no heap change record of these tables also registers
    # a visibility-map block (fork 2). VISIBLE records register the VM page as
    # block 0, so they are not counted.
    cur.execute(
        """
        WITH b AS (SELECT * FROM pg_get_wal_block_info(%s, %s)),
             tables AS (SELECT pg_relation_filenode(c::regclass) AS filenode FROM unnest(%s::text[]) c),
             heap_changes AS (
                 SELECT start_lsn FROM b
                 WHERE block_id = 0 AND relforknumber = 0
                   AND relfilenode IN (SELECT filenode FROM tables))
        SELECT b.start_lsn, b.resource_manager, b.record_type FROM b
        WHERE b.relforknumber = 2 AND b.start_lsn IN (SELECT start_lsn FROM heap_changes)
        """,
        (start_lsn, end_lsn, list(TABLES)),
    )
    with_vm = cur.fetchall()
    assert with_vm == [], f"heap records register a visibility-map block: {with_vm}"

    # 1. The pageserver: a branch at the LSN right after the changes.
    fork_at_current_lsn(env, primary, "vm_clear_branch", "main")
    branch = env.endpoints.create_start("vm_clear_branch")
    with branch.cursor() as bcur:
        check_cleared(bcur, "branch")

    # 2. The primary, its buffers cleared (VM pages re-read from the pageserver).
    primary.clear_buffers(cursor=cur)
    check_cleared(cur, "primary after clear_buffers")

    # 3. A hot-standby replica.
    wait_replica_caughtup(primary, replica)
    with replica.cursor() as rcur:
        check_cleared(rcur, "replica")
