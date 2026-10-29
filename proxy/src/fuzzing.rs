//! Entry points for the fuzz targets in `fuzz/` (Loams Postgres, LP-0008).
//!
//! Built only with the `fuzzing` feature, which nothing but the fuzz crate
//! enables. Each function runs one of the proxy's parsers of client input
//! on arbitrary bytes and drops the result: the fuzzer looks for panics,
//! hangs and memory errors, not for particular answers.

use std::future::Future;
use std::hint::black_box;
use std::pin::pin;
use std::task::{Context, Poll, Waker};

use crate::pqproto::{FeStartupPacket, read_startup};
use crate::sasl::FirstMessage;
use crate::scram::{ClientFinalMessage, ClientFirstMessage};

/// The first packet of a connection: SSLRequest, GSSENCRequest,
/// CancelRequest or StartupMessage (and its parameters), as
/// `read_startup` reads it from a client.
pub fn startup(data: &[u8]) {
    let mut stream = data;
    let read = pin!(read_startup(&mut stream));
    let mut cx = Context::from_waker(Waker::noop());
    match read.poll(&mut cx) {
        Poll::Ready(Ok(FeStartupPacket::StartupMessage { params, .. })) => {
            for pair in params.iter() {
                black_box(pair);
            }
            if let Some(options) = params.options_raw() {
                for option in options {
                    black_box(option);
                }
            }
        }
        Poll::Ready(packet) => {
            black_box(packet.is_ok());
        }
        Poll::Pending => unreachable!("reading from a byte slice never waits"),
    }
}

/// The SASLInitialResponse payload: mechanism name and initial message.
pub fn sasl_first_message(data: &[u8]) {
    black_box(FirstMessage::parse(data).map(|m| (m.method, m.message)));
}

/// SCRAM's client-first-message.
pub fn scram_client_first(input: &str) {
    black_box(ClientFirstMessage::parse(input).map(|m| (m.bare, m.nonce)));
}

/// SCRAM's client-final-message.
pub fn scram_client_final(input: &str) {
    black_box(ClientFinalMessage::parse(input).map(|m| (m.without_proof, m.nonce, m.proof)));
}
