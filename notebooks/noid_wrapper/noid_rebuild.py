"""Confined tooling for reconstructing an AGSL NOID database.

This module intentionally does not create databases, mint identifiers, release
holds, queue identifiers, delete bindings, or configure a web resolver.  It
turns reviewed Aardvark CSV rows into a deterministic reconstruction manifest
and applies only missing holds and explicit ``set`` bindings.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shlex
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict


NAAN = "77981"
SHOULDER = "gmgs"
ARK_PATTERN = re.compile(
    rf"ark:/{NAAN}/{SHOULDER}[0-9bcdfghjkmnpqrstvwxz]{{7}}"
)
SCHEMA_URL = "http://schema.org/url"
SCHEMA_DOWNLOAD_URL = "http://schema.org/downloadUrl"
CATALOG_BASE_URL = "https://geodiscovery.uwm.edu/catalog/"
ALLOWED_ACCESS = frozenset({"Public", "Restricted"})


class ManifestEntry(TypedDict):
    noid: str
    hold: bool
    bindings: dict[str, str]


class ManifestError(ValueError):
    """Raised when source metadata cannot safely become a NOID entry."""


class NoidCommandError(RuntimeError):
    """Raised when NOID returns an error or an unexpected response."""


@dataclass(frozen=True)
class RowError:
    row: int
    aardvark_id: str
    message: str


@dataclass(frozen=True)
class Manifest:
    entries: tuple[ManifestEntry, ...]
    hold_noids: tuple[str, ...]

    @property
    def bindings(self) -> dict[tuple[str, str], str]:
        return {
            (entry["noid"], element): value
            for entry in self.entries
            for element, value in entry["bindings"].items()
        }


@dataclass(frozen=True)
class DatabaseDump:
    holds: frozenset[str]
    bindings: Mapping[tuple[str, str], str]


def serialize_manifest(manifest: Manifest) -> tuple[str, str]:
    """Return canonical manifest JSON and its SHA-256 checksum."""
    payload = {
        "format": "agsl-noid-rebuild-manifest-v1",
        "entries": list(manifest.entries),
        "hold_noids": list(manifest.hold_noids),
    }
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, checksum


def load_manifest_file(
    path: str | Path, *, expected_sha256: str | None = None
) -> Manifest:
    """Load and fully revalidate a portable reconstruction manifest."""
    raw = Path(path).read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and actual_sha256 != expected_sha256:
        raise ManifestError(
            f"Manifest checksum mismatch: expected {expected_sha256}, "
            f"got {actual_sha256}"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ManifestError(f"Invalid manifest JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ManifestError("Manifest must be a JSON object")
    if payload.get("format") != "agsl-noid-rebuild-manifest-v1":
        raise ManifestError(f"Unsupported manifest format: {payload.get('format')!r}")

    raw_entries = payload.get("entries")
    raw_holds = payload.get("hold_noids")
    if not isinstance(raw_entries, list) or not isinstance(raw_holds, list):
        raise ManifestError("Manifest entries and hold_noids must be arrays")

    entries: list[ManifestEntry] = []
    for index, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            raise ManifestError(f"Manifest entry {index} must be an object")
        noid = entry.get("noid")
        hold = entry.get("hold")
        bindings = entry.get("bindings")
        if (
            not isinstance(noid, str)
            or hold is not True
            or not isinstance(bindings, dict)
            or not all(
                isinstance(element, str) and isinstance(value, str)
                for element, value in bindings.items()
            )
        ):
            raise ManifestError(f"Malformed manifest entry {index}")
        entries.append({"noid": noid, "hold": True, "bindings": bindings})

    if not all(isinstance(noid, str) for noid in raw_holds):
        raise ManifestError("Every hold_noids value must be a string")
    entry_noids = {entry["noid"] for entry in entries}
    hold_only = set(raw_holds) - entry_noids
    manifest = build_manifest(entries, hold_only_noids=hold_only)
    if tuple(raw_holds) != manifest.hold_noids:
        raise ManifestError("Manifest hold_noids is incomplete, duplicated, or unsorted")
    return manifest


def serialize_noid_commands(manifest: Manifest) -> tuple[str, str]:
    """Return native NOID bulk commands and their SHA-256 checksum."""
    lines = [shlex.join(["hold", "set", noid]) for noid in manifest.hold_noids]
    for entry in manifest.entries:
        for element, value in sorted(entry["bindings"].items()):
            lines.append(
                shlex.join(
                    ["bind", "set", entry["noid"], element, value]
                )
            )
    text = "\n".join(lines) + "\n"
    checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, checksum


def build_noid_entry(row: Mapping[str, str]) -> ManifestEntry:
    """Build one validated, non-mutating reconstruction entry."""
    try:
        identifier = row["Identifier"]
        aardvark_id = row["ID"].strip()
        title = row["Title"].strip()
        access = row["Access Rights"].strip()
        reference_text = row["dct_references_s"]
    except (AttributeError, KeyError) as error:
        raise ManifestError(f"Missing or invalid column: {error}") from error

    arks = [
        value.strip()
        for value in identifier.split("|")
        if ARK_PATTERN.fullmatch(value.strip())
    ]
    if len(arks) != 1:
        raise ManifestError(f"Expected one canonical ARK; found {len(arks)}")

    ark = arks[0]
    expected_id = ark.replace(f"ark:/{NAAN}/", f"ark:-{NAAN}-", 1)
    if aardvark_id != expected_id:
        raise ManifestError(
            f"ID mismatch: expected {expected_id!r}, got {aardvark_id!r}"
        )
    if not title:
        raise ManifestError("Title is blank")
    if access not in ALLOWED_ACCESS:
        raise ManifestError(
            f"Access Rights must be one of {sorted(ALLOWED_ACCESS)}; got {access!r}"
        )

    try:
        references = json.loads(reference_text)
    except (TypeError, json.JSONDecodeError) as error:
        raise ManifestError(f"Invalid dct_references_s JSON: {error}") from error
    if not isinstance(references, dict):
        raise ManifestError("dct_references_s must decode to an object")

    where = references.get(SCHEMA_URL)
    expected_where = f"{CATALOG_BASE_URL}{aardvark_id}"
    if where != expected_where:
        raise ManifestError(
            f"Resolver mismatch: expected {expected_where!r}, got {where!r}"
        )

    bindings = {
        "identifier": ark,
        "ogm_aardvark_id": aardvark_id,
        "title": title,
        "access": access,
        "where": where,
    }
    download = references.get(SCHEMA_DOWNLOAD_URL)
    if download:
        if not isinstance(download, str):
            raise ManifestError("Download reference must be a string")
        bindings["download"] = download

    for element, value in bindings.items():
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ManifestError(
                f"Binding {element!r} contains an unsupported control character"
            )

    return {
        "noid": ark.removeprefix("ark:/"),
        "hold": True,
        "bindings": bindings,
    }


def load_csv_entries(path: str | Path) -> tuple[list[ManifestEntry], list[RowError]]:
    """Read Aardvark CSV rows, retaining every row-level conversion error."""
    entries: list[ManifestEntry] = []
    errors: list[RowError] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for row_number, row in enumerate(csv.DictReader(stream), start=2):
            try:
                entries.append(build_noid_entry(row))
            except ManifestError as error:
                errors.append(
                    RowError(row_number, row.get("ID", ""), str(error))
                )
    return entries, errors


def build_manifest(
    entries: Iterable[ManifestEntry],
    *,
    hold_only_noids: Iterable[str] = (),
) -> Manifest:
    """Validate cross-record invariants and return a deterministic manifest."""
    ordered_entries = tuple(sorted(entries, key=lambda entry: entry["noid"]))
    entry_noids = [entry["noid"] for entry in ordered_entries]
    if len(entry_noids) != len(set(entry_noids)):
        raise ManifestError("Duplicate NOIDs found in bound entries")

    where_values = [entry["bindings"]["where"] for entry in ordered_entries]
    if len(where_values) != len(set(where_values)):
        raise ManifestError("Duplicate resolver URLs found in bound entries")

    hold_only = set(hold_only_noids)
    invalid_hold_only = [
        noid
        for noid in hold_only
        if not ARK_PATTERN.fullmatch(f"ark:/{noid}")
    ]
    if invalid_hold_only:
        raise ManifestError(
            f"Invalid hold-only NOIDs: {sorted(invalid_hold_only)[:10]}"
        )
    overlap = set(entry_noids) & hold_only
    if overlap:
        raise ManifestError(
            f"Hold-only NOIDs also have entries: {sorted(overlap)[:10]}"
        )

    return Manifest(
        entries=ordered_entries,
        hold_noids=tuple(sorted(set(entry_noids) | hold_only)),
    )


def parse_database_dump(text: str) -> DatabaseDump:
    """Parse hold keys and ordinary bindings from ``noid dbinfo dump``."""
    holds: set[str] = set()
    bindings: dict[tuple[str, str], str] = {}
    for line in text.splitlines():
        if "\t" not in line:
            continue
        noid, stored = line.split("\t", 1)
        noid = noid.strip()
        if stored.startswith(":/h:"):
            holds.add(noid)
            continue
        if not noid.startswith(f"{NAAN}/{SHOULDER}") or stored.startswith(":/"):
            continue
        element, separator, value = stored.partition(": ")
        if separator:
            bindings[(noid, element)] = value
    return DatabaseDump(frozenset(holds), bindings)


def missing_holds(requested: Iterable[str], existing: Iterable[str]) -> list[str]:
    """Return only absent holds; repeated holds corrupt NOID's held counter."""
    return sorted(set(requested) - set(existing))


def verify_database(manifest: Manifest, dump: DatabaseDump) -> None:
    """Require exact agreement between a database dump and a manifest."""
    expected_holds = set(manifest.hold_noids)
    if dump.holds != expected_holds:
        missing = sorted(expected_holds - dump.holds)
        unexpected = sorted(dump.holds - expected_holds)
        raise ManifestError(
            f"Hold mismatch; missing={missing[:10]}, unexpected={unexpected[:10]}"
        )

    expected_bindings = manifest.bindings
    actual_bindings = dict(dump.bindings)
    missing_keys = sorted(expected_bindings.keys() - actual_bindings.keys())
    unexpected_keys = sorted(actual_bindings.keys() - expected_bindings.keys())
    mismatched = sorted(
        key
        for key in expected_bindings.keys() & actual_bindings.keys()
        if expected_bindings[key] != actual_bindings[key]
    )
    if missing_keys or unexpected_keys or mismatched:
        raise ManifestError(
            "Binding mismatch; "
            f"missing={missing_keys[:10]}, unexpected={unexpected_keys[:10]}, "
            f"different={mismatched[:10]}"
        )


class NoidRebuilder:
    """Minimal subprocess adapter for a pre-existing scratch NOID database."""

    def __init__(
        self,
        noid_binary: str | Path,
        database_dir: str | Path,
        perl5lib: str | Path,
    ) -> None:
        self.noid_binary = Path(noid_binary).resolve()
        self.database_dir = Path(database_dir).resolve()
        self.perl5lib = Path(perl5lib).resolve()

    def _run(
        self, args: Sequence[str], *, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [
                    str(self.noid_binary),
                    "-f",
                    str(self.database_dir),
                    *args,
                ],
                env={**os.environ, "PERL5LIB": str(self.perl5lib)},
                input=input_text,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as error:
            raise NoidCommandError(
                f"NOID command failed ({error.returncode}): "
                f"{' '.join(args)}\n{error.stderr}"
            ) from error

    def validate(self, noids: Iterable[str]) -> None:
        requested = list(noids)
        if not requested:
            return
        result = self._run(["validate", "-", *requested])
        lines = result.stdout.splitlines()
        errors = [line for line in lines if line.startswith("iderr:")]
        if errors or len(lines) != len(requested):
            raise NoidCommandError(
                f"NOID validation failed: {errors[:10] or result.stdout}"
            )

    def dump(self) -> DatabaseDump:
        return parse_database_dump(self._run(["dbinfo", "dump"]).stdout)

    def add_missing_holds(self, noids: Iterable[str]) -> int:
        """Place only absent holds, preserving NOID's administrative counter."""
        absent = missing_holds(noids, self.dump().holds)
        if not absent:
            return 0
        self._run(["hold", "set", *absent])
        remaining = missing_holds(absent, self.dump().holds)
        if remaining:
            raise NoidCommandError(f"Holds were not stored: {remaining[:10]}")
        return len(absent)

    def bind_entry(self, entry: ManifestEntry) -> None:
        payload = "".join(
            f"{element}: {value}\n"
            for element, value in entry["bindings"].items()
        ) + "\n"
        result = self._run(
            ["bind", "set", entry["noid"], ":"], input_text=payload
        )
        expected = len(entry["bindings"])
        successful = result.stdout.count("Status:  ok")
        if successful != expected:
            raise NoidCommandError(
                f"Binding failed for {entry['noid']}: "
                f"{successful}/{expected} successful\n{result.stdout}"
            )

    def apply(self, manifest: Manifest) -> None:
        """Validate, add missing holds, set bindings, then verify exactly."""
        self.validate(manifest.hold_noids)
        self.add_missing_holds(manifest.hold_noids)
        for entry in manifest.entries:
            self.bind_entry(entry)
        verify_database(manifest, self.dump())
