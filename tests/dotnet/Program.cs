// Program.cs
//
// .NET ODBC end-to-end test for the DeltaForge bulk Arrow ingest endpoint.
// Drives the INGEST pragma via System.Data.Odbc on a temp Parquet file.
//
// Run:
//   dotnet run --project delta-forge-odbc/tests/dotnet/TestIngest
//
// Env vars:
//   DELTAFORGE_ODBC_DSN     ODBC DSN (default: "DeltaForge")
//   DELTAFORGE_INGEST_TARGET  qualified target table (default: "test.bulk_ingest.smoke_dotnet")
//
// Exit codes:
//   0   all PASS
//   1   one or more failures
//   77  SKIP (cannot connect to DSN)
//

using System;
using System.Data;
using System.Data.Odbc;
using System.IO;
using System.Threading.Tasks;
using Parquet;
using Parquet.Data;
using Parquet.Schema;

internal static class Program
{
    private static string Dsn() =>
        Environment.GetEnvironmentVariable("DELTAFORGE_ODBC_DSN") ?? "DeltaForge";
    private static string TargetTable() =>
        Environment.GetEnvironmentVariable("DELTAFORGE_INGEST_TARGET")
            ?? "test.bulk_ingest.smoke_dotnet";

    public static async Task<int> Main()
    {
        OdbcConnection conn;
        try
        {
            conn = new OdbcConnection($"DSN={Dsn()}");
            conn.Open();
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"SKIP: cannot open DSN={Dsn()}: {e.Message}");
            return 77;
        }

        var failures = 0;
        try
        {
            failures += await Run("AppendBasic", () => AppendBasic(conn));
            failures += await Run("OverwriteReplacesPrior", () => OverwriteReplacesPrior(conn));
            failures += await Run("IdempotencyReplay", () => IdempotencyReplay(conn));
            failures += await Run("Land", () => Land(conn));
        }
        finally
        {
            conn.Close();
        }
        Console.WriteLine(failures == 0 ? "ALL PASS" : $"FAILURES: {failures}");
        return failures == 0 ? 0 : 1;
    }

    private static async Task<int> Run(string name, Func<Task> body)
    {
        try
        {
            Console.WriteLine($"--- {name}");
            await body();
            Console.WriteLine("    PASS");
            return 0;
        }
        catch (Exception e)
        {
            Console.WriteLine($"    FAIL: {e.GetType().Name}: {e.Message}");
            return 1;
        }
    }

    private static async Task<string> WriteParquet(long start, int rows)
    {
        var schema = new ParquetSchema(
            new DataField<long>("id"),
            new DataField<string>("region"),
            new DataField<int>("qty"));

        var idCol = new long[rows];
        var regionCol = new string[rows];
        var qtyCol = new int[rows];
        var regions = new[] { "us-east", "us-west", "eu-central" };
        for (var i = 0; i < rows; ++i)
        {
            idCol[i] = start + i;
            regionCol[i] = regions[i % 3];
            qtyCol[i] = (int)((start + i) * 10);
        }

        var path = Path.Combine(Path.GetTempPath(), $"df_ingest_{Guid.NewGuid():N}.parquet");
        await using var fs = File.Create(path);
        using var writer = await ParquetWriter.CreateAsync(schema, fs);
        using (var rg = writer.CreateRowGroup())
        {
            await rg.WriteColumnAsync(new Parquet.Data.DataColumn(
                (DataField<long>)schema[0], idCol));
            await rg.WriteColumnAsync(new Parquet.Data.DataColumn(
                (DataField<string>)schema[1], regionCol));
            await rg.WriteColumnAsync(new Parquet.Data.DataColumn(
                (DataField<int>)schema[2], qtyCol));
        }
        return path;
    }

    private static long CountRows(OdbcConnection conn, string table)
    {
        using var cmd = new OdbcCommand($"SELECT COUNT(*) FROM {table}", conn);
        var v = cmd.ExecuteScalar();
        return Convert.ToInt64(v);
    }

    private static async Task AppendBasic(OdbcConnection conn)
    {
        var target = TargetTable();
        var before = CountRows(conn, target);
        var path = await WriteParquet(0, 100);
        try
        {
            using var cmd = new OdbcCommand(
                $"INGEST INTO {target} MODE='append' FROM PARQUET FILE='{path}'", conn);
            var rc = cmd.ExecuteNonQuery();
            if (rc != 100)
                throw new Exception($"ExecuteNonQuery returned {rc}, expected 100");
            var after = CountRows(conn, target);
            if (after - before != 100)
                throw new Exception($"row delta {after - before} != 100");
        }
        finally
        {
            File.Delete(path);
        }
    }

    private static async Task OverwriteReplacesPrior(OdbcConnection conn)
    {
        var target = Environment.GetEnvironmentVariable("DELTAFORGE_INGEST_OVERWRITE_TARGET")
                     ?? (TargetTable() + "_overwrite");
        var seed = await WriteParquet(0, 30);
        var replace = await WriteParquet(2_000, 5);
        try
        {
            using (var cmd = new OdbcCommand(
                $"INGEST INTO {target} MODE='append' FROM PARQUET FILE='{seed}'", conn))
            {
                cmd.ExecuteNonQuery();
            }
            using (var cmd = new OdbcCommand(
                $"INGEST INTO {target} MODE='overwrite' FROM PARQUET FILE='{replace}'", conn))
            {
                cmd.ExecuteNonQuery();
            }
            if (CountRows(conn, target) != 5)
                throw new Exception("overwrite did not collapse table to 5 rows");
        }
        finally
        {
            File.Delete(seed);
            File.Delete(replace);
        }
    }

    private static async Task IdempotencyReplay(OdbcConnection conn)
    {
        var target = TargetTable();
        var before = CountRows(conn, target);
        var key = $"dotnet-idem-{Guid.NewGuid():N}";
        var path = await WriteParquet(80_000, 11);
        try
        {
            for (var attempt = 0; attempt < 2; ++attempt)
            {
                using var cmd = new OdbcCommand(
                    $"INGEST INTO {target} MODE='append' IDEMPOTENCY_KEY='{key}' " +
                    $"FROM PARQUET FILE='{path}'", conn);
                var rc = cmd.ExecuteNonQuery();
                if (rc != 11)
                    throw new Exception($"attempt {attempt}: rowcount {rc} != 11");
            }
            var after = CountRows(conn, target);
            if (after - before != 11)
                throw new Exception(
                    $"replay must not double-commit; delta {after - before} != 11");
        }
        finally
        {
            File.Delete(path);
        }
    }

    private static async Task Land(OdbcConnection conn)
    {
        var location = Environment.GetEnvironmentVariable("DELTAFORGE_INGEST_LAND_LOCATION")
                       ?? "file:///tmp/df_ingest_land_dotnet";
        var path = await WriteParquet(0, 21);
        try
        {
            using var cmd = new OdbcCommand(
                $"INGEST INTO LOCATION '{location}' MODE='land' " +
                $"FROM PARQUET FILE='{path}'", conn);
            var rc = cmd.ExecuteNonQuery();
            if (rc != 21)
                throw new Exception($"land ExecuteNonQuery returned {rc}, expected 21");
        }
        finally
        {
            File.Delete(path);
        }
    }
}
