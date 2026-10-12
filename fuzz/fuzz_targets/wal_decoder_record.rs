//! One WAL record, decoded and interpreted as the pageserver does with what
//! a safekeeper streams to it (`InterpretedWalRecord::from_bytes_filtered`).
//! The WAL comes from the compute, which runs tenant code, so it is untrusted.
//!
//! The first byte picks the Postgres major and the sharding (unsharded, or
//! the four shards of a four-shard tenant); the rest is the record.
#![no_main]

use bytes::Bytes;
use libfuzzer_sys::fuzz_target;
use pageserver_api::shard::{DEFAULT_STRIPE_SIZE, ShardCount, ShardIdentity, ShardNumber};
use postgres_ffi::PgMajorVersion;
use utils::lsn::Lsn;
use wal_decoder::models::InterpretedWalRecord;

fuzz_target!(|data: &[u8]| {
    let Some((&selector, record)) = data.split_first() else {
        return;
    };
    let versions = PgMajorVersion::ALL;
    let pg_version = versions[usize::from(selector & 0x7f) % versions.len()];
    let shards: Vec<ShardIdentity> = if selector & 0x80 == 0 {
        vec![ShardIdentity::unsharded()]
    } else {
        (0..4)
            .map(|n| {
                ShardIdentity::new(ShardNumber(n), ShardCount::new(4), DEFAULT_STRIPE_SIZE).unwrap()
            })
            .collect()
    };
    let _ = InterpretedWalRecord::from_bytes_filtered(
        Bytes::copy_from_slice(record),
        &shards,
        Lsn(0x0100_0000),
        pg_version,
    );
});
