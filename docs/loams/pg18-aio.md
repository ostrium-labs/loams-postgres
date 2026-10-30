# Asynchronous I/O at Postgres 18 (NF2 Task 3, D1110)

Design: §62 §4.2 and D1110 in `ostrium-labs/loams`. Patches: LP-0044 (Postgres side, in `loams/pg18`), LP-0043 (`pgxn/neon` and `compute_ctl`).

## What 18 does

Reads through shared buffers go through the read stream and `StartReadBuffers()`/`AsyncReadBuffers()`. These call `smgrstartreadv(PgAioHandle *, ...)`. md.c implements it by handing a file descriptor (`FileStartReadV`) to the AIO subsystem, which then runs the read with the configured `io_method` (`worker`, `io_uring` or `sync`). The completion runs callbacks from a table compiled into core (`PgAioHandleCallbackID`): md's (`PGAIO_HCB_MD_READV`) turns the byte count into blocks and reports short reads, and bufmgr's validates the pages and marks the buffers valid.

## The spike's question, and the answer

Can a storage manager without file descriptors, such as Neon's (it fetches pages from the pageserver through the communicator), complete an 18 AIO read from an extension, with no core change?

**No.** An extension cannot register completion callbacks, because their table is a fixed enum in core. It also cannot finish a handle without executing an IO: the only staging path runs `pg_preadv()` on a descriptor, either synchronously or in an IO method. Neon's own 18 branch (`REL_18_STABLE_neon`) leaves the core path unchanged, so its unpublished `pgxn/neon` must do something we cannot see. We do not use that branch as a base (D1109).

So, as §62 §12's first risk allows, the bypass is ours, a small core patch with an id and a drop condition (**LP-0044**):

- `smgrstartreadv()`: for an smgr that leaves `smgr_startreadv` unset, the read happens synchronously through `smgr_readv` (for Neon, the communicator, with its prefetch and LFC). The handle then completes at once with md's callbacks, through `pgaio_io_stage_completed()`, which is new in `aio.c`. It stages an IO the caller has already performed and runs its completion; the IO is never submitted to an IO method. bufmgr's own callbacks then validate the pages and mark the buffers valid, as for md.c.
- `smgrmaxcombine()`: an unset `smgr_maxcombine` leaves combining to the read stream (`PG_IOV_MAX`, capped there by `io_combine_limit`).
- `smgrfd()`: an unset `smgr_fd` is an error. Only an IO worker reopening a file calls it, and a descriptor-less read never reaches a worker.

`pgxn/neon` and `neon_walredo`'s in-memory smgr leave all three unset.

## Configuration

Because no read reaches an IO method, the bypass works under every `io_method`. `compute_ctl` still writes `io_method = 'sync'` at 18 and later, after the spec's own settings, and refuses a spec that sets `io_method` (`io_method_locked`). This is D1110's rule, and it matches what Neon's service does. Writes do not use AIO at 18.

## Cost and later work

Sequential scans lose AIO's overlap, but they keep Neon's prefetch. The read stream issues advice for sequential patterns too, because under `NEON_SMGR` it does not assume kernel readahead (port of `01fa3c4866`). That advice reaches `neon_prefetch()`, which overlaps page-service round trips.

`read_stream_seqscan_pg18` records the prefetch hit rate of a 10 GB scan in G2 at 18. A native AIO target whose completions come from the communicator is later work (NF3). It starts only if those measurements say it pays, and LP-0044 is dropped then.

## Tests

- `io_method_locked` and `io_method_sync_from_18` (compute_tools).
- `loams-pgxn-18.yml`: the neon extensions build against `vendor/postgres-v18` on every pull request that touches them.
- G2 at 18, once Task 7's 18 leg runs with Task 8's images: the LFC and prefetch tests, and `read_stream_seqscan_pg18`.
