# `tokio-epoll-uring`'s licence

The pageserver's default I/O engine (`TokioEpollUring`, on Linux) comes from
`tokio-epoll-uring`, and its `IoBuf` traits (crate `uring-common`) are used
across `pageserver/src/virtual_file/owned_buffers_io`. Loams Postgres builds
both from our fork, `ostrium-labs/tokio-epoll-uring`, branch `loams/main`,
pinned by rev in the workspace `Cargo.toml` (LP-0005) at a commit tagged
`loams-<date>-<n>`.

## The finding (design §51 §11, D817)

Upstream (`neondatabase/tokio-epoll-uring`) published no licence file, and
GitHub reports no licence for it. Its manifests declare the terms:

- `tokio-epoll-uring/Cargo.toml`: `license = "MIT OR Apache-2.0"`;
- `uring-common/Cargo.toml`: `license = "MIT" # the same as tokio-uring at the time we forked it`.

That is true at `781989bb540a1408b0b93daa1e9d1fa452195497` (the revision
Neon's pageserver pinned) and at upstream `main`. The code is licensed by its
authors' declaration; what was missing are the licence texts and the
copyright notices that MIT and Apache-2.0 expect to travel with it.

## The resolution (LP-0007)

`ostrium-labs/tokio-epoll-uring` (PR #2 into `loams/main`) adds, without
changing any licence or code:

| File | Covers |
|---|---|
| `LICENSE-MIT`, `LICENSE-APACHE` | `tokio-epoll-uring` (MIT OR Apache-2.0) and the files of `uring-common` its authors wrote (MIT), attributed to "the tokio-epoll-uring authors (Neon Inc.)" |
| `uring-common/LICENSE-tokio-uring` | `uring-common`'s `buf` module and `open_options.rs`, vendored from `tokio-uring` at `d5e90539bd6d1c518e848298564a098c300866bc` in upstream PRs #24 (`91d67e20`) and #25 (`53c832d3`): MIT, Copyright (c) 2021 Carl Lerche |
| `LICENSING.md` | which text covers which file, with the manifest lines and the upstream commits |

The pin moved from `781989bb` to the commit with the texts. That also brings
in upstream's last five commits (`7adcb121` … `478ab1a3`, upstream PR #76,
2026-09-17 to 09-21), which close the file descriptor that an `open` future
leaked when it was cancelled after the kernel had completed it. They touch
only `tokio-epoll-uring/src/{ops/open_at.rs,system/slots.rs,system/submission/op_fut.rs,system/tests.rs}`.

The image's third-party licence file (`THIRD_PARTY_LICENSES.html`, from
`cargo about`, NF1 Task 10) and the SBOM then carry the texts.

## Still open

- **Q716:** whether to ask upstream, once, to add licence files that match its
  manifests. That would be an exception to "nothing is posted upstream"
  (D231), so it waits for the owner. No issue has been filed.
- **Fallback, only if counsel finds the declaration insufficient:** a
  pageserver feature `io-uring` (on by default). With it off, the
  `TokioEpollUring` engine is compiled out and `uring-common`'s traits are
  vendored into the pageserver with `tokio-uring`'s MIT notice; that build
  uses `StdFs`. Not started (estimate 1–2 engineer-weeks, branch
  `loams/nf1-no-uring`).
