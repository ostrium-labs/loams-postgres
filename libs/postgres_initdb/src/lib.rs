//! The canonical way we run `initdb` in Neon.
//!
//! initdb has implicit defaults that are dependent on the environment, e.g., locales & collations.
//!
//! This module's job is to eliminate the environment-dependence as much as possible.

use std::fmt;

use camino::Utf8Path;
use postgres_versioninfo::PgMajorVersion;

pub struct RunInitdbArgs<'a> {
    pub superuser: &'a str,
    pub locale: &'a str,
    pub initdb_bin: &'a Utf8Path,
    pub pg_version: PgMajorVersion,
    pub library_search_path: &'a Utf8Path,
    pub pgdata: &'a Utf8Path,
}

#[derive(thiserror::Error, Debug)]
pub enum Error {
    Spawn(std::io::Error),
    Failed {
        status: std::process::ExitStatus,
        stderr: Vec<u8>,
    },
    WaitOutput(std::io::Error),
    Other(anyhow::Error),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            Error::Spawn(e) => write!(f, "Error spawning command: {e:?}"),
            Error::Failed { status, stderr } => write!(
                f,
                "Command failed with status {:?}: {}",
                status,
                String::from_utf8_lossy(stderr)
            ),
            Error::WaitOutput(e) => write!(f, "Error waiting for command output: {e:?}"),
            Error::Other(e) => write!(f, "Error: {e:?}"),
        }
    }
}

/// initdb's arguments for a major.
///
/// From 18 on, initdb turns data checksums on by default. Nothing in Loams
/// Postgres sets page checksums (WAL redo, image layers, basebackup), so a
/// timeline bootstrapped with them on would fail verification in the compute:
/// pass `--no-data-checksums` (D1111, Loams-Patch LP-0041). 14 to 17 default
/// to off and do not know the flag.
pub fn initdb_args(
    superuser: &str,
    locale: &str,
    pg_version: PgMajorVersion,
    pgdata: &Utf8Path,
) -> Vec<String> {
    let mut args: Vec<String> = [
        "--pgdata",
        pgdata.as_str(),
        "--username",
        superuser,
        "--encoding",
        "utf8",
        "--locale",
        locale,
        "--no-instructions",
        "--no-sync",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();

    // Before version 14, only the libc provide was available.
    if pg_version > PgMajorVersion::PG14 {
        // Version 17 brought with it a builtin locale provider which only provides
        // C and C.UTF-8. While being safer for collation purposes since it is
        // guaranteed to be consistent throughout a major release, it is also more
        // performant.
        let locale_provider = if pg_version >= PgMajorVersion::PG17 {
            "builtin"
        } else {
            "libc"
        };
        args.extend(["--locale-provider".to_string(), locale_provider.to_string()]);
    }

    if pg_version >= PgMajorVersion::PG18 {
        args.push("--no-data-checksums".to_string());
    }
    args
}

pub async fn do_run_initdb(args: RunInitdbArgs<'_>) -> Result<(), Error> {
    let RunInitdbArgs {
        superuser,
        locale,
        initdb_bin: initdb_bin_path,
        pg_version,
        library_search_path,
        pgdata,
    } = args;
    let mut initdb_command = tokio::process::Command::new(initdb_bin_path);
    initdb_command
        .args(initdb_args(superuser, locale, pg_version, pgdata))
        .env_clear()
        .env("LD_LIBRARY_PATH", library_search_path)
        .env("DYLD_LIBRARY_PATH", library_search_path)
        .env(
            "ASAN_OPTIONS",
            std::env::var("ASAN_OPTIONS").unwrap_or_default(),
        )
        .env(
            "UBSAN_OPTIONS",
            std::env::var("UBSAN_OPTIONS").unwrap_or_default(),
        )
        .stdin(std::process::Stdio::null())
        // stdout invocation produces the same output every time, we don't need it
        .stdout(std::process::Stdio::null())
        // we would be interested in the stderr output, if there was any
        .stderr(std::process::Stdio::piped());

    let initdb_proc = initdb_command.spawn().map_err(Error::Spawn)?;

    // Ideally we'd select here with the cancellation token, but the problem is that
    // we can't safely terminate initdb: it launches processes of its own, and killing
    // initdb doesn't kill them. After we return from this function, we want the target
    // directory to be able to be cleaned up.
    // See https://github.com/neondatabase/neon/issues/6385
    let initdb_output = initdb_proc
        .wait_with_output()
        .await
        .map_err(Error::WaitOutput)?;
    if !initdb_output.status.success() {
        return Err(Error::Failed {
            status: initdb_output.status,
            stderr: initdb_output.stderr,
        });
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A timeline bootstrapped at 18 has data checksums off (D1111); 14 to
    /// 17 are not given a flag they do not know.
    #[test]
    fn bootstrap_pg18_checksums_off() {
        let pgdata = Utf8Path::new("/pgdata");
        let at = |v| initdb_args("cloud_admin", "C.UTF-8", v, pgdata);

        let args18 = at(PgMajorVersion::PG18);
        assert!(args18.iter().any(|a| a == "--no-data-checksums"), "{args18:?}");
        for v in PgMajorVersion::ALL {
            let args = at(*v);
            assert!(
                !args.iter().any(|a| a == "--data-checksums" || a == "-k"),
                "{v}: {args:?}"
            );
            assert_eq!(
                args.iter().any(|a| a == "--no-data-checksums"),
                *v >= PgMajorVersion::PG18,
                "{v}: {args:?}"
            );
        }
        // The rest is unchanged from 17.
        let args17 = at(PgMajorVersion::PG17);
        assert_eq!(&args18[..args17.len()], &args17[..]);
    }
}
