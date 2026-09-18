"""Safely populate blank CSV Identifier and ID fields through a NOID CGI.

The CSV is the durable ledger.  The tool mints one identifier per request and
atomically checkpoints the CSV after every successful response.  Dry-run is
the default; network access requires both ``--apply`` and confirmation.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit, urlunsplit

import requests


NAAN = "77981"
SHOULDER = "gmgs"
ARK_NAME_PATTERN = re.compile(
    rf"{NAAN}/{SHOULDER}[0-9bcdfghjkmnpqrstvwxz]{{7}}"
)
REQUIRED_COLUMNS = frozenset({"Title", "Identifier", "ID"})


class MintError(RuntimeError):
    """Raised when minting cannot safely continue."""


class MintOutcomeUnknown(MintError):
    """Raised when a request may have minted an ID but no response arrived."""


@dataclass(frozen=True)
class MintSummary:
    records: int
    already_identified: int
    pending: int
    minted: int


def canonical_ark(ark_name: str) -> str:
    if not ARK_NAME_PATTERN.fullmatch(ark_name):
        raise MintError(f"Unexpected NOID returned by minter: {ark_name!r}")
    return f"ark:/{ark_name}"


def aardvark_id(identifier: str) -> str:
    prefix = f"ark:/{NAAN}/"
    if not identifier.startswith(prefix):
        raise MintError(f"Cannot derive ID from {identifier!r}")
    return identifier.replace(prefix, f"ark:-{NAAN}-", 1)


def parse_mint_response(text: str) -> str:
    """Return exactly one validated ARK name from classic NOID output."""
    identifiers = []
    for line in text.splitlines():
        match = re.fullmatch(r"\s*id:\s*(\S+)\s*", line)
        if match:
            identifiers.append(match.group(1))
    if len(identifiers) != 1:
        excerpt = " ".join(text.split())[:300]
        raise MintError(
            "Expected exactly one 'id:' line from NOID; "
            f"found {len(identifiers)}. Response: {excerpt!r}"
        )
    canonical_ark(identifiers[0])
    return identifiers[0]


def bulk_endpoint(endpoint: str) -> str:
    """Add the classic NOID bulk-command query without altering the path."""
    parts = urlsplit(endpoint.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise MintError("NOIDU endpoint must be an absolute HTTP(S) URL")
    if parts.query and parts.query != "-":
        raise MintError("NOIDU endpoint must not contain a query other than '?-'")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "-", ""))


class NoiduClient:
    """Minimal client for the classic ``noidu`` POST/bulk interface."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout: float = 30,
        bearer_token: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.endpoint = bulk_endpoint(endpoint)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.headers = {"Content-Type": "text/plain; charset=utf-8"}
        if bearer_token:
            self.headers["Authorization"] = f"Bearer {bearer_token}"

    def mint_one(self) -> str:
        try:
            response = self.session.post(
                self.endpoint,
                data="mint 1\n",
                headers=self.headers,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise MintOutcomeUnknown(
                "The NOID request failed without a reliable response. The "
                "identifier may have been minted. Do not retry until the "
                "production minter/audit log has been checked."
            ) from error
        if 300 <= response.status_code < 400:
            raise MintError(
                f"NOIDU returned redirect HTTP {response.status_code}; "
                "use the final authenticated endpoint explicitly"
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise MintError(
                f"NOIDU returned HTTP {response.status_code}: "
                f"{response.text[:300]!r}"
            ) from error
        return parse_mint_response(response.text)


def load_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise MintError(f"CSV not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        missing = sorted(REQUIRED_COLUMNS - set(fields))
        if missing:
            raise MintError(f"CSV is missing required columns: {', '.join(missing)}")
        rows = list(reader)
    return fields, rows


def validate_rows(rows: Sequence[dict[str, str]]) -> tuple[int, list[int]]:
    """Validate identifier state and return (complete count, pending indexes)."""
    complete = 0
    pending = []
    seen_identifiers: set[str] = set()
    seen_ids: set[str] = set()
    errors = []
    for index, row in enumerate(rows):
        line = index + 2
        title = (row.get("Title") or "").strip()
        identifier = (row.get("Identifier") or "").strip()
        record_id = (row.get("ID") or "").strip()
        if not title:
            errors.append(f"row {line}: Title is blank")
            continue
        if bool(identifier) != bool(record_id):
            errors.append(
                f"row {line}: Identifier and ID must either both be blank "
                "or both be populated"
            )
            continue
        if not identifier:
            pending.append(index)
            continue
        try:
            ark_name = identifier.removeprefix("ark:/")
            canonical_ark(ark_name)
            expected_id = aardvark_id(identifier)
        except MintError as error:
            errors.append(f"row {line}: {error}")
            continue
        if record_id != expected_id:
            errors.append(
                f"row {line}: ID mismatch; expected {expected_id!r}, "
                f"got {record_id!r}"
            )
        if identifier in seen_identifiers or record_id in seen_ids:
            errors.append(f"row {line}: duplicate identifier")
        seen_identifiers.add(identifier)
        seen_ids.add(record_id)
        complete += 1
    if errors:
        raise MintError("CSV validation failed:\n" + "\n".join(errors))
    return complete, pending


def atomic_write_csv(
    path: Path, fields: Sequence[str], rows: Sequence[dict[str, str]]
) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def create_backup(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.before-noid-{stamp}.bak")
    shutil.copy2(path, backup)
    return backup


def mint_csv(
    path: Path,
    *,
    client: NoiduClient | None = None,
    apply: bool = False,
    limit: int | None = None,
) -> MintSummary:
    fields, rows = load_csv(path)
    complete, pending_indexes = validate_rows(rows)
    if limit is not None:
        if limit < 1:
            raise MintError("--limit must be a positive integer")
        pending_indexes = pending_indexes[:limit]
    if not apply:
        return MintSummary(len(rows), complete, len(pending_indexes), 0)
    if client is None:
        raise MintError("A NOIDU client is required in apply mode")
    minted = 0
    for index in pending_indexes:
        ark_name = client.mint_one()
        identifier = canonical_ark(ark_name)
        record_id = aardvark_id(identifier)
        if any(
            identifier == row.get("Identifier") or record_id == row.get("ID")
            for row in rows
        ):
            raise MintError(f"NOIDU returned duplicate identifier {identifier}")
        rows[index]["Identifier"] = identifier
        rows[index]["ID"] = record_id
        try:
            atomic_write_csv(path, fields, rows)
        except OSError as error:
            raise MintError(
                f"Minted {identifier}, but could not checkpoint the CSV. "
                "Record this ARK manually before doing anything else."
            ) from error
        minted += 1
        print(f"row {index + 2}: {identifier}  {rows[index]['Title']}", flush=True)
    return MintSummary(len(rows), complete, len(pending_indexes), minted)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Populate blank Identifier/ID cells using an AGSL NOIDU minter."
    )
    parser.add_argument("csv", type=Path, help="CSV ledger to validate or update")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("NOIDU_URL"),
        help="NOIDU CGI URL (or set NOIDU_URL); omit for dry-run",
    )
    parser.add_argument("--apply", action="store_true", help="Perform real mints")
    parser.add_argument("--yes", action="store_true", help="Skip typed confirmation")
    parser.add_argument("--limit", type=int, help="Mint at most this many pending rows")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument(
        "--token-env",
        default="NOIDU_BEARER_TOKEN",
        help="Environment variable containing an optional bearer token",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    path = args.csv.resolve()
    try:
        preview = mint_csv(path, apply=False, limit=args.limit)
        print(
            f"Records: {preview.records}; already identified: "
            f"{preview.already_identified}; pending in this run: {preview.pending}"
        )
        if not args.apply:
            print("Dry run only. No identifiers were minted and no files changed.")
            return 0
        if not args.endpoint:
            raise MintError("--endpoint or NOIDU_URL is required with --apply")
        if preview.pending == 0:
            print("Nothing to mint.")
            return 0
        if not args.yes:
            expected = f"MINT {preview.pending}"
            entered = input(f"Type {expected!r} to modify the production minter: ")
            if entered != expected:
                raise MintError("Confirmation did not match; nothing was minted")
        backup = create_backup(path)
        print(f"Backup: {backup}")
        token = os.environ.get(args.token_env)
        client = NoiduClient(
            args.endpoint,
            timeout=args.timeout,
            bearer_token=token,
        )
        result = mint_csv(
            path,
            client=client,
            apply=True,
            limit=args.limit,
        )
        print(f"Minted and checkpointed: {result.minted}")
        return 0
    except MintOutcomeUnknown as error:
        print(f"STOP: {error}", file=sys.stderr)
        return 3
    except (MintError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
