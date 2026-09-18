# NOID minting preprocessor

`noid_mint.py` populates blank `Identifier` and `ID` cells before the CSV is
passed to the Aardvark converter. The CSV is the durable minting ledger.

The default invocation is validation-only and performs no network requests:

```bash
uv run python notebooks/csv2JSON/noid_mint.py \
  notebooks/csv2JSON/MilwaukeeOpenDataPortal-20260918.csv
```

Before a production run, confirm the authoritative `noidu` CGI endpoint and
its authentication with the service administrator. Do not put credentials in
the CSV, command history, notebook, or repository. `requests` may use a
protected `.netrc`; an optional bearer token can instead be supplied through
`NOIDU_BEARER_TOKEN`.

Test a single row first:

```bash
export NOIDU_URL='https://REPLACE-WITH-AUTHORITATIVE-ENDPOINT/noidu_gmgs'
uv run python notebooks/csv2JSON/noid_mint.py \
  notebooks/csv2JSON/MilwaukeeOpenDataPortal-20260918.csv \
  --apply --limit 1
```

After verifying that identifier in the production minter and CSV, process the
remaining blank rows by omitting `--limit`. Apply mode creates a timestamped
backup, asks for typed confirmation, sends `mint 1` through the classic
`noidu?-` POST interface, and atomically saves the CSV after every response.
Rows whose `Identifier` and `ID` are already populated are validated and
skipped.

If a request times out or loses its connection, the command stops with exit
status 3. The outcome may be ambiguous: the server may have minted an
identifier even though the client did not receive it. Do not retry until the
production minter or its audit log has been inspected.

The tool does not bind identifiers. Binding should occur later, after the
archived download URL and final GeoDiscovery catalog URL are known.
