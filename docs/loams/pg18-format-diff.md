# Postgres 18 format diff: 17.11 → 18.6

This is the written diff that design §51 §8.3 requires before a major is ported (NF2 Task 1, LP-0034). It compares upstream `postgres/postgres` at `REL_17_11` (`083ac033`) with `REL_18_6` (`724edf9b`), header by header, for everything §51 §8.3 lists:

- `XLOG_PAGE_MAGIC` and the record framing;
- `rmgrlist.h` and every `*_xlog.h` (one header per resource manager);
- `pg_control.h`;
- the SLRU layouts;
- `xl_running_xacts`;
- the checkpoint records;
- the smgr API.

It also confirms or corrects design §62 §4.1.

**Status: Postgres 18 is beta** in Loams Postgres until NF2 Task 14's gate passes.

## How this was made

- Each header was fetched at both tags from `raw.githubusercontent.com/postgres/postgres/<tag>/src/include/...` and diffed with copyright lines ignored. No local clone was made.
- Where a format lives in a `.c` file, the `.c` file was diffed too. That covers the SLRU constants in `clog.c`, `commit_ts.c`, `multixact.c`, `subtrans.c` and `slru.c`, the two-phase state file in `twophase.c`, the relation map in `relmapper.c`, the snapshot and origin files, and the `XLogRegister*` calls in `xact.c` and `heapam.c`.
- Each upstream commit was found with `GET repos/postgres/postgres/commits?sha=REL_18_6&path=<header>` and checked against its patch.
- The Rust and C that read each format were checked at this repository's `main` (`f39cb8be`). Line numbers below are at that commit.

The upstream header diff is not the whole story for this fork. 17.11 already carries upstream's visibility-map block references, and the fork reverted them at 17 (`docs/loams/pg17-vm-clear.md`). Neon's own Postgres 18 branch also carries a redo fix that our ported series does not have. Both are rows below (F27, F28).

## Classifications

Each item gets exactly one class. `scripts/loams/format-diff-check.py` enforces that (`format_diff_has_no_unclassified_items`, in `loams-hygiene.yml`).

| Class | Meaning |
|---|---|
| decoder | The record or page bytes change, so the WAL decoders must read them per major: `postgres_ffi`, `wal_decoder`, and Loams' `loams-wal-decoder` |
| walingest | The pageserver's ingest, bootstrap, import or basebackup must change: `walingest.rs`, `basebackup.rs`, `import_datadir.rs`, `import_pgdata`, `postgres_initdb` |
| redo | WAL redo must change: the `neon_walredo` process, `neon_rmgr`, or heap redo in the ported Postgres series |
| compute only | Only the compute changes (`pgxn/neon`, `compute_ctl`, the Postgres series). Storage and the formats storage reads are unaffected |
| none | No change that matters here |

## Constants

| Constant | 17.11 | 18.6 | Upstream |
|---|---|---|---|
| `XLOG_PAGE_MAGIC` | `0xD116` | `0xD118` | `0xD117` in `b14e9ce7d5`, then `0xD118` in `243e9b40f1` |
| `PG_CONTROL_VERSION` | 1700 | 1800 | `44fe30fdab` |
| `CATALOG_VERSION_NO` | 202406281 | 202506291 | Last bumped in `9c5b9a280c` (pre-release housekeeping, 2025-06-30) |
| Resource managers | 22 | 22 | `rmgrlist.h` unchanged |
| `SizeOf(xl_xact_stats_item)` | 12 | 16 | `b14e9ce7d5` |
| `sizeof(SharedInvalidationMessage)` | 16 | 16 | A new member (`3abe9dc188`) is 12 bytes; the union size is unchanged |
| `sizeof(ControlFileData)`, offset of `crc` | — | +4 bytes | `44fe30fdab`: a `bool` after `data_checksum_version` |

## Items

### WAL framing and resource managers

| Id | Item | Header | 17.11 → 18.6 | Upstream | Classification | Where the work lands |
|---|---|---|---|---|---|---|
| F01 | `XLOG_PAGE_MAGIC` | `access/xlog_internal.h` | `0xD116` → `0xD118` | `b14e9ce7d5`, `243e9b40f1` | decoder | `libs/postgres_ffi/build.rs` (the bindgen loop, line 60, gains `v18`); `waldecoder_handler.rs` line 41 and `xlog_utils.rs` (lines 458 and 490) take it from the v18 bindings; `postgres_versioninfo` `PG18`; Loams' `loams-wal-decoder`. An unknown magic must stay an error (`unknown_page_magic_is_error`, Task 4) |
| F02 | `XLogPageHeaderData`, `XLogLongPageHeaderData`, `XLP_*` flags | `access/xlog_internal.h` | Unchanged | — | none | — |
| F03 | `XLogRecord`, block headers, `XLR_*`, `BKPBLOCK_*`, `BKPIMAGE_*` (compression flags) | `access/xlogrecord.h` | Unchanged | — | none | — |
| F04 | `XLogRecData.data` is `const void *` (was `char *`) | `access/xlog_internal.h` | In-memory only | `cdaeff9b39` | compute only | Source compatibility for the Postgres series and `pgxn/neon` |
| F05 | `XLogRegisterData`, `XLogRegisterBufData` take `const void *`; `log_newpage*` take `PageData` | `access/xloginsert.h` | Signatures only | `2b5f57977f`, `cdaeff9b39` | compute only | `pgxn/neon_rmgr`, `pgxn/neon` callers (existing casts still compile) |
| F06 | `XLogReaderState` | `access/xlogreader.h` | Comment only | — | none | — |
| F07 | `xlog.h`: `CommitDelay`/`CommitSiblings` externs, `ckpt_slru_written`, `GetDefaultCharSignedness()`, `BootStrapXLOG(uint32)`, `CreateCheckPoint()` returns `bool` | `access/xlog.h` | Declarations only | `774d47b6c0`, `17cc5f666f`, `44fe30fdab`, `983a588e0b` | compute only | The Postgres series (`docs/core_changes.md` areas that touch `xlog.c`) |
| F08 | `ignore_invalid_pages` extern | `access/xlogutils.h` | Declaration only | `774d47b6c0` | compute only | — |
| F09 | `xlogarchive.h`, `xlogbackup.h`, `xlogdefs.h`, `xlogprefetcher.h`, `xlogrecovery.h`, `xlogstats.h` | `access/` | Unchanged | — | none | — |
| F10 | Resource manager list (22 built-in rmgrs, ids unchanged) | `access/rmgrlist.h` | Unchanged | — | none | `decode_all_rmgrs_pg18` (Task 5) proves it |
| F11 | Custom rmgr range (`RM_MIN_CUSTOM_ID` 128 to `RM_MAX_CUSTOM_ID` 255), so `RM_NEON_ID` 134 still fits | `access/rmgr.h` | Unchanged | — | none | — |

### Records, one resource manager at a time

| Id | Item | Header | 17.11 → 18.6 | Upstream | Classification | Where the work lands |
|---|---|---|---|---|---|---|
| F12 | XLOG rmgr info codes (`XLOG_CHECKPOINT_*`, `XLOG_CHECKPOINT_REDO`, `XLOG_FPI*`, `XLOG_SWITCH`, `XLOG_PARAMETER_CHANGE`, `XLOG_END_OF_RECOVERY`, `XLOG_OVERWRITE_CONTRECORD`) | `catalog/pg_control.h` | Unchanged | — | none | `walingest.rs` lines 1306–1436 |
| F13 | Checkpoint records: the `CheckPoint` struct (online and shutdown checkpoints) | `catalog/pg_control.h` | Unchanged | — | none | `walingest.rs` lines 216 and 1332 decode it through the per-major bindings; v18's are the same layout |
| F14 | `xl_parameter_change`, `xl_restore_point`, `xl_end_of_recovery`, `xl_overwrite_contrecord` | `access/xlog_internal.h` | Unchanged | — | none | — |
| F15 | `xl_xact_stats_item` grows from 12 to 16 bytes: `objoid` becomes `objid_lo` and `objid_hi` | `access/xact.h` | Changed | `b14e9ce7d5` | decoder | `libs/postgres_ffi/src/walrecord.rs` line 1061 hard-codes `sizeof_xl_xact_stats_item = 12`. It must be 16 from 18 (`XlXactParsedRecord::decode` needs the major). See "Corrections to §62 §4.1" for what goes wrong otherwise. Test: `xact_stats_item_size_pg18` (Task 5) |
| F16 | The rest of the commit and abort records (`xl_xact_commit`, `xl_xact_abort`, `xl_xact_xinfo` flags, `dbinfo`, `subxacts`, `relfilelocators`, `invals`, `twophase`, `origin`) and `xl_xact_prepare`, `xl_xact_assignment` | `access/xact.h` | Unchanged. The section order in `xact.c` is unchanged too | — | none | — |
| F17 | `xl_smgr_create`, `xl_smgr_truncate` (`SMGR_TRUNCATE_*`) | `catalog/storage_xlog.h` | Unchanged | — | none | — |
| F18 | `xl_clog_truncate`, `CLOG_ZEROPAGE` (64-bit page numbers since 17) | `access/clog.h` | Unchanged | — | none | `decoder.rs` line 760 already reads 64-bit page numbers from 17 |
| F19 | `xl_dbase_create_*_rec`, `xl_dbase_drop_rec` | `commands/dbcommands_xlog.h` | Unchanged | — | none | `decoder.rs` line 719 (the 17 arm serves 18) |
| F20 | `xl_tblspc_create_rec`, `xl_tblspc_drop_rec` (the header only gains GUC externs) | `commands/tablespace.h` | Records unchanged | `774d47b6c0` (externs) | none | — |
| F21 | `xl_multixact_create`, `xl_multixact_truncate`, 32-bit `MultiXactOffset` | `access/multixact.h` | Unchanged (19 changes it, §62 §5.1) | — | none | `decoder.rs` line 852 |
| F22 | `xl_relmap_update`, `RelMapFile` (`RELMAPPER_FILEMAGIC` `0x592717`) | `utils/relmapper.h`, `relmapper.c` | Unchanged | — | none | `decoder.rs` line 888 |
| F23 | `xl_running_xacts` | `storage/standbydefs.h` | Unchanged | — | none | `decoder.rs` line 956 |
| F24 | `xl_standby_locks`, `xl_invalidations` | `storage/standbydefs.h` | Unchanged | — | none | — |
| F25 | `SharedInvalidationMessage` gains `SharedInvalRelSyncMsg` (id −6). The union stays 16 bytes, so the commit record's and the standby record's invalidation arrays keep their stride | `storage/sinval.h` | New member, same size | `3abe9dc188` | none | `walrecord.rs` line 1066 skips `nmsgs * 16`, which still holds. Task 4 adds a size assertion to `pg_constants_v18_match_headers` |
| F26 | `xl_heap_inplace` carries `dbId`, `tsId`, `relcacheInitFileInval`, `nmsgs` and the invalidation messages (`MinSizeOfHeapInplace`); `SizeOfHeapInplace` is gone | `access/heapam_xlog.h` | Changed | `243e9b40f1` | redo | **The decoder never reads this record's main data.** `decode_heapam_record` (`decoder.rs` line 409) has no `XLOG_HEAP_INPLACE` arm, and the record reaches the pageserver as a block record, so ingest is unaffected. **Redo is affected.** 18.6's `heap_xlog_inplace` calls `ProcessCommittedInvalidationMessages()` unconditionally. With `relcacheInitFileInval` set, that unlinks the relcache init files, and `unlink` is not in `neon_walredo`'s seccomp allow-list (`walredoproc.c` lines 174–205). The walredo process could then be killed on a catalog in-place update. Neon's `REL_18_STABLE_neon` guards the call with `if (!am_wal_redo_postgres)` (`f368841ccf`, "Stop sending invalidation messages during WAL redo"). Task 2's port must carry the same guard, and Task 6 tests it (a `VACUUM` of a catalog read back through a branch) |
| F27 | **Heap records register the visibility-map buffer** (block ids `HEAP_*_BLKREF_VM`) and can carry VM full-page images. This is the 18 back-patch of 17.11's `c0d9864f`, new in 18.6 | `access/heapam_xlog.h`, `heapam.c`, `heapam_xlog.c`, `visibilitymap.c` | Unchanged between the tags (17.11 has it too), **but the fork reverted it at 17** | `f581fa729d`, `d0fb1da21b` (macros) | redo | The ported series must keep the fork's heap format at 18 as option (a) did at 17.11. At 18, heap redo lives in `heapam_xlog.c` (moved by `00c76cf21c`), so the revert covers `heapam.c` and `heapam_xlog.c`; the `pg_walsummary` and `pg_combinebackup` test changes are reverted with it. If it is not reverted, `decoder.rs` (lines 432 and 540) reads an update's old heap block from `decoded.blocks.last()` and would take the VM block. `test_loams_vm_clear` must run at 18. **Open for the lead:** D1112 names 17.11 and 19, not 18 |
| F28 | The fork's own `RM_NEON_ID` heap records (`xl_neon_heap_*`) | `pgxn/neon_rmgr`, the Postgres series | Not upstream; ported unchanged | — | none | `decode_neonmgr_record` (`decoder.rs` line 516) gains `PG18` beside `PG16` and `PG17` (Task 5) |
| F29 | The other heap records: `xl_heap_insert`, `delete`, `update`, `lock`, `lock_updated`, `multi_insert`, `prune`, `visible`, `new_cid`, `rewrite_mapping`, `truncate`, `confirm`, and the `XLH_*` flags | `access/heapam_xlog.h` | Unchanged | — | none | `decoder.rs` line 409's 17 arm serves 18 |
| F30 | `nbtxlog.h` (B-tree) | `access/nbtxlog.h` | Unchanged | — | none | — |
| F31 | `hash_xlog.h` (hash) | `access/hash_xlog.h` | Unchanged | — | none | — |
| F32 | `ginxlog.h` (GIN) | `access/ginxlog.h` | Unchanged | — | none | — |
| F33 | `gistxlog.h` (GiST) | `access/gistxlog.h` | Unchanged | — | none | — |
| F34 | `spgxlog.h` (SP-GiST) | `access/spgxlog.h` | Unchanged | — | none | — |
| F35 | `brin_xlog.h` (BRIN) | `access/brin_xlog.h` | Unchanged | — | none | — |
| F36 | `xl_seq_rec` (sequence) | `commands/sequence.h` | Unchanged | — | none | — |
| F37 | `generic_xlog.h` (generic WAL) | `access/generic_xlog.h` | Unchanged | — | none | — |
| F38 | `xl_commit_ts_truncate` (commit timestamps) | `access/commit_ts.h` | Unchanged | — | none | — |
| F39 | `xl_replorigin_set`, `xl_replorigin_drop` | `replication/origin.h` | Unchanged | — | none | `decoder.rs` line 968 |
| F40 | `MAX_RONAME_LEN` (512) and the `max_active_replication_origins` GUC | `replication/origin.h` | New | `16bf24e0e4`, `04ff636cbc` | compute only | `compute_ctl` keeps 17's logical-replication settings (§62 §4.6) |
| F41 | `xl_logical_message` (Neon's `neon-file:` aux files ride on it) | `replication/message.h` | Unchanged | — | none | `decoder.rs` line 920 |
| F42 | Two-phase state files (`TWOPHASE_MAGIC` `0x57F94534`, `TwoPhaseFileHeader`) | `twophase.c`, `access/twophase.h` | Unchanged (the header gains functions only) | — | none | The pageserver writes `pg_twophase` from the `PREPARE` record |

### Control file

| Id | Item | Header | 17.11 → 18.6 | Upstream | Classification | Where the work lands |
|---|---|---|---|---|---|---|
| F43 | `PG_CONTROL_VERSION` 1700 → 1800 | `catalog/pg_control.h` | Changed | `44fe30fdab` | walingest | The pageserver keeps initdb's control file and rewrites its checkpoint fields (`basebackup.rs` lines 338–355; `xlog_utils.rs` line 143). The bindings it uses must be v18's |
| F44 | `ControlFileData.default_char_signedness` (`bool` after `data_checksum_version`). `mock_authentication_nonce` moves by 1 byte, and `crc` and the struct size move by 4 | `catalog/pg_control.h` | Changed | `44fe30fdab` | walingest | `controlfile_utils.rs` `decode`/`encode` (the CRC offset comes from the struct) with v18 bindings; `import_datadir.rs` lines 38 and 531. initdb sets the field; the pageserver must carry it, never reset it. `pg_upgrade --set-char-signedness` matters for Path 3 (§62 §10) |
| F45 | `import_pgdata` reads every control file with **v14's layout** (`importbucket_client.rs` line 255, "XXX … v17 had changes"). At 18 the CRC is at a different offset, so an 18 data directory is refused with "invalid CRC". `try_pg_version` (line 278) knows catalog versions only up to 202406281 | `catalog/pg_control.h`, `catalog/catversion.h` | Changed | `44fe30fdab`, `9c5b9a280c` | walingest | Read `catalog_version_no` (same offset in every major) first, then decode with that major's bindings; add `202506291 => PG18` (Task 5; the importer also gets D1111's checksum refusal) |
| F46 | `CATALOG_VERSION_NO` 202406281 → 202506291 | `catalog/catversion.h` | Changed | `9c5b9a280c` | walingest | F45's map; `postgres_versioninfo` (Task 4) |

### SLRU and other on-disk files the pageserver serves

| Id | Item | Header | 17.11 → 18.6 | Upstream | Classification | Where the work lands |
|---|---|---|---|---|---|---|
| F47 | `SLRU_PAGES_PER_SEGMENT` (32); segment file names (`%04X`, or 15 hex digits for long segments, since 17) | `access/slru.h`, `slru.c` | Unchanged (a format-string spelling only) | — | none | `basebackup.rs`, `nonrelfile_utils.rs` |
| F48 | CLOG page layout (`CLOG_BITS_PER_XACT` 2, `CLOG_XACTS_PER_PAGE`) | `clog.c` | Unchanged | — | none | — |
| F49 | `commit_ts` entry layout | `commit_ts.c` | Unchanged | — | none | — |
| F50 | MultiXact offsets and members pages (member groups, `MULTIXACT_*` constants) | `multixact.c` | Unchanged | — | none | — |
| F51 | `pg_subtrans` layout | `subtrans.c` | Unchanged | — | none | — |
| F52 | Replication slot files: `SLOT_MAGIC`, `SLOT_VERSION` 5 and `ReplicationSlotPersistentData` are unchanged. `ReplicationSlotInvalidationCause` becomes bit flags (`RS_INVAL_WAL_LEVEL` 3 → 4), with a new `RS_INVAL_IDLE_TIMEOUT` (8) | `replication/slot.h` | Values change, layout unchanged | `ac0e33136a` | compute only | The pageserver stores `pg_replslot/` as opaque aux files (`aux_file.rs` line 78, `basebackup.rs` line 486) and never parses them. Slot invalidation by `idle_replication_slot_timeout` must survive a restart (`slot_invalidation_survives_restart_pg18`, Task 6) |
| F53 | Logical snapshots (`SNAPBUILD_MAGIC`, `SNAPBUILD_VERSION` 6; `SnapBuild` moved to `snapbuild_internal.h` with the same fields) | `replication/snapbuild_internal.h` | Unchanged | — | none | Opaque aux files (`aux_file.rs` line 66) |
| F54 | `pg_logical/replorigin_checkpoint` (`REPLICATION_STATE_MAGIC` `0x1257DADE`, `ReplicationStateOnDisk`) | `origin.c` | Unchanged | — | none | `basebackup.rs` line 542 builds it |
| F55 | Page layout: `PageHeaderData`, `PG_PAGE_LAYOUT_VERSION` 4 | `storage/bufpage.h` | Unchanged | — | none | — |
| F56 | Visibility-map page bits (`VISIBILITYMAP_*`) | `access/visibilitymapdefs.h` | Unchanged | — | none | `walingest.rs` `ingest_clear_vm_bits` |

### The smgr API and the read path

| Id | Item | Header | 17.11 → 18.6 | Upstream | Classification | Where the work lands |
|---|---|---|---|---|---|---|
| F57 | `smgrstartreadv(PgAioHandle *, …)`, `smgrmaxcombine()`, `aio_smgr_target_info`, `pgaio_io_set_target_smgr()` | `storage/smgr.h` | New | `50cb7505b3`, `755a4c10d1` | compute only | `pgxn/neon/pagestore_smgr.c`'s `f_smgr` (line 2222) gains `smgr_startreadv`, `smgr_maxcombine` and a "no descriptor" `smgr_fd`; `compute_ctl` locks `io_method = sync` (D1110, Task 3) |
| F58 | `smgrtruncate(…, old_nblocks, nblocks)` replaces 17.11's `smgrtruncate2`. This is the 18 form of "Fix corruption when relation truncation fails" | `storage/smgr.h` | Signature | `38c579b089` | compute only | `pagestore_smgr.c`'s truncate callback (Task 6) |
| F59 | `md.h`: `mdstartreadv`, `mdmaxcombine`, `mdfd`, `aio_md_readv_cb`; `mdtruncate`'s parameter renamed | `storage/md.h` | New | `50cb7505b3`, `a6cab6a78e` | compute only | `pagestore_smgr.c` delegates local (temp, unlogged) relations to md (Task 3) |
| F60 | `bufmgr.h`: `ReadBuffersOperation` (`nblocks_done`, `io_wref`, `io_return`, `persistence`), `READ_BUFFERS_IGNORE_CHECKSUM_FAILURES`/`SYNCHRONOUSLY`, `io_max_combine_limit`, `aio_*_buffer_readv_cb`, pin limits, `EvictUnpinnedBuffer(…, bool *)`, `effective_io_concurrency` and `maintenance_io_concurrency` default to 16 | `storage/bufmgr.h` | Changed | `047cba7fa0`, `12ce89fd07`, `ce1a75c4fe`, `10f6646847`, `01261fb078`, `ff79b5b2ab`, `cc6be07ebd`, `dcf7e1697b` | compute only | `pgxn/neon` prefetch and LFC; `compute_ctl`'s per-major templates (Task 3, Task 6) |
| F61 | Read streams: batch mode (`READ_STREAM_USE_BATCHING`), `read_stream_begin_smgr_relation`, `block_range_read_stream_cb` | `storage/read_stream.h` | New | `ae3df4b341`, `a858be17c3`, `c582b75851`, `70d38e3d8a` | compute only | `read_stream_seqscan_pg18` (Task 3) |
| F62 | The AIO subsystem (`io_method` = `worker`, `io_uring` or `sync`) | `storage/aio.h`, `aio_types.h` (new) | New | `da7226993f`, `247ce06b88`, `c325a7633f` | compute only | Task 3 (D1110) |
| F63 | **WAL redo reads buffers through the 18 read path.** `XLogReadBufferForRedo` reaches `StartReadBuffers` and `smgrstartreadv`. `neon_walredo`'s `inmem_smgr` (`inmem_smgr.c` line 364) has no `smgr_startreadv`/`smgr_maxcombine`, and `walredoproc.c` line 534 calls `InitBufferPool()`, which 18 renames `BufferManagerShmemInit()` (`478846e768`) | `storage/smgr.h`, `storage/bufmgr.h` | New | `50cb7505b3`, `12ce89fd07`, `478846e768` | redo | `pgxn/neon_walredo` (Tasks 3 and 6). Neon met this in `REL_18_STABLE_neon` `3750bd51f7` ("we can't really read buffers yet in PG18 in wal-redo postgres") and patched several heap redo functions. Prior art only; our series is ported from `loams/pg17`, not from that branch |
| F64 | `bufpage.h`: `PageData` type, `const` page accessors, `PageIsVerified(page, blkno, flags, &checksum_failure)` replaces `PageIsVerifiedExtended`, `PIV_*` flags | `storage/bufpage.h` | API only | `6e4df237fb`, `4f4a1d853a`, `d445990adc` | compute only | `pgxn/neon` callers |
| F65 | `relpath()` and `GetRelationPath()` return `RelPathStr` by value | `common/relpath.h` | API only | `37c87e63f9` | compute only | `pagestore_smgr.c` line 1045 (`relpath(...).str`) |

### Items already known from §51 §8.3 and §62 §4

| Id | Item | Where | Upstream | Classification | Where the work lands |
|---|---|---|---|---|---|
| K1 | `initdb` turns data checksums on by default | `src/bin/initdb/initdb.c` | `04bec894a0`, `983a588e0b` (`--no-data-checksums`) | walingest | `libs/postgres_initdb` passes `--no-data-checksums` from 18; `import_datadir` and `ImportPgdata` refuse checksums (D1111, Task 5) |
| K2 | Protocol 3.2: 256-bit cancel keys and `min/max_protocol_version` | `libpq/pqcomm.h` | `a460251f0a`, `285613c60a` | compute only | Not a storage format. The gateway, PgDog, pgbouncer and `local_proxy` handle it (§62 §4.4, Task 12) |
| K3 | OAuth (`oauth` in `pg_hba`, `oauth_validator_libraries`) | `libpq/oauth.h` (new) | — | compute only | The compute is built without `--with-libcurl`; `compute_ctl` never writes `oauth` (§62 §4.4) |
| K4 | `uuidv7()` built in; MD5 password warnings | Catalogue | — | compute only | `pg_uuidv7` dropped from 18 (§51 §7.1); D711 already refuses MD5 |

## Corrections to §62 §4.1

| §62 §4.1 says | This diff finds |
|---|---|
| New `XLOG_PAGE_MAGIC` `0xD118` (no commit given) | **Confirmed.** Two bumps: `0xD117` in `b14e9ce7d5` and `0xD118` in `243e9b40f1` |
| `xl_xact_stats_item` 12 → 16 bytes, `b14e9ce7d5`, decoder; "without this change, dropped relations would be **silently missed**" | **Size, commit and class confirmed; the consequence is corrected.** In `xact.c` and in `walrecord.rs` the dropped-stats section comes **after** the relfilelocators, so dropped relations are still read correctly. A 12-byte stride corrupts what follows: the two-phase xid of `COMMIT PREPARED` and `ABORT PREPARED` (ingest then sets CLOG for the wrong xid) and the origin LSN (`walingest.rs` line 906, `set_replorigin`). Both happen only when the record carries dropped stats. Commits that drop tables, functions or other stats objects do. The fix and the test are unchanged |
| `xl_heap_inplace`, `243e9b40f1`, "decoder, redo"; "verify that nothing reads past the fixed part"; "Neon's `t_cid` patch does not cover in-place updates (verify)" | **Corrected to redo only** (F26). The decoder never reads this record's main data. The record carries no tuple header, so `t_cid` does not apply. The real risk is redo: 18.6 processes the invalidations during redo. Neon's fix `f368841ccf` must be in our port |
| Control file `default_char_signedness`, `44fe30fdab`, "walingest, basebackup" | **Confirmed; classified walingest** (basebackup is part of that class here). Adds F45: `import_pgdata` decodes every control file with v14's layout and would refuse 18 with a CRC error |
| `PG_CONTROL_VERSION` 1800, `CATALOG_VERSION_NO` 202506291 | **Confirmed.** Catalog version from `9c5b9a280c` |
| rmgr list unchanged (22 rmgrs), none | **Confirmed** |
| SLRU on disk: no format change found, none (verify) | **Verified, none.** The `clog.c`, `commit_ts.c`, `multixact.c`, `subtrans.c` and `slru.c` constants are identical; only a `printf` format string changed |
| Heap, btree and multixact records: no other format change, none | **Corrected.** No upstream header change between the tags, but 18.6 adds the VM block references (`f581fa729d`), the 18 back-patch of 17.11's `c0d9864f`. The fork reverted that at 17 (option (a)). §62 §4.1 does not list it, and D1112 names 17.11 and 19 only (F27) |
| (not listed) | **Added:** F63, WAL redo through the 18 read path (`inmem_smgr`, `InitBufferPool` renamed); F52, slot invalidation causes renumbered (compute only) |

## Open questions for the NF2 lead

1. **F27: does option (a) / D1112 extend to 18?** The upstream format at 18.6 puts VM block references in heap records. The fork's `RM_NEON_ID` records never had them, and the 17.11 merge reverted them for the vanilla records. This diff assumes Task 2 reverts `f581fa729d` the same way, in `heapam.c` and `heapam_xlog.c`. That decides what a WAL record carries, so it is not ruled here.
2. **Not new at 18:** `XlXactParsedRecord::decode` reads the origin LSN straight after the two-phase xid. It does not skip the GID string when `XACT_XINFO_HAS_GID` is set. A commit-prepared record with both a GID and an origin therefore yields a wrong `origin_lsn` (`walingest.rs` line 906) at every major. Upstream's `ParseCommitRecord` skips the GID. This is recorded for the lead and not fixed here.

## Sources

- `postgres/postgres` tags `REL_17_11` (`083ac033`) and `REL_18_6` (`724edf9b`), the headers and `.c` files named above.
- `ostrium-labs/postgres` `REL_18_STABLE_neon` (frozen), commits `f368841ccf` and `3750bd51f7`, read through the REST API.
- Design §51 §8.3 and §62 §4 in `ostrium-labs/loams`; `docs/loams/pg17-vm-clear.md` here.
