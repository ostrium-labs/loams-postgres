#![allow(non_upper_case_globals)]
#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
// bindgen creates some unsafe code with no doc comments.
#![allow(clippy::missing_safety_doc)]
// noted at 1.63 that in many cases there's u32 -> u32 transmutes in bindgen code.
#![allow(clippy::useless_transmute)]
// modules included with the postgres_ffi macro depend on the types of the specific version's
// types, and trigger a too eager lint.
#![allow(clippy::duplicate_mod)]
#![deny(clippy::undocumented_unsafe_blocks)]

use bytes::Bytes;
use utils::bin_ser::SerializeError;
use utils::lsn::Lsn;

pub use postgres_versioninfo::PgMajorVersion;

macro_rules! postgres_ffi {
    ($version:ident) => {
        #[path = "."]
        pub mod $version {
            pub mod bindings {
                // bindgen generates bindings for a lot of stuff we don't need
                #![allow(dead_code)]
                #![allow(unsafe_op_in_unsafe_fn)]
                #![allow(clippy::undocumented_unsafe_blocks)]
                #![allow(clippy::ptr_offset_with_cast)]

                use serde::{Deserialize, Serialize};
                include!(concat!(
                    env!("OUT_DIR"),
                    "/bindings_",
                    stringify!($version),
                    ".rs"
                ));

                include!(concat!("pg_constants_", stringify!($version), ".rs"));
            }
            pub mod controlfile_utils;
            pub mod nonrelfile_utils;
            pub mod wal_craft_test_export;
            pub mod wal_generator;
            pub mod waldecoder_handler;
            pub mod xlog_utils;

            pub const PG_MAJORVERSION: &str = stringify!($version);

            // Re-export some symbols from bindings
            pub use bindings::{CheckPoint, ControlFileData, DBState_DB_SHUTDOWNED, XLogRecord};

            pub const ZERO_CHECKPOINT: bytes::Bytes =
                bytes::Bytes::from_static(&[0u8; xlog_utils::SIZEOF_CHECKPOINT]);
        }
    };
}

#[macro_export]
macro_rules! for_all_postgres_versions {
    ($macro:tt) => {
        $macro!(v14);
        $macro!(v15);
        $macro!(v16);
        $macro!(v17);
        $macro!(v18);
    };
}

for_all_postgres_versions! { postgres_ffi }

/// dispatch_pgversion
///
/// Run a code block in a context where the postgres_ffi bindings for a
/// specific (supported) PostgreSQL version are `use`-ed in scope under the pgv
/// identifier.
/// If the provided pg_version is not supported, we panic!(), unless the
/// optional third argument was provided (in which case that code will provide
/// the default handling instead).
///
/// Use like
///
/// dispatch_pgversion!(my_pgversion, { pgv::constants::XLOG_DBASE_CREATE })
/// dispatch_pgversion!(my_pgversion, pgv::constants::XLOG_DBASE_CREATE)
///
/// Other uses are for macro-internal purposes only and strictly unsupported.
///
#[macro_export]
macro_rules! dispatch_pgversion {
    ($version:expr, $code:expr) => {
        dispatch_pgversion!($version, $code, panic!("Unknown PostgreSQL version {}", $version))
    };
    ($version:expr, $code:expr, $invalid_pgver_handling:expr) => {
        dispatch_pgversion!(
            $version => $code,
            default = $invalid_pgver_handling,
            pgversions = [
                $crate::PgMajorVersion::PG14 => v14,
                $crate::PgMajorVersion::PG15 => v15,
                $crate::PgMajorVersion::PG16 => v16,
                $crate::PgMajorVersion::PG17 => v17,
                $crate::PgMajorVersion::PG18 => v18,
            ]
        )
    };
    ($pgversion:expr => $code:expr,
     default = $default:expr,
     pgversions = [$($sv:pat => $vsv:ident),+ $(,)?]) => {
        match ($pgversion.clone().into()) {
            $($sv => {
                use $crate::$vsv as pgv;
                $code
            },)+
            #[allow(unreachable_patterns)]
            _ => {
                $default
            }
        }
    };
}

#[macro_export]
macro_rules! enum_pgversion_dispatch {
    ($name:expr, $typ:ident, $bind:ident, $code:block) => {
        enum_pgversion_dispatch!(
            name = $name,
            bind = $bind,
            typ = $typ,
            code = $code,
            pgversions = [
                V14 : v14,
                V15 : v15,
                V16 : v16,
                V17 : v17,
                V18 : v18,
            ]
        )
    };
    (name = $name:expr,
     bind = $bind:ident,
     typ = $typ:ident,
     code = $code:block,
     pgversions = [$($variant:ident : $md:ident),+ $(,)?]) => {
        match $name {
            $(
            self::$typ::$variant($bind) => {
                use $crate::$md as pgv;
                $code
            }
            ),+,
        }
    };
}

#[macro_export]
macro_rules! enum_pgversion {
    {$name:ident, pgv :: $t:ident} => {
        enum_pgversion!{
            name = $name,
            typ = $t,
            pgversions = [
                V14 : v14,
                V15 : v15,
                V16 : v16,
                V17 : v17,
                V18 : v18,
            ]
        }
    };
    {$name:ident, pgv :: $p:ident :: $t:ident} => {
        enum_pgversion!{
            name = $name,
            path = $p,
            typ = $t,
            pgversions = [
                V14 : v14,
                V15 : v15,
                V16 : v16,
                V17 : v17,
                V18 : v18,
            ]
        }
    };
    {name = $name:ident,
     typ = $t:ident,
     pgversions = [$($variant:ident : $md:ident),+ $(,)?]} => {
        pub enum $name {
            $($variant ( $crate::$md::$t )),+
        }
        impl self::$name {
            pub fn pg_version(&self) -> PgMajorVersion {
                enum_pgversion_dispatch!(self, $name, _ign, {
                    pgv::bindings::MY_PGVERSION
                })
            }
        }
        $(
        impl Into<self::$name> for $crate::$md::$t {
            fn into(self) -> self::$name {
                self::$name::$variant (self)
            }
        }
        )+
    };
    {name = $name:ident,
     path = $p:ident,
     $(typ = $t:ident,)?
     pgversions = [$($variant:ident : $md:ident),+ $(,)?]} => {
        pub enum $name {
            $($variant $(($crate::$md::$p::$t))?),+
        }
        impl $name {
            pub fn pg_version(&self) -> PgMajorVersion {
                enum_pgversion_dispatch!(self, $name, _ign, {
                    pgv::bindings::MY_PGVERSION
                })
            }
        }
        $(
        impl Into<$name> for $crate::$md::$p::$t {
            fn into(self) -> $name {
                $name::$variant (self)
            }
        }
        )+
    };
}

pub mod pg_constants;
pub mod relfile_utils;
pub mod walrecord;

// Export some widely used datatypes that are unlikely to change across Postgres versions
pub use v14::bindings::{
    BlockNumber, CheckPoint, ControlFileData, MultiXactId, OffsetNumber, Oid, PageHeaderData,
    RepOriginId, TimeLineID, TransactionId, XLogRecPtr, XLogRecord, XLogSegNo, uint32, uint64,
};
// Likewise for these, although the assumption that these don't change is a little more iffy.
pub use v14::bindings::{MultiXactOffset, MultiXactStatus};
pub use v14::xlog_utils::{
    XLOG_SIZE_OF_XLOG_LONG_PHD, XLOG_SIZE_OF_XLOG_RECORD, XLOG_SIZE_OF_XLOG_SHORT_PHD,
};

// from pg_config.h. These can be changed with configure options --with-blocksize=BLOCKSIZE and
// --with-segsize=SEGSIZE, but assume the defaults for now.
pub const BLCKSZ: u16 = 8192;
pub const RELSEG_SIZE: u32 = 1024 * 1024 * 1024 / (BLCKSZ as u32);
pub const XLOG_BLCKSZ: usize = 8192;
pub const WAL_SEGMENT_SIZE: usize = 16 * 1024 * 1024;

pub const MAX_SEND_SIZE: usize = XLOG_BLCKSZ * 16;

// Export some version independent functions that are used outside of this mod
pub use v14::bindings::DBState_DB_SHUTDOWNED;
pub use v14::xlog_utils::{
    XLogFileName, encode_logical_message, get_current_timestamp, to_pg_timestamp,
    try_from_pg_timestamp,
};

/// The major version whose WAL carries this `XLOG_PAGE_MAGIC`.
///
/// An unknown magic is an error: a page of a major we do not know is never
/// decoded with another major's layout (Loams-Patch LP-0040).
pub fn pg_major_version_from_page_magic(magic: u16) -> anyhow::Result<PgMajorVersion> {
    macro_rules! magic_of {
        ($version:ident) => {
            if magic == $version::bindings::XLOG_PAGE_MAGIC as u16 {
                return Ok($version::bindings::MY_PGVERSION);
            }
        };
    }
    for_all_postgres_versions! { magic_of }
    anyhow::bail!("unknown XLOG_PAGE_MAGIC {magic:#06X}")
}

pub fn bkpimage_is_compressed(bimg_info: u8, version: PgMajorVersion) -> bool {
    dispatch_pgversion!(version, pgv::bindings::bkpimg_is_compressed(bimg_info))
}

pub fn generate_wal_segment(
    segno: u64,
    system_id: u64,
    pg_version: PgMajorVersion,
    lsn: Lsn,
) -> Result<Bytes, SerializeError> {
    assert_eq!(segno, lsn.segment_number(WAL_SEGMENT_SIZE));

    dispatch_pgversion!(
        pg_version,
        pgv::xlog_utils::generate_wal_segment(segno, system_id, lsn)
    )
}

pub fn generate_pg_control(
    pg_control_bytes: &[u8],
    checkpoint_bytes: &[u8],
    lsn: Lsn,
    pg_version: PgMajorVersion,
) -> anyhow::Result<(Bytes, u64, bool)> {
    dispatch_pgversion!(
        pg_version,
        pgv::xlog_utils::generate_pg_control(pg_control_bytes, checkpoint_bytes, lsn),
        anyhow::bail!("Unknown version {}", pg_version)
    )
}

// PG timeline is always 1, changing it doesn't have any useful meaning in Neon.
//
// NOTE: this is not to be confused with Neon timelines; different concept!
//
// It's a shaky assumption, that it's always 1. We might import a
// PostgreSQL data directory that has gone through timeline bumps,
// for example. FIXME later.
pub const PG_TLI: u32 = 1;

//  See TransactionIdIsNormal in transam.h
pub const fn transaction_id_is_normal(id: TransactionId) -> bool {
    id > pg_constants::FIRST_NORMAL_TRANSACTION_ID
}

// See TransactionIdPrecedes in transam.c
pub const fn transaction_id_precedes(id1: TransactionId, id2: TransactionId) -> bool {
    /*
     * If either ID is a permanent XID then we can just do unsigned
     * comparison.  If both are normal, do a modulo-2^32 comparison.
     */

    if !(transaction_id_is_normal(id1)) || !transaction_id_is_normal(id2) {
        return id1 < id2;
    }

    let diff = id1.wrapping_sub(id2) as i32;
    diff < 0
}

// Check if page is not yet initialized (port of Postgres PageIsInit() macro)
pub fn page_is_new(pg: &[u8]) -> bool {
    pg[14] == 0 && pg[15] == 0 // pg_upper == 0
}

// ExtractLSN from page header
pub fn page_get_lsn(pg: &[u8]) -> Lsn {
    Lsn(
        ((u32::from_le_bytes(pg[0..4].try_into().unwrap()) as u64) << 32)
            | u32::from_le_bytes(pg[4..8].try_into().unwrap()) as u64,
    )
}

pub fn page_set_lsn(pg: &mut [u8], lsn: Lsn) {
    pg[0..4].copy_from_slice(&((lsn.0 >> 32) as u32).to_le_bytes());
    pg[4..8].copy_from_slice(&(lsn.0 as u32).to_le_bytes());
}

// This is port of function with the same name from freespace.c.
// The only difference is that it does not have "level" parameter because XLogRecordPageWithFreeSpace
// always call it with level=FSM_BOTTOM_LEVEL
pub fn fsm_logical_to_physical(addr: BlockNumber) -> BlockNumber {
    let mut leafno = addr;
    const FSM_TREE_DEPTH: u32 = if pg_constants::SLOTS_PER_FSM_PAGE >= 1626 {
        3
    } else {
        4
    };

    /* Count upper level nodes required to address the leaf page */
    let mut pages: BlockNumber = 0;
    for _l in 0..FSM_TREE_DEPTH {
        pages += leafno + 1;
        leafno /= pg_constants::SLOTS_PER_FSM_PAGE;
    }
    /* Turn the page count into 0-based block number */
    pages - 1
}

pub mod waldecoder {
    use std::num::NonZeroU32;

    use crate::PgMajorVersion;
    use bytes::{Buf, Bytes, BytesMut};
    use thiserror::Error;
    use utils::lsn::Lsn;

    pub enum State {
        WaitingForRecord,
        ReassemblingRecord {
            recordbuf: BytesMut,
            contlen: NonZeroU32,
        },
        SkippingEverything {
            skip_until_lsn: Lsn,
        },
    }

    pub struct WalStreamDecoder {
        pub lsn: Lsn,
        pub pg_version: PgMajorVersion,
        pub inputbuf: BytesMut,
        pub state: State,
    }

    #[derive(Error, Debug, Clone)]
    #[error("{msg} at {lsn}")]
    pub struct WalDecodeError {
        pub msg: String,
        pub lsn: Lsn,
    }

    impl WalStreamDecoder {
        pub fn new(lsn: Lsn, pg_version: PgMajorVersion) -> WalStreamDecoder {
            WalStreamDecoder {
                lsn,
                pg_version,
                inputbuf: BytesMut::new(),
                state: State::WaitingForRecord,
            }
        }

        // The latest LSN position fed to the decoder.
        pub fn available(&self) -> Lsn {
            self.lsn + self.inputbuf.remaining() as u64
        }

        /// Returns the LSN up to which the WAL decoder has processed.
        ///
        /// If [`Self::poll_decode`] returned a record, then this will return
        /// the end LSN of said record.
        pub fn lsn(&self) -> Lsn {
            self.lsn
        }

        pub fn feed_bytes(&mut self, buf: &[u8]) {
            self.inputbuf.extend_from_slice(buf);
        }

        pub fn poll_decode(&mut self) -> Result<Option<(Lsn, Bytes)>, WalDecodeError> {
            dispatch_pgversion!(
                self.pg_version,
                {
                    use pgv::waldecoder_handler::WalStreamDecoderHandler;
                    self.poll_decode_internal()
                },
                Err(WalDecodeError {
                    msg: format!("Unknown version {}", self.pg_version),
                    lsn: self.lsn,
                })
            )
        }
    }
}

/// The constants that `pg_constants_<version>.rs` copies by hand, as bindgen
/// reads them from that version's headers (`bindgen_consts.h`).
#[cfg(test)]
mod header_consts {
    macro_rules! header_consts {
        ($version:ident) => {
            pub mod $version {
                #![allow(dead_code)]
                include!(concat!(
                    env!("OUT_DIR"),
                    "/header_consts_",
                    stringify!($version),
                    ".rs"
                ));
            }
        };
    }
    for_all_postgres_versions! { header_consts }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Every constant in pg_constants_v18.rs that a header defines matches
    /// REL_18_6's headers, and the 18 layouts the decoder depends on have
    /// the sizes it assumes.
    #[test]
    fn pg_constants_v18_match_headers() {
        use header_consts::v18 as h;
        use v18::bindings as c;

        assert_eq!(c::XACT_XINFO_HAS_DROPPED_STATS, h::XACT_XINFO_HAS_DROPPED_STATS);
        assert_eq!(c::XLOG_DBASE_CREATE_FILE_COPY as u32, h::XLOG_DBASE_CREATE_FILE_COPY);
        assert_eq!(c::XLOG_DBASE_CREATE_WAL_LOG as u32, h::XLOG_DBASE_CREATE_WAL_LOG);
        assert_eq!(c::XLOG_DBASE_DROP as u32, h::XLOG_DBASE_DROP);
        assert_eq!(c::BKPIMAGE_APPLY as u32, h::BKPIMAGE_APPLY);
        assert_eq!(c::BKPIMAGE_COMPRESS_PGLZ as u32, h::BKPIMAGE_COMPRESS_PGLZ);
        assert_eq!(c::BKPIMAGE_COMPRESS_LZ4 as u32, h::BKPIMAGE_COMPRESS_LZ4);
        assert_eq!(c::BKPIMAGE_COMPRESS_ZSTD as u32, h::BKPIMAGE_COMPRESS_ZSTD);
        assert_eq!(c::XLOG_HEAP2_PRUNE_ON_ACCESS as u32, h::XLOG_HEAP2_PRUNE_ON_ACCESS);
        assert_eq!(c::XLOG_HEAP2_PRUNE_VACUUM_SCAN as u32, h::XLOG_HEAP2_PRUNE_VACUUM_SCAN);
        assert_eq!(
            c::XLOG_HEAP2_PRUNE_VACUUM_CLEANUP as u32,
            h::XLOG_HEAP2_PRUNE_VACUUM_CLEANUP
        );
        assert_eq!(c::XLOG_OVERWRITE_CONTRECORD as u32, h::XLOG_OVERWRITE_CONTRECORD);
        assert_eq!(c::XLOG_CHECKPOINT_REDO as u32, h::XLOG_CHECKPOINT_REDO);
        assert_eq!(
            c::SIZEOF_XL_XACT_STATS_ITEM,
            std::mem::size_of::<h::xl_xact_stats_item>()
        );

        // 18 adds SharedInvalRelSyncMsg to the union; it stays 16 bytes, so
        // the commit and standby records' invalidation arrays keep their
        // stride (format diff F25).
        assert_eq!(std::mem::size_of::<h::SharedInvalidationMessage>(), 16);

        // §62 §4.1's table, read from the headers.
        assert_eq!(c::XLOG_PAGE_MAGIC, 0xD118);
        assert_eq!(h::PG_CONTROL_VERSION, 1800);
        assert_eq!(h::CATALOG_VERSION_NO, 202506291);
        assert_eq!(c::PG_MAJORVERSION_NUM, 18);

        // 18's control file gained default_char_signedness (44fe30fdab).
        let control = c::ControlFileData::default();
        let _: bool = control.default_char_signedness;
        assert!(
            std::mem::size_of::<c::ControlFileData>() <= c::PG_CONTROL_FILE_SIZE as usize
        );
    }

    /// The same comparison at 17, which proves the method on a version whose
    /// constants are known good.
    #[test]
    fn pg_constants_v17_match_headers() {
        use header_consts::v17 as h;
        use v17::bindings as c;
        assert_eq!(c::XACT_XINFO_HAS_DROPPED_STATS, h::XACT_XINFO_HAS_DROPPED_STATS);
        assert_eq!(c::XLOG_CHECKPOINT_REDO as u32, h::XLOG_CHECKPOINT_REDO);
        assert_eq!(c::XLOG_PAGE_MAGIC, 0xD116);
        assert_eq!(h::PG_CONTROL_VERSION, 1700);
        assert_eq!(std::mem::size_of::<h::xl_xact_stats_item>(), 12);
    }

    #[test]
    fn xlog_page_magic_v18() {
        assert_eq!(v18::bindings::XLOG_PAGE_MAGIC, 0xD118);
        assert_eq!(
            pg_major_version_from_page_magic(0xD118).unwrap(),
            PgMajorVersion::PG18
        );
        // Every supported major maps to itself, and the magics are distinct.
        for v in PgMajorVersion::ALL {
            let magic = dispatch_pgversion!(v, pgv::bindings::XLOG_PAGE_MAGIC as u16);
            assert_eq!(pg_major_version_from_page_magic(magic).unwrap(), *v);
        }

        // A segment generated at 18 carries 18's magic and decodes at 18.
        let lsn = utils::lsn::Lsn(0x0100_0000);
        let seg = generate_wal_segment(1, 42, PgMajorVersion::PG18, lsn).unwrap();
        assert_eq!(u16::from_le_bytes([seg[0], seg[1]]), 0xD118);
        let mut decoder = waldecoder::WalStreamDecoder::new(lsn, PgMajorVersion::PG18);
        decoder.feed_bytes(&seg[..XLOG_BLCKSZ]);
        decoder.poll_decode().unwrap();
    }

    #[test]
    fn unknown_page_magic_is_error() {
        // 19's magic (§62 §4.1), a magic between majors, and garbage.
        for magic in [0xD122u16, 0xD117, 0xD119, 0x0000, 0xFFFF] {
            let err = pg_major_version_from_page_magic(magic).unwrap_err();
            assert!(err.to_string().contains("unknown XLOG_PAGE_MAGIC"), "{err}");
        }

        // A 17 page fed to an 18 decoder, and an 18 page to a 17 decoder, are
        // errors: never decoded with the other major's layout.
        let lsn = utils::lsn::Lsn(0x0100_0000);
        for (written, read) in [
            (PgMajorVersion::PG17, PgMajorVersion::PG18),
            (PgMajorVersion::PG18, PgMajorVersion::PG17),
        ] {
            let seg = generate_wal_segment(1, 42, written, lsn).unwrap();
            let mut decoder = waldecoder::WalStreamDecoder::new(lsn, read);
            decoder.feed_bytes(&seg[..XLOG_BLCKSZ]);
            let err = decoder.poll_decode().unwrap_err();
            assert!(err.msg.contains("xlp_magic"), "{}", err.msg);
        }
    }
}
