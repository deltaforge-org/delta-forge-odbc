# DeltaForge ODBC: client tests

Public-facing tests you can run against an **installed DeltaForge ODBC driver**.
They drive the driver through the public ODBC API (pyodbc, .NET
`System.Data.Odbc`), exactly as your own application would, and verify
read/write behavior end to end. Each test skips cleanly (exit 77) when it cannot
connect, so they are safe to run in CI without a backend.

These tests exercise the shipped binary. They do not contain or require the
driver's source.

## Prerequisites

- DeltaForge ODBC driver installed and registered as a DSN (default name
  `DeltaForge`). See the driver README.
- A reachable DeltaForge control plane + compute node, and the target tables
  already created.

## Python (pyodbc)

```bash
pip install pyodbc pyarrow
export DELTAFORGE_ODBC_DSN=DeltaForge
export DELTAFORGE_INGEST_TARGET=your.schema.table   # must already exist
python tests/python/test_ingest.py
```

Covers append, overwrite, land, idempotent replay, and error-code handling
through the `INGEST` pragma.

## .NET (System.Data.Odbc)

```bash
export DELTAFORGE_ODBC_DSN=DeltaForge
export DELTAFORGE_INGEST_TARGET=your.schema.table
dotnet run --project tests/dotnet
```

## Exit codes

`0` all passed, `1` one or more failed, `77` skipped (could not connect).
