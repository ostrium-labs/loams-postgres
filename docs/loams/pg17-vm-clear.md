# Postgres 17.11's VM-clear fix in Loams Postgres

Postgres 17.11 adds upstream commit `c0d9864f`, "Fix VM clear WAL logging by registering VM blocks". It makes heap WAL records that clear visibility-map (VM) bits register the VM page as an extra block reference. The companion commit `7edec8b5` adds names for those block references.

**Owner ruling (2026-10-17), option (a):** Loams Postgres keeps the fork's heap WAL record format unchanged. It does not take the extra block reference.

This page records why the upstream bug cannot occur in Neon's storage model, how the merge must be resolved, and the test that holds it (LP-0016, NF1 Task 17). Line numbers are at `main` `25a8c11c`.

## The upstream bug

Heap records that clear VM bits (insert, delete, update, lock) did not register the VM page. That broke two things:

1. **Incremental backups.** The WAL summarizer records only registered blocks, so an incremental backup taken across such operations left out the changed VM pages. A restore then kept stale all-visible or all-frozen bits. The effects are wrong index-only scan results, and a wrong `relfrozenxid` advance when vacuum skips pages.
2. **No full-page image of a VM page when bits are cleared.** A torn VM page on local disk could go undetected when checksums are off.

## Why neither can happen in Neon's storage model

The fork writes heap inserts, deletes, updates, multi-inserts and locks as its own `RM_NEON_ID` records (`vendor/postgres-v17/src/backend/access/heap/heapam.c`; at `loams/REL_17_STABLE` they are the `XLogInsert(RM_NEON_ID, …)` calls at lines 2216, 2633, 3143, 3903, 5242, 6317 and 9179). Each record carries the `XLH_*_ALL_VISIBLE_CLEARED` and `XLH_LOCK_ALL_FROZEN_CLEARED` flags. Storage does not rely on block references to find VM changes. Four mechanisms cover it:

1. **The pageserver derives the VM clear from the record's flags.**
   - `libs/wal_decoder/src/decoder.rs`, `decode_neonmgr_record` (line 499): `XLOG_NEON_HEAP_INSERT` (`XLH_INSERT_ALL_VISIBLE_CLEARED`, line 523), `DELETE` (line 529), `UPDATE`/`HOT_UPDATE` (old and new page, lines 539 and 542), `MULTI_INSERT` (line 562) and `LOCK` (`XLH_LOCK_ALL_FROZEN_CLEARED`, line 568, clearing all-frozen only).
   - These become `NeonrmgrRecord::ClearVmBits` (line 590).
   - Vanilla `RM_HEAP`/`RM_HEAP2` records are decoded the same way, per major (`decode_heapam_record`, line 193). That covers `XLOG_HEAP2_LOCK_UPDATED`, which stays `RM_HEAP2` in the fork.
2. **The clear is stored on the VM page itself.**
   - `pageserver/src/walingest.rs` sends both record kinds to `ingest_clear_vm_bits` (lines 260–271).
   - `ingest_clear_vm_bits` (line 402) maps each heap block to its VM block (`HEAPBLK_TO_MAPBLOCK`) and puts a `NeonWalRecord::ClearVisibilityMapFlags` on that VM block's key (lines 459–506).
   - Page reconstruction applies it and sets the VM page's LSN (`pageserver/src/walredo/apply_neon.rs`, lines 71–110).

   The VM page's history in the pageserver therefore contains the clear whether or not the heap record registered the VM block. No storage path depends on block references to see VM changes, so there is no WAL summarizer and no incremental backup that could miss one.
3. **A compute never relies on its own disk for a VM page.**
   - Pages come from the pageserver, so there is no local torn page to recover from.
   - When a compute evicts a dirty VM or FSM page, `neon_wallog_page` always WAL-logs it as a full page first (`pgxn/neon/pagestore_smgr.c`, lines 338–366), and `neon_wallog_pagev` does the same (lines 181–212).
   - So an unregistered VM change on the compute is not lost either.
4. **Replicas replay the clear from the flags.** `pgxn/neon_rmgr/neon_rmgr.c` clears the VM bits in its redo of each record when the flag is set: insert at lines 237–243, delete at 346–352, update at 447–453 and 531–537, lock at 695–696, multi-insert at 778.

Neon does not take incremental base backups (`pg_basebackup --incremental`) of a compute, because a compute has no durable data directory.

## How the 17.11 merge must be resolved (option (a))

- **`heapam.c`.** Every heap record the fork writes keeps its 17.8 layout: no `HEAP_*_BLKREF_VM` registration and no `PageSetLSN` of the VM buffer for the record. This applies to the `RM_NEON_ID` records and to `XLOG_HEAP2_LOCK_UPDATED`.
  - Some of upstream's additions merge without a conflict and must be removed by hand: the VM registration in `heap_lock_tuple`'s `XLOG_NEON_HEAP_LOCK` path, and the VM `PageSetLSN` in `heap_multi_insert`.
  - The decoder takes the old heap block of an update from `decoded.blocks.last()` (`decoder.rs`, line 540). An extra VM block in a record would therefore be read as the old heap block and clear the wrong VM bits.
- **The redo side.** `heapam_xlog.c` and `neon_rmgr` keep reading the records without a VM block. Upstream's VM handling in redo must not require a block reference that the fork's records do not carry.
- **Keep the rest of upstream's fix:** the visibility-map locking around the critical section, and the block-reference macros, which do no harm.

## The test

`test_runner/regress/test_loams_vm_clear.py::test_loams_vm_clear_without_vm_block_reference` runs in the gate's G2 subset on Postgres 16 and up.

1. It sets VM bits with `VACUUM FREEZE`.
2. It clears them with an insert, a `COPY` (multi-insert), a delete, an update and a row lock (all-frozen only).
3. It checks `pg_visibility_map` and an index-only scan in three places:
   - on a branch at the LSN right after the changes. The pageserver reconstructs these pages from WAL; the primary has 128 MB of buffers, so no VM full-page image came first.
   - on the primary after `clear_buffers`;
   - on a hot-standby replica.
4. **A guard on the record format.** No WAL record whose block 0 is a heap page of those tables also registers a VM-fork block (`pg_get_wal_block_info`). This fails if a merge brings upstream's extra block reference into the fork's records.

It passes on today's 16 and 17 trees, and it must pass at 17.11 before `loams/REL_17_STABLE` is promoted.
