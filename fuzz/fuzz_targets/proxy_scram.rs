//! The proxy's SASL and SCRAM parsers of client messages, before the client
//! is authenticated.
//!
//! The first byte picks the parser: the SASLInitialResponse payload, SCRAM's
//! client-first-message or its client-final-message; the rest is the input.
#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let Some((&selector, input)) = data.split_first() else {
        return;
    };
    match selector % 3 {
        0 => proxy::fuzzing::sasl_first_message(input),
        parser => {
            let Ok(text) = std::str::from_utf8(input) else {
                return;
            };
            if parser == 1 {
                proxy::fuzzing::scram_client_first(text);
            } else {
                proxy::fuzzing::scram_client_final(text);
            }
        }
    }
});
