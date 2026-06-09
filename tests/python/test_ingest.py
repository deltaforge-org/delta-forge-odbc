#!/usr/bin/env python3
"""
End-to-end bulk Arrow ingest test for the DeltaForge ODBC driver.

The ODBC v1 surface uses the INGEST pragma against a pre-written
Parquet file (Power BI bulk-write via SQLBulkOperations is a v1.5
follow-up). Each test writes a temp Parquet file, then executes:

    INGEST INTO <table> MODE='<mode>' FROM PARQUET FILE='<path>'

via pyodbc's cursor.execute(), and verifies the row count via
cursor.rowcount + SELECT COUNT(*).

Requires:
    - pyodbc + the DeltaForge ODBC driver installed (DSN configured)
    - A reachable control plane + compute node
    - DELTAFORGE_ODBC_DSN env var pointing at the DSN
    - The target tables already exist; this script does not CREATE them.

Skips (exit 77) when the connection fails so CI builds without a backend
stay clean.
"""

import os
import sys
import tempfile
import uuid

# Import pyarrow FIRST so its bundled libarrow + libparquet are loaded by
# the dynamic linker before the ODBC driver pulls in the system libarrow.
# pyodbc -> the DeltaForge ODBC driver -> system libarrow.so. If pyarrow
# loads after pyodbc, its libparquet.so resolves Arrow symbols against the
# system libarrow (different version) and dies with an "undefined symbol"
# ImportError. Loading pyarrow first lets its libarrow win in the loader
# cache and the ODBC driver then shares pyarrow's libarrow.
try:
    import pyarrow as _pa_preload  # noqa: F401
    import pyarrow.parquet as _pq_preload  # noqa: F401
except ImportError:
    # Surface the underlying ABI error in the per-test check.
    pass


def _check_env():
    dsn = os.environ.get("DELTAFORGE_ODBC_DSN", "DeltaForge")
    target = os.environ.get("DELTAFORGE_INGEST_TARGET", "test.bulk_ingest.smoke_odbc")
    location = os.environ.get(
        "DELTAFORGE_INGEST_LAND_LOCATION", "file:///tmp/df_ingest_land_odbc"
    )
    return dsn, target, location


def _connect(dsn):
    try:
        import pyodbc
    except ImportError:
        print("SKIP: pyodbc not installed (pip install pyodbc)")
        sys.exit(77)
    try:
        return pyodbc.connect(f"DSN={dsn}", autocommit=True)
    except Exception as e:
        print(f"SKIP: cannot connect to DSN={dsn}: {e}")
        sys.exit(77)


def _to_server_path(local_path):
    """The INGEST pragma reads the file CLIENT-side (driver opens it via
    std::ifstream, ships the bytes inline through the wire). The server
    never sees the path. So the path in the SQL is always the client's
    local path. This helper used to translate WSL -> Windows for a
    different deployment shape; today it's an identity passthrough."""
    return local_path


def _write_parquet(start, rows):
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as ie:
        print(f"SKIP: pyarrow not installed (pip install pyarrow): {ie}")
        sys.exit(77)
    batch = pa.RecordBatch.from_pydict(
        {
            "id": pa.array([start + i for i in range(rows)], type=pa.int64()),
            "region": pa.array(
                [["us-east", "us-west", "eu-central"][i % 3] for i in range(rows)]
            ),
            "qty": pa.array(
                [(start + i) * 10 for i in range(rows)], type=pa.int32()
            ),
        }
    )
    table = pa.Table.from_batches([batch])
    # The INGEST pragma sends the file path verbatim to the server. When
    # the driver runs on a different OS than the server (e.g. WSL driver +
    # Windows server) the path must live on a filesystem both sides can
    # reach. `DELTAFORGE_INGEST_SCRATCH_DIR` lets the caller override the
    # default `/tmp`; when set to a /mnt/c/... path under WSL, the Windows
    # server reads back through its native `C:/...` mount.
    scratch_dir = os.environ.get("DELTAFORGE_INGEST_SCRATCH_DIR", tempfile.gettempdir())
    os.makedirs(scratch_dir, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="df_ingest_", suffix=".parquet", dir=scratch_dir)
    os.close(fd)
    pq.write_table(table, path)
    # Tests use the returned path BOTH for `os.remove(...)` (local view)
    # AND inside the INGEST pragma string (server view). We bind both onto
    # a small wrapper so a single `str(path)` expansion in the f-string
    # automatically gets the server-side view while os.remove(path) keeps
    # working through the __fspath__ protocol.
    return _IngestPath(local=path, server=_to_server_path(path))


class _IngestPath:
    """Pair of a local file path and its server-visible translation. Acts
    as the local path for os.remove / open / etc. (via __fspath__) and as
    the server path for any string formatting (via __str__)."""
    __slots__ = ("local", "server")

    def __init__(self, local, server):
        self.local = local
        self.server = server

    def __str__(self):
        return self.server

    def __fspath__(self):
        return self.local


def _count_rows(conn, table):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def test_append_via_pragma():
    dsn, target, _location = _check_env()
    conn = _connect(dsn)
    try:
        before = _count_rows(conn, target)
        path = _write_parquet(0, 150)
        try:
            cur = conn.cursor()
            cur.execute(f"INGEST INTO {target} MODE='append' FROM PARQUET FILE='{path}'")
            assert cur.rowcount == 150, f"rowcount {cur.rowcount} != 150"
            after = _count_rows(conn, target)
            assert after - before == 150
        finally:
            os.remove(path)
    finally:
        conn.close()


def test_overwrite_via_pragma():
    dsn, target, _location = _check_env()
    overwrite_target = os.environ.get(
        "DELTAFORGE_INGEST_OVERWRITE_TARGET", target + "_overwrite"
    )
    conn = _connect(dsn)
    try:
        seed_path = _write_parquet(0, 20)
        replace_path = _write_parquet(2_000, 5)
        try:
            cur = conn.cursor()
            cur.execute(
                f"INGEST INTO {overwrite_target} MODE='append' FROM PARQUET FILE='{seed_path}'"
            )
            cur.execute(
                f"INGEST INTO {overwrite_target} MODE='overwrite' FROM PARQUET FILE='{replace_path}'"
            )
            assert _count_rows(conn, overwrite_target) == 5
        finally:
            os.remove(seed_path)
            os.remove(replace_path)
    finally:
        conn.close()


def test_land_via_pragma():
    dsn, _target, location = _check_env()
    conn = _connect(dsn)
    try:
        path = _write_parquet(0, 12)
        try:
            cur = conn.cursor()
            cur.execute(
                f"INGEST INTO LOCATION '{location}' MODE='land' "
                f"FROM PARQUET FILE='{path}'"
            )
            assert cur.rowcount == 12
        finally:
            os.remove(path)
    finally:
        conn.close()


def test_idempotency_replay():
    dsn, target, _location = _check_env()
    conn = _connect(dsn)
    try:
        key = f"odbc-idem-{uuid.uuid4()}"
        path = _write_parquet(70_000, 8)
        try:
            before = _count_rows(conn, target)
            cur = conn.cursor()
            for _ in range(2):
                cur.execute(
                    f"INGEST INTO {target} MODE='append' "
                    f"IDEMPOTENCY_KEY='{key}' FROM PARQUET FILE='{path}'"
                )
                assert cur.rowcount == 8
            after = _count_rows(conn, target)
            assert after - before == 8, (
                f"replay must not double-commit: delta {after - before} != 8"
            )
        finally:
            os.remove(path)
    finally:
        conn.close()


def test_pragma_missing_mode_returns_42000():
    dsn, target, _location = _check_env()
    conn = _connect(dsn)
    try:
        path = _write_parquet(0, 1)
        try:
            import pyodbc
            try:
                cur = conn.cursor()
                cur.execute(f"INGEST INTO {target} FROM PARQUET FILE='{path}'")
                assert False, "must reject INGEST without MODE='...'"
            except pyodbc.Error as e:
                assert "42000" in str(e) or "MODE" in str(e), (
                    f"expected 42000 or MODE in error: {e}"
                )
        finally:
            os.remove(path)
    finally:
        conn.close()


if __name__ == "__main__":
    tests = [
        test_append_via_pragma,
        test_overwrite_via_pragma,
        test_land_via_pragma,
        test_idempotency_replay,
        test_pragma_missing_mode_returns_42000,
    ]
    failures = 0
    for t in tests:
        try:
            print(f"--- {t.__name__}")
            t()
            print("    PASS")
        except SystemExit as e:
            if e.code == 77:
                raise
            failures += 1
            print(f"    FAIL: {e}")
        except Exception as e:
            failures += 1
            print(f"    FAIL: {e}")
    if failures:
        sys.exit(1)
    print("ALL PASS")
