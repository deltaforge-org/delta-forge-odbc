# DeltaForge ODBC Driver

ODBC driver for DeltaForge. Lets Power BI, Tableau, Excel, DBeaver, Python,
.NET, R, and any other ODBC-aware client query DeltaForge tables directly,
without copying data into a second relational database first.

The driver registers under the canonical name **`DeltaForge ODBC Driver`**
on every supported platform.

- **Project home**: https://github.com/deltaforge-org/delta-forge-odbc
- **Documentation**: https://docs.deltaforge.org/
- **Issue tracker**: https://github.com/deltaforge-org/delta-forge-odbc/issues

## Why this driver exists

Most teams ship lakehouse data twice: once into Delta tables, then again
into Azure SQL, SQL Server, or a hosted warehouse, just so their BI tool
can render a chart at acceptable speed. The result is two storage systems
holding the same numbers, a nightly copy job to keep them aligned, and a
refresh window that stakeholders see as stale dashboards.

The DeltaForge ODBC driver removes the second copy. BI tools point at
DeltaForge directly. One source of truth, one governance model, no copy
pipeline.

## Supported clients

| Client | Connection path |
|---|---|
| Power BI Desktop &amp; Service | Get Data &gt; ODBC |
| Tableau Desktop, Server, Cloud | More... &gt; Other Databases (ODBC) |
| Microsoft Excel | Data &gt; Get Data &gt; From ODBC |
| DBeaver | Database &gt; New Database Connection &gt; ODBC |
| Python | `pyodbc.connect("DSN=DeltaForge;...")` |
| .NET | `new OdbcConnection("DSN=DeltaForge;...")` |
| R | `dbConnect(odbc::odbc(), dsn = "DeltaForge")` |
| dbt | `dbt-odbc` adapter |
| MicroStrategy | Generic DBMS, ODBC connection |
| Qlik Sense, QlikView | ODBC data connection |

For per-tool walkthroughs see https://docs.deltaforge.org/odbc/bi-tools/.

## Install

The release pipeline produces a signed installer for each platform.
Downloads are attached to GitHub releases at
https://github.com/deltaforge-org/delta-forge-odbc/releases.

### Windows

```
msiexec /i DeltaForgeODBC-<version>-x64.msi /qn /norestart
```

The installer registers the driver under
`HKLM\Software\ODBC\ODBCINST.INI\DeltaForge ODBC Driver` so every
ODBC-aware application on the machine sees it.

Open the **64-bit ODBC Data Source Administrator** (`odbcad32.exe` in
`System32`) to add a DSN. Modern Power BI and Excel are 64-bit; the
32-bit administrator under `SysWOW64` will not see the driver.

### Linux

```
# Debian / Ubuntu
sudo apt install ./delta-forge-odbc_<version>_amd64.deb

# RHEL / Rocky / Amazon Linux
sudo dnf install ./delta-forge-odbc-<version>.x86_64.rpm
```

The package writes a driver entry under `/etc/odbcinst.ini`. Verify with
`odbcinst -q -d`. Add a DSN to `~/.odbc.ini` (user) or `/etc/odbc.ini`
(system).

### macOS

```
sudo installer -pkg DeltaForgeODBC-<version>.pkg -target /
```

The installer registers with iODBC (the macOS-native driver manager).
Tableau Desktop on macOS uses iODBC, so no additional registration is
needed.

## First connection

Smoke-test before wiring up a BI tool:

```sh
# Linux (unixODBC)
isql -v DeltaForge alice@example.com 'hunter2'

# macOS (iODBC)
iodbctest 'DSN=DeltaForge;Uid=alice@example.com;Pwd=hunter2'

# Python (any platform)
python3 -c "import pyodbc; \
  c = pyodbc.connect('DSN=DeltaForge;Uid=alice@example.com;Pwd=hunter2'); \
  print(c.cursor().execute('SELECT 1').fetchone())"
```

A successful connection returns a row from `SELECT 1`. If the smoke test
works and Power BI later fails, the problem is somewhere above the driver.

## Connection string

A minimum connection string:

```
DSN=DeltaForge;Uid=alice@example.com;Pwd=hunter2
```

Or, with no system DSN required:

```
Driver={DeltaForge ODBC Driver};Server=https://df.example.com;Uid=alice@example.com;Pwd=hunter2
```

### Common keys

| Key | Purpose |
|---|---|
| `Server` | Control plane URL (required) |
| `Uid` | Username, email, or service identifier |
| `Pwd` | Password (or omit, see Credential storage below) |
| `Token` | DeltaForge personal access token, prefix `df_pat_` |
| `Database` (alias `Catalog`) | Default zone |
| `Schema` | Default schema |
| `ApplicationName` | User-Agent suffix surfaced in audit logs |
| `ConnectionTimeout` (alias `LoginTimeout`) | Connect-phase budget in seconds |
| `CommandTimeout` | Default per-statement timeout in seconds |
| `ComputeServer` | Pin queries to a specific compute URL |
| `ComputeNode` | Pin queries to a specific compute node by entity reference |
| `HTTPProxy` | Forward proxy URL (with optional `ProxyUID` / `ProxyPWD`) |

The parser also accepts vocabulary borrowed from other vendors so
existing connection strings need not be rewritten: `User`, `Password`,
`AccessToken`, `OAuthToken`, `Authentication`, `AuthMech`,
`HOST` + `PORT`, `LoginTimeout`, `Connect Timeout`,
`ProxyHost` + `ProxyPort`. Keys the driver does not recognise are
silently accepted so a future BI tool's exotic key does not break a
working connection.

For the full reference: https://docs.deltaforge.org/odbc/connection-string/.

## Credential storage

The driver looks credentials up from the OS-native secret store when
`Pwd` is absent from the connection string, so passwords do not need to
live in `odbc.ini` or the registry in cleartext.

| Platform | Backend |
|---|---|
| Windows | DPAPI per-user encryption + a registry entry under `HKCU\Software\DeltaForge\Credstore` |
| macOS | Keychain Services (login keychain, generic password class) |
| Linux | libsecret over D-Bus (GNOME Keyring, KWallet, KeePassXC, any Secret-Service implementation) |
| Linux fallback | mode-0600 file under `~/.config/deltaforge/credstore/` for headless hosts with no D-Bus session |

Credentials are saved through the DSN setup GUI's **Save password**
flow on each platform. The next connection that omits `Pwd` reads the
stored value.

Lookup order at connect time:

1. `Token=` in the connection string (used directly)
2. `Pwd=` in the connection string (used directly)
3. `Pwd:<Uid>` in the OS keychain under the DSN name
4. `Token:<Uid>` in the OS keychain under the DSN name

An explicit `Pwd=` always wins. To force the keychain lookup, omit
`Pwd=` from both the connection string and the DSN file.

## Identifier case

DeltaForge object names are lowercase / snake_case and case-preserving.
The driver returns column names verbatim. Application code that
uppercases or lowercases names for a case-insensitive lookup will break
against case-preserving identifiers; use the names the driver returns.

## Diagnostics

Every error path populates a SQLSTATE chain accessible through
`SQLGetDiagRec`. Common values:

| SQLSTATE | Meaning |
|---|---|
| `08001` | Client unable to establish connection |
| `28000` | Authentication failed |
| `42000` | SQL syntax error |
| `42S02` | Object not found |
| `01004` | String data, right truncation (resize buffer and re-fetch) |
| `HY010` | Function sequence error |
| `HYC00` | Optional feature not implemented |
| `HYT00` | Operation timed out |

Every BI tool surfaces the chain in some form: Power BI's error pop-up
**Details** view, Tableau's performance recording, DBeaver's error pane,
`SQLGetDiagRec` directly from code.

## Reporting issues

- Bugs and feature requests: https://github.com/deltaforge-org/delta-forge-odbc/issues
- Security disclosures: see [SECURITY.md](SECURITY.md)

When filing a bug, include the client tool and version, the platform
and architecture, and the SQLSTATE chain returned by `SQLGetDiagRec`.

## License

See [LICENSE](LICENSE).

## Trademarks

DeltaForge is a trademark of its respective owners. Power BI, Tableau,
Excel, Windows, macOS, and Linux are trademarks of their respective
holders and are referenced here for compatibility purposes only.
