import csv
import tempfile
import unittest
from pathlib import Path

from noid_mint import (
    MintError,
    aardvark_id,
    mint_csv,
    parse_mint_response,
)


FIELDS = ["Title", "Identifier", "ID", "Download"]


class FakeClient:
    def __init__(self, identifiers):
        self.identifiers = iter(identifiers)
        self.calls = 0

    def mint_one(self):
        self.calls += 1
        return next(self.identifiers)


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class NoidMintTests(unittest.TestCase):
    def test_parse_mint_response(self):
        self.assertEqual(
            parse_mint_response("id: 77981/gmgs0c4sj74\n\n"),
            "77981/gmgs0c4sj74",
        )

    def test_response_must_contain_exactly_one_id(self):
        with self.assertRaises(MintError):
            parse_mint_response("error: database unavailable\n")
        with self.assertRaises(MintError):
            parse_mint_response(
                "id: 77981/gmgs0c4sj74\nid: 77981/gmgs154dn9c\n"
            )

    def test_aardvark_id(self):
        self.assertEqual(
            aardvark_id("ark:/77981/gmgs0c4sj74"),
            "ark:-77981-gmgs0c4sj74",
        )

    def test_dry_run_does_not_change_csv_or_call_client(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.csv"
            write_csv(path, [{"Title": "One", "Identifier": "", "ID": ""}])
            before = path.read_bytes()
            client = FakeClient(["77981/gmgs0c4sj74"])
            summary = mint_csv(path, client=client, apply=False)
            self.assertEqual(summary.pending, 1)
            self.assertEqual(client.calls, 0)
            self.assertEqual(path.read_bytes(), before)

    def test_apply_checkpoints_and_resume_skips_completed_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.csv"
            write_csv(
                path,
                [
                    {"Title": "One", "Identifier": "", "ID": ""},
                    {"Title": "Two", "Identifier": "", "ID": ""},
                ],
            )
            first = FakeClient(["77981/gmgs0c4sj74"])
            result = mint_csv(path, client=first, apply=True, limit=1)
            self.assertEqual(result.minted, 1)
            second = FakeClient(["77981/gmgs154dn9c"])
            result = mint_csv(path, client=second, apply=True)
            self.assertEqual(result.minted, 1)
            with path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["Identifier"], "ark:/77981/gmgs0c4sj74")
            self.assertEqual(rows[1]["Identifier"], "ark:/77981/gmgs154dn9c")

    def test_partial_identifier_state_is_rejected_before_minting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.csv"
            write_csv(
                path,
                [{"Title": "One", "Identifier": "ark:/77981/gmgs0c4sj74", "ID": ""}],
            )
            client = FakeClient(["77981/gmgs154dn9c"])
            with self.assertRaisesRegex(MintError, "both be blank"):
                mint_csv(path, client=client, apply=True)
            self.assertEqual(client.calls, 0)


if __name__ == "__main__":
    unittest.main()
