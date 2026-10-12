//! The first packet a client sends the proxy (SSLRequest, GSSENCRequest,
//! CancelRequest or StartupMessage with its parameters), from the internet,
//! before any authentication.
#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    proxy::fuzzing::startup(data);
});
