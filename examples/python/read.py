#!/usr/bin/env python3
"""Read from a Delta table with the DeltaForge ODBC driver (pyodbc).

Prerequisites:
    - DeltaForge ODBC driver installed and registered (a DSN named "DeltaForge",
      or pass a full connection string).
    - pip install pyodbc

Environment:
    DELTAFORGE_DSN    ODBC DSN name (default: DeltaForge)
    DELTAFORGE_UID    user / email
    DELTAFORGE_PWD    password or token

Usage:
    python read.py "SELECT * FROM sales.public.orders LIMIT 100"
"""

import os
import sys

import pyodbc


def connect():
    dsn = os.environ.get("DELTAFORGE_DSN", "DeltaForge")
    uid = os.environ.get("DELTAFORGE_UID", "")
    pwd = os.environ.get("DELTAFORGE_PWD", "")
    return pyodbc.connect(f"DSN={dsn};Uid={uid};Pwd={pwd}")


def main() -> int:
    sql = sys.argv[1] if len(sys.argv) > 1 else "SELECT 1 AS one"
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        print(" | ".join(cols))
        for row in cur.fetchmany(20):
            print(" | ".join(str(v) for v in row))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
