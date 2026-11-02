# Licensing

This repository is Ostrium Labs' fork of
[`neondatabase/tokio-epoll-uring`](https://github.com/neondatabase/tokio-epoll-uring),
kept for Loams Postgres (`ostrium-labs/loams-postgres`, patch LP-0007).

Upstream published no licence file. Its authors declared the licences in the
crates' manifests, and this fork adds the texts those declarations name, so
that the notices travel with the code. No licence was chosen or changed here.

## What the manifests declare

At upstream's `781989bb540a1408b0b93daa1e9d1fa452195497` (the revision Neon's
pageserver pinned) and at upstream `main`:

- `tokio-epoll-uring/Cargo.toml`: `license = "MIT OR Apache-2.0"`.
- `uring-common/Cargo.toml`: `license = "MIT" # the same as tokio-uring at the time we forked it`.

## Which text covers what

| Code | Licence | Text |
|---|---|---|
| `tokio-epoll-uring/` and the rest of the repository, written by the tokio-epoll-uring authors (Neon Inc.) | MIT OR Apache-2.0, at your option | `LICENSE-MIT`, `LICENSE-APACHE` |
| `uring-common/`, files written by the tokio-epoll-uring authors (`src/lib.rs`, `src/io_fd.rs`, `src/open_options_io_uring_ext.rs`) | MIT | `LICENSE-MIT` |
| `uring-common/`, files vendored from [`tokio-uring`](https://github.com/tokio-rs/tokio-uring) (`src/buf.rs`, `src/buf/*.rs`, `src/open_options.rs`; each starts with `tokio-uring`'s notice) | MIT, Copyright (c) 2021 Carl Lerche | `uring-common/LICENSE-tokio-uring` |

## Where the vendored code comes from

- Upstream PR #24, commit `91d67e20fe5224eb8b7b99c4e84543b033a43a65`
  ("vendor `IoBuf`/`IoBufMut` from `tokio-uring`"), copied the `buf` module
  from `tokio-uring.git` at `d5e90539bd6d1c518e848298564a098c300866bc`. Its
  message says: "The files that reproduce the `tokio-uring` LICENSE text at the
  top are copied from `tokio-uring.git:d5e90539…`. Files without it were
  written by myself."
- Upstream PR #25, commit `53c832d322`, vendored `OpenOptions` from the same
  `tokio-uring` revision (`src/open_options.rs`) and added
  `src/open_options_io_uring_ext.rs`.
- `uring-common/LICENSE-tokio-uring` is `tokio-uring`'s `LICENSE` at
  `d5e90539bd6d1c518e848298564a098c300866bc`, unchanged.

## The texts

- `LICENSE-APACHE` is the Apache License, Version 2.0, from
  https://www.apache.org/licenses/LICENSE-2.0.txt (sha256
  `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`).
- `LICENSE-MIT` is the MIT licence with the copyright line
  "the tokio-epoll-uring authors (Neon Inc.)".
