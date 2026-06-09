# DeltaForge ODBC: Python examples

Read and write Delta tables from Python through the DeltaForge ODBC driver.

DeltaForge is commercial software with a free Community license. See
[deltaforge.org/pricing](https://deltaforge.org/pricing).

## Prerequisites

- DeltaForge ODBC driver installed and registered (a DSN named `DeltaForge`).
  See the driver README / `docs/QUICKSTART.md`.
- `pip install pyodbc pyarrow pandas`

## Configure

```bash
export DELTAFORGE_DSN=DeltaForge
export DELTAFORGE_UID=you@example.com
export DELTAFORGE_PWD='your-password-or-token'
export DELTAFORGE_INGEST_TARGET=sales.public.orders   # for the write example
```

## Read

```bash
python read.py "SELECT * FROM sales.public.orders LIMIT 100"
```

## Write a DataFrame

```bash
python write_dataframe.py            # append a sample frame
python write_dataframe.py overwrite  # overwrite instead
```

ODBC writes go through DeltaForge's bulk `INGEST` path (DataFrame to Parquet,
then a single ingest statement), which is the supported bulk-write path for the
ODBC driver. For Arrow-native in-memory writes with no temp file, plus `upsert`,
use the **ADBC driver** (`pip install deltaforge-adbc`).
