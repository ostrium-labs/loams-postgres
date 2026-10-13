## Benchmarks

To run benchmarks:

```sh
# All benchmarks.
cargo bench --package postgres_ffi

# Specific file.
cargo bench --package postgres_ffi --bench waldecoder

# Specific benchmark.
cargo bench --package postgres_ffi --bench waldecoder complete_record/size=1024

# List available benchmarks.
cargo bench --package postgres_ffi --benches -- --list

# Generate CPU profiles using pprof-rs, profiling for 10 seconds.
# Output in target/criterion/*/profile/profile.pb (pprof format, e.g. `go tool pprof -http :8080`).
# Loams Postgres builds pprof without its flamegraph renderer (inferno is CDDL-1.0, LP-0003).
cargo bench --package postgres_ffi --bench waldecoder complete_record/size=1024 -- --profile-time 10
```

Additional charts and statistics are available in `target/criterion/report/index.html`.

Benchmarks are automatically compared against the previous run. To compare against other runs, see
`--baseline` and `--save-baseline`.