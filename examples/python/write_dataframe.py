#!/usr/bin/env python3
"""Write a pandas DataFrame into a Delta table with the DeltaForge ODBC driver.

ODBC writes go through DeltaForge's bulk INGEST path: the DataFrame is written
to a Parquet file, then ingested in one statement. This is far faster than
row-by-row INSERT and is the supported bulk-write path for the ODBC driver. For
Arrow-native, in-memory writes (no temp file), use the ADBC driver instead.

Prerequisites:
    - DeltaForge ODBC driver installed and registered (DSN "DeltaForge").
    - pip install pyodbc pyarrow pandas

Environment:
    DELTAFORGE_DSN              ODBC DSN name (default: DeltaForge)
    DELTAFORGE_UID             user / email
    DELTAFORGE_PWD             password or token
    DELTAFORGE_INGEST_TARGET   target table (must already exist)

Usage:
    python write_dataframe.py            # appends a small sample frame
    python write_dataframe.py overwrite  # overwrites instead of appending
"""

import os
import sys
import tempfile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyodbc


def connect():
    dsn = os.environ.get("DELTAFORGE_DSN", "DeltaForge")
    uid = os.environ.get("DELTAFORGE_UID", "")
    pwd = os.environ.get("DELTAFORGE_PWD", "")
    return pyodbc.connect(f"DSN={dsn};Uid={uid};Pwd={pwd}")


def write_dataframe(conn, table: str, frame: pd.DataFrame, mode: str = "append") -> None:
    """Write `frame` into `table` via a temporary Parquet file + INGEST."""
    if mode not in {"append", "overwrite"}:
        raise ValueError("ODBC INGEST supports mode 'append' or 'overwrite'")
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        path = tmp.name
    try:
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path)
        # Forward slashes are accepted on all platforms by the engine.
        uri = path.replace("\\", "/")
        conn.cursor().execute(
            f"INGEST INTO {table} MODE='{mode}' FROM PARQUET FILE='{uri}'"
        )
        conn.commit()
    finally:
        os.unlink(path)


def _count(conn, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "append"
    target = os.environ.get("DELTAFORGE_INGEST_TARGET")
    if not target:
        print("set DELTAFORGE_INGEST_TARGET to a fully qualified existing table")
        return 2

    frame = pd.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "region": ["us-east", "us-west", "eu-central", "us-east"],
            "qty": [10, 20, 30, 40],
        }
    )

    conn = connect()
    try:
        before = _count(conn, target)
        write_dataframe(conn, target, frame, mode=mode)
        after = _count(conn, target)
        print(f"{target}: {before} -> {after} rows (mode={mode})")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
