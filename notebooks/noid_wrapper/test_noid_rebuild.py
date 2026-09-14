import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from noid_rebuild import (
    ManifestError,
    NoidRebuilder,
    build_manifest,
    build_noid_entry,
    load_manifest_file,
    missing_holds,
    parse_database_dump,
    serialize_manifest,
    serialize_noid_commands,
    verify_database,
)


def example_row():
    return {
        "ID": "ark:-77981-gmgs0c4sj74",
        "Identifier": "call number|ark:/77981/gmgs0c4sj74",
        "Title": "Parcels Milwaukee, Wisconsin April 7, 2014",
        "Access Rights": "Public",
        "dct_references_s": json.dumps(
            {
                "http://schema.org/url": (
                    "https://geodiscovery.uwm.edu/catalog/"
                    "ark:-77981-gmgs0c4sj74"
                ),
                "http://schema.org/downloadUrl": "https://example.org/data.zip",
            }
        ),
    }


class NoidRebuildTests(unittest.TestCase):
    def test_build_noid_entry(self):
        entry = build_noid_entry(example_row())
        self.assertEqual(entry["noid"], "77981/gmgs0c4sj74")
        self.assertEqual(
            entry["bindings"]["identifier"], "ark:/77981/gmgs0c4sj74"
        )
        self.assertEqual(
            entry["bindings"]["download"], "https://example.org/data.zip"
        )

    def test_build_noid_entry_rejects_wrong_resolver(self):
        row = example_row()
        row["dct_references_s"] = json.dumps(
            {"http://schema.org/url": "https://example.org/wrong"}
        )
        with self.assertRaisesRegex(ManifestError, "Resolver mismatch"):
            build_noid_entry(row)

    def test_manifest_rejects_duplicate_noids(self):
        entry = build_noid_entry(example_row())
        with self.assertRaisesRegex(ManifestError, "Duplicate NOIDs"):
            build_manifest([entry, entry])

    def test_missing_holds_returns_only_difference(self):
        self.assertEqual(missing_holds({"a", "b", "c"}, {"a", "c"}), ["b"])

    def test_manifest_serialization_is_deterministic(self):
        entry = build_noid_entry(example_row())
        manifest = build_manifest([entry])
        first = serialize_manifest(manifest)
        second = serialize_manifest(manifest)
        self.assertEqual(first, second)
        payload = json.loads(first[0])
        self.assertEqual(payload["format"], "agsl-noid-rebuild-manifest-v1")

    def test_load_manifest_file_checks_checksum_and_invariants(self):
        entry = build_noid_entry(example_row())
        manifest = build_manifest([entry], hold_only_noids={"77981/gmgs15dv46t"})
        text, checksum = serialize_manifest(manifest)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(text, encoding="utf-8")
            loaded = load_manifest_file(path, expected_sha256=checksum)
            self.assertEqual(loaded, manifest)
            with self.assertRaisesRegex(ManifestError, "checksum mismatch"):
                load_manifest_file(path, expected_sha256="0" * 64)

    def test_native_commands_are_deterministic_and_safely_quoted(self):
        row = example_row()
        row["Title"] = "Reader's map"
        manifest = build_manifest([build_noid_entry(row)])
        first = serialize_noid_commands(manifest)
        second = serialize_noid_commands(manifest)
        self.assertEqual(first, second)
        self.assertEqual(len(first[0].splitlines()), 7)
        self.assertIn("Reader'\"'\"'s map", first[0])

    def test_parse_and_verify_database_dump(self):
        entry = build_noid_entry(example_row())
        manifest = build_manifest(
            [entry], hold_only_noids={"77981/gmgs15dv46t"}
        )
        lines = [
            "77981/gmgs0c4sj74\t:/h: 1",
            "77981/gmgs15dv46t\t:/h: 1",
        ]
        lines.extend(
            f"{entry['noid']}\t{element}: {value}"
            for element, value in entry["bindings"].items()
        )
        verify_database(manifest, parse_database_dump("\n".join(lines)))

    def test_add_missing_holds_does_not_repeat_existing(self):
        calls = []
        dumps = iter(
            [
                "77981/gmgs0c4sj74\t:/h: 1\n",
                (
                    "77981/gmgs0c4sj74\t:/h: 1\n"
                    "77981/gmgs15dv46t\t:/h: 1\n"
                ),
            ]
        )

        def fake_run(command, **kwargs):
            calls.append(command)
            stdout = (
                next(dumps) if command[-2:] == ["dbinfo", "dump"] else "ok\n"
            )
            return subprocess.CompletedProcess(command, 0, stdout, "")

        with tempfile.TemporaryDirectory() as directory:
            with patch("subprocess.run", side_effect=fake_run):
                rebuilder = NoidRebuilder("noid", Path(directory), "perl5")
                added = rebuilder.add_missing_holds(
                    ["77981/gmgs0c4sj74", "77981/gmgs15dv46t"]
                )

        self.assertEqual(added, 1)
        hold_call = next(command for command in calls if "hold" in command)
        self.assertEqual(
            hold_call[-3:], ["hold", "set", "77981/gmgs15dv46t"]
        )


if __name__ == "__main__":
    unittest.main()
