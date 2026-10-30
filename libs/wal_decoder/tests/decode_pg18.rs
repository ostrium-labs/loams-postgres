//! Postgres 18 WAL through the decoder (NF2 Task 5, Loams-Patch LP-0041).
//!
//! Records are built by hand from REL_18_6's struct layouts, so these tests
//! need no running Postgres. `decode_all_rmgrs_pg18` gives every built-in
//! resource manager and Neon's one record at 18 and checks what the decoder
//! makes of it; the format diff (docs/loams/pg18-format-diff.md) says which
//! layouts changed (F01, F15) and which did not.

use bytes::{BufMut, Bytes, BytesMut};
use pageserver_api::shard::ShardIdentity;
use postgres_ffi::{PgMajorVersion, pg_constants};
use utils::lsn::Lsn;
use wal_decoder::models::*;

const PG18: PgMajorVersion = PgMajorVersion::PG18;

/// A block reference: (fork, rel (spc, db, rel), block number, block data).
struct Blk {
    fork: u8,
    rel: (u32, u32, u32),
    blkno: u32,
    data: Vec<u8>,
}

fn blk(rel: u32, blkno: u32) -> Blk {
    Blk {
        fork: 0,
        rel: (1663, 5, rel),
        blkno,
        data: vec![0xEE; 8],
    }
}

/// An XLogRecord: the 24-byte header, block headers, the main data header,
/// then block data and main data (xloginsert.c's XLogRecordAssemble).
fn record(rmid: u8, info: u8, xid: u32, blocks: &[Blk], main: &[u8]) -> Bytes {
    let mut headers = BytesMut::new();
    for (id, b) in blocks.iter().enumerate() {
        headers.put_u8(id as u8);
        let mut fork_flags = b.fork;
        if !b.data.is_empty() {
            fork_flags |= pg_constants::BKPBLOCK_HAS_DATA;
        }
        headers.put_u8(fork_flags);
        headers.put_u16_le(b.data.len() as u16);
        headers.put_u32_le(b.rel.0);
        headers.put_u32_le(b.rel.1);
        headers.put_u32_le(b.rel.2);
        headers.put_u32_le(b.blkno);
    }
    if !main.is_empty() {
        if main.len() <= 255 {
            headers.put_u8(pg_constants::XLR_BLOCK_ID_DATA_SHORT);
            headers.put_u8(main.len() as u8);
        } else {
            headers.put_u8(pg_constants::XLR_BLOCK_ID_DATA_LONG);
            headers.put_u32_le(main.len() as u32);
        }
    }
    let mut body = headers;
    for b in blocks {
        body.put_slice(&b.data);
    }
    body.put_slice(main);

    let mut rec = BytesMut::new();
    rec.put_u32_le(24 + body.len() as u32); // xl_tot_len
    rec.put_u32_le(xid); // xl_xid
    rec.put_u64_le(0x0100_0000); // xl_prev
    rec.put_u8(info);
    rec.put_u8(rmid);
    rec.put_u16_le(0); // padding
    rec.put_u32_le(0); // xl_crc: the decoder does not check it
    rec.put_slice(&body);
    rec.freeze()
}

fn decode(rec: Bytes) -> anyhow::Result<InterpretedWalRecord> {
    let shard = ShardIdentity::unsharded();
    let mut out =
        InterpretedWalRecord::from_bytes_filtered(rec, &[shard], Lsn(0x0200_0000), PG18)?;
    Ok(out.remove(&shard).unwrap())
}

fn meta(rmid: u8, info: u8, blocks: &[Blk], main: &[u8]) -> Option<MetadataRecord> {
    let ctx = format!("rmid {rmid} info {info:#04x}");
    decode(record(rmid, info, 900, blocks, main))
        .unwrap_or_else(|e| panic!("{ctx}: {e:#}"))
        .metadata_record
}

/// A commit's main data at 18: dbinfo, relfilelocators, dropped stats with
/// 16-byte items, invalidations, a two-phase xid and an origin.
fn commit_main_pg18(twophase_xid: u32) -> Vec<u8> {
    let mut b = BytesMut::new();
    b.put_i64_le(800_000_000); // xact_time
    let xinfo = pg_constants::XACT_XINFO_HAS_DBINFO
        | pg_constants::XACT_XINFO_HAS_RELFILENODES
        | postgres_ffi::v18::bindings::XACT_XINFO_HAS_DROPPED_STATS
        | pg_constants::XACT_XINFO_HAS_INVALS
        | pg_constants::XACT_XINFO_HAS_TWOPHASE
        | pg_constants::XACT_XINFO_HAS_ORIGIN;
    b.put_u32_le(xinfo);
    b.put_u32_le(5); // dbId
    b.put_u32_le(1663); // tsId
    b.put_i32_le(2); // nrels
    for rel in [16384, 16390] {
        b.put_u32_le(1663);
        b.put_u32_le(5);
        b.put_u32_le(rel);
    }
    b.put_i32_le(2); // nitems
    for objid in [16384u64, 0x1_0000_4001] {
        b.put_i32_le(2); // kind
        b.put_u32_le(5); // dboid
        b.put_u32_le(objid as u32); // objid_lo
        b.put_u32_le((objid >> 32) as u32); // objid_hi
    }
    b.put_i32_le(1); // nmsgs
    b.put_bytes(0xAB, 16);
    b.put_u32_le(twophase_xid);
    b.put_u64_le(0x0000_0001_2345_6780); // origin_lsn
    b.put_i64_le(42); // origin_timestamp
    b.to_vec()
}

#[test]
fn decode_all_rmgrs_pg18() {
    // RM_XLOG_ID: a shutdown checkpoint, with 18's CheckPoint layout.
    let checkpoint = postgres_ffi::v18::CheckPoint::default().encode().unwrap();
    assert!(matches!(
        meta(pg_constants::RM_XLOG_ID, pg_constants::XLOG_CHECKPOINT_SHUTDOWN, &[], &checkpoint),
        Some(MetadataRecord::Xlog(XlogRecord::Raw(RawXlogRecord { info, .. })))
            if info == pg_constants::XLOG_CHECKPOINT_SHUTDOWN
    ));

    // RM_XACT_ID: COMMIT PREPARED with every section (F15).
    match meta(
        pg_constants::RM_XACT_ID,
        pg_constants::XLOG_XACT_COMMIT_PREPARED | pg_constants::XLOG_XACT_HAS_INFO,
        &[],
        &commit_main_pg18(741),
    ) {
        Some(MetadataRecord::Xact(XactRecord::CommitPrepared(c))) => {
            assert_eq!(c.parsed.xid, 741, "two-phase xid");
            assert_eq!(c.parsed.origin_lsn, Lsn(0x0000_0001_2345_6780), "origin LSN");
            let rels: Vec<u32> = c.parsed.xnodes.iter().map(|r| r.relnode).collect();
            assert_eq!(rels, vec![16384, 16390], "dropped relations");
        }
        _ => panic!("RM_XACT_ID: no CommitPrepared"),
    }

    // RM_SMGR_ID: create (RelFileLocator, ForkNumber).
    let mut m = BytesMut::new();
    m.put_u32_le(1663);
    m.put_u32_le(5);
    m.put_u32_le(16384);
    m.put_i32_le(0);
    match meta(pg_constants::RM_SMGR_ID, pg_constants::XLOG_SMGR_CREATE, &[], &m) {
        Some(MetadataRecord::Smgr(SmgrRecord::Create(c))) => assert_eq!(c.rel.relnode, 16384),
        _ => panic!("RM_SMGR_ID: no Create"),
    }

    // RM_CLOG_ID: zero page, a 64-bit page number since 17.
    let pageno: u64 = 40;
    match meta(pg_constants::RM_CLOG_ID, pg_constants::CLOG_ZEROPAGE, &[], &pageno.to_le_bytes()) {
        Some(MetadataRecord::Clog(ClogRecord::ZeroPage(z))) => {
            assert_eq!(z.segno * pg_constants::SLRU_PAGES_PER_SEGMENT + z.rpageno, 40)
        }
        _ => panic!("RM_CLOG_ID: no ZeroPage"),
    }

    // RM_DBASE_ID: create by file copy (db, ts, src db, src ts).
    let mut m = BytesMut::new();
    for v in [16500u32, 1663, 1, 1663] {
        m.put_u32_le(v);
    }
    match meta(
        pg_constants::RM_DBASE_ID,
        postgres_ffi::v18::bindings::XLOG_DBASE_CREATE_FILE_COPY,
        &[],
        &m,
    ) {
        Some(MetadataRecord::Dbase(DbaseRecord::Create(c))) => assert_eq!(c.db_id, 16500),
        _ => panic!("RM_DBASE_ID: no Create"),
    }

    // RM_TBLSPC_ID: not handled, no metadata, no error.
    let mut m = BytesMut::new();
    m.put_u32_le(16600);
    m.put_slice(b"/x\0");
    assert!(meta(pg_constants::RM_TBLSPC_ID, 0x00, &[], &m).is_none());

    // RM_MULTIXACT_ID: create (mid, moff, nmembers, members).
    let mut m = BytesMut::new();
    m.put_u32_le(7);
    m.put_u32_le(70);
    m.put_i32_le(1);
    m.put_u32_le(900);
    m.put_i32_le(0);
    match meta(pg_constants::RM_MULTIXACT_ID, pg_constants::XLOG_MULTIXACT_CREATE_ID, &[], &m) {
        Some(MetadataRecord::MultiXact(MultiXactRecord::Create(c))) => {
            assert_eq!((c.mid, c.nmembers), (7, 1))
        }
        _ => panic!("RM_MULTIXACT_ID: no Create"),
    }

    // RM_RELMAP_ID: update (dbid, tsid, nbytes, data).
    let mut m = BytesMut::new();
    m.put_u32_le(5);
    m.put_u32_le(1663);
    m.put_i32_le(4);
    m.put_u32_le(0x592717);
    assert!(matches!(
        meta(pg_constants::RM_RELMAP_ID, 0x00, &[], &m),
        Some(MetadataRecord::Relmap(RelmapRecord::Update(_)))
    ));

    // RM_STANDBY_ID: running xacts.
    let mut m = BytesMut::new();
    for v in [0u32, 0, 0, 1000, 990, 999] {
        m.put_u32_le(v);
    }
    match meta(pg_constants::RM_STANDBY_ID, pg_constants::XLOG_RUNNING_XACTS, &[], &m) {
        Some(MetadataRecord::Standby(StandbyRecord::RunningXacts(r))) => {
            assert_eq!(r.oldest_running_xid, 990)
        }
        _ => panic!("RM_STANDBY_ID: no RunningXacts"),
    }

    // RM_HEAP_ID: an insert that cleared all-visible (xl_heap_insert, F29).
    let main = [1u8, 0, pg_constants::XLH_INSERT_ALL_VISIBLE_CLEARED];
    match meta(pg_constants::RM_HEAP_ID, pg_constants::XLOG_HEAP_INSERT, &[blk(16384, 3)], &main) {
        Some(MetadataRecord::Heapam(HeapamRecord::ClearVmBits(c))) => {
            assert_eq!(c.new_heap_blkno, Some(3));
            assert_eq!(c.old_heap_blkno, None);
        }
        _ => panic!("RM_HEAP_ID: no ClearVmBits"),
    }

    // RM_HEAP2_ID: a multi-insert that cleared all-visible
    // (flags, ntuples, offsets).
    let main = [pg_constants::XLH_INSERT_ALL_VISIBLE_CLEARED, 0, 1, 0, 1, 0];
    match meta(
        pg_constants::RM_HEAP2_ID,
        pg_constants::XLOG_HEAP2_MULTI_INSERT,
        &[blk(16384, 4)],
        &main,
    ) {
        Some(MetadataRecord::Heapam(HeapamRecord::ClearVmBits(c))) => {
            assert_eq!(c.new_heap_blkno, Some(4))
        }
        _ => panic!("RM_HEAP2_ID: no ClearVmBits"),
    }

    // RM_REPLORIGIN_ID: set (remote_lsn, node_id, force).
    let mut m = BytesMut::new();
    m.put_u64_le(0x5000);
    m.put_u16_le(3);
    m.put_u8(1);
    m.put_u8(0);
    match meta(pg_constants::RM_REPLORIGIN_ID, pg_constants::XLOG_REPLORIGIN_SET, &[], &m) {
        Some(MetadataRecord::Replorigin(ReploriginRecord::Set(s))) => {
            assert_eq!((s.node_id, s.remote_lsn), (3, Lsn(0x5000)))
        }
        _ => panic!("RM_REPLORIGIN_ID: no Set"),
    }

    // RM_LOGICALMSG_ID: Neon's aux-file message (F41).
    let prefix = b"neon-file:pg_logical/replorigin_checkpoint\0";
    let message = b"abc";
    let mut m = BytesMut::new();
    m.put_u32_le(5); // dbId
    m.put_u32_le(0); // transactional, padded
    m.put_u64_le(prefix.len() as u64);
    m.put_u64_le(message.len() as u64);
    m.put_slice(prefix);
    m.put_slice(message);
    match meta(pg_constants::RM_LOGICALMSG_ID, pg_constants::XLOG_LOGICAL_MESSAGE, &[], &m) {
        Some(MetadataRecord::LogicalMessage(LogicalMessageRecord::Put(p))) => {
            assert_eq!(p.path, "pg_logical/replorigin_checkpoint");
            assert_eq!(&p.buf[..], message);
        }
        _ => panic!("RM_LOGICALMSG_ID: no Put"),
    }

    // RM_NEON_ID: the fork's heap insert (F28), ported unchanged.
    let main = [1u8, 0, pg_constants::XLH_INSERT_ALL_VISIBLE_CLEARED];
    match meta(
        pg_constants::RM_NEON_ID,
        pg_constants::XLOG_NEON_HEAP_INSERT,
        &[blk(16384, 5)],
        &main,
    ) {
        Some(MetadataRecord::Neonrmgr(NeonrmgrRecord::ClearVmBits(c))) => {
            assert_eq!(c.new_heap_blkno, Some(5))
        }
        _ => panic!("RM_NEON_ID: no ClearVmBits"),
    }

    // The block-only resource managers: btree, hash, gin, gist, sequence,
    // spgist, brin, commit_ts and generic. No metadata; the block goes to
    // the batch.
    for rmid in 11u8..=18 {
        let rec = decode(record(rmid, 0x00, 900, &[blk(16400, 1)], &[0u8; 4]))
            .unwrap_or_else(|e| panic!("rmid {rmid}: {e:#}"));
        assert!(rec.metadata_record.is_none(), "rmid {rmid}");
        assert!(rec.batch.has_data(), "rmid {rmid}: the block reached the batch");
    }
    let rec = decode(record(20, 0x00, 900, &[blk(16400, 1)], &[])).unwrap();
    assert!(rec.metadata_record.is_none() && rec.batch.has_data(), "generic");
}

/// A resource manager id that 18 does not have is an error at 18, never
/// skipped (the plan's review focus 1). 14 to 17 keep their behaviour.
#[test]
fn unknown_rmgr_is_error_pg18() {
    for rmid in [22u8, 100, 127, 128, 200, 255] {
        let err = decode(record(rmid, 0x00, 900, &[], &[0u8; 4]))
            .err()
            .unwrap_or_else(|| panic!("rmid {rmid} decoded"));
        assert!(err.to_string().contains("resource manager"), "{err}");
    }
}

/// `xact_stats_item_size_pg18` through the decoder: a commit and an abort
/// with dropped stats read every later section at 18's 16-byte item size.
#[test]
fn xact_stats_item_size_pg18_decoder() {
    for info in [
        pg_constants::XLOG_XACT_COMMIT,
        pg_constants::XLOG_XACT_ABORT,
        pg_constants::XLOG_XACT_ABORT_PREPARED,
    ] {
        let parsed = match meta(
            pg_constants::RM_XACT_ID,
            info | pg_constants::XLOG_XACT_HAS_INFO,
            &[],
            &commit_main_pg18(741),
        ) {
            Some(MetadataRecord::Xact(
                XactRecord::Commit(c) | XactRecord::Abort(c) | XactRecord::AbortPrepared(c),
            )) => c.parsed,
            _ => panic!("info {info:#x}: no xact record"),
        };
        assert_eq!(parsed.xid, 741, "info {info:#x}");
        assert_eq!(parsed.origin_lsn, Lsn(0x0000_0001_2345_6780), "info {info:#x}");
        assert_eq!(parsed.xnodes.len(), 2, "info {info:#x}");
    }
}
