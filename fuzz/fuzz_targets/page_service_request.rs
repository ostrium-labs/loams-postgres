//! One page-service request, as the pageserver parses it from a compute
//! (`PagestreamFeMessage::parse`). The compute runs tenant code, so the
//! request is untrusted.
//!
//! The first byte picks the protocol version (V2 or V3); the rest is the message.
#![no_main]

use libfuzzer_sys::fuzz_target;
use pageserver_api::pagestream_api::{PagestreamFeMessage, PagestreamProtocolVersion};

fuzz_target!(|data: &[u8]| {
    let Some((&selector, mut body)) = data.split_first() else {
        return;
    };
    let version = if selector & 1 == 0 {
        PagestreamProtocolVersion::V2
    } else {
        PagestreamProtocolVersion::V3
    };
    let _ = PagestreamFeMessage::parse(&mut body, version);
});
