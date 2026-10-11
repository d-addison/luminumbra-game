"""Tests for tools/check_tree_small_02_receipts.py and validators/resource_accounting.py."""

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import check_tree_small_02_receipts as checker  # noqa: E402
from validators import resource_accounting  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "tree-small-02-receipt-counts.json"
MANIFEST = REPO / "assets" / "tree-small-02" / "runtime-manifest.json"
DOC = REPO / "docs" / "canopy-conversion.md"
EVIDENCE = REPO / "docs" / "evidence" / "tree-small-02-resource-accounting.json"
LEAF_BRANCHES_LOD0 = "data/models/trees/tree_small_02_branches.lmesh"
LEAF_LOD1 = "data/models/trees/tree_small_02_leaves.lod1.lmesh"
TEXTURE = "data/textures/models/tree_trunk_albedo_512.ltex"


def _run(argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = checker.main(argv)
    return code, out.getvalue(), err.getvalue()


class ReceiptTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def _receipt_with(self, mutate, name="receipt.json"):
        data = copy.deepcopy(self.fixture)
        mutate(data)
        path = self.dir / name
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return path

    def _entry(self, data, path):
        for entry in data["files"]:
            if entry["path"] == path:
                return entry
        raise KeyError(path)

    def _expect_failure(self, mutate, needle):
        receipt = self._receipt_with(mutate)
        code, out, err = _run(["--receipt", str(receipt), "--manifest", str(MANIFEST)])
        self.assertEqual(code, 1, err)
        self.assertIn(needle, err)
        self.assertEqual(out, "")


class PositiveTests(ReceiptTestCase):
    def test_fixture_passes(self):
        code, out, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST)])
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")

    def test_full_mode_skips_trimmed_fixture(self):
        code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--full"])
        self.assertEqual(code, 0, err)

    def test_emit_json_is_deterministic_and_valid(self):
        target = self.dir / "accounting.json"
        code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--emit-json", str(target)])
        self.assertEqual(code, 0, err)
        first = target.read_bytes()
        code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--check-json", str(target)])
        self.assertEqual(code, 0, err)
        self.assertEqual(first, target.read_bytes())
        obj = json.loads(first.decode("utf-8"))
        self.assertEqual(obj["totals"]["texture_file_bytes"], 12583053)
        self.assertEqual(obj["totals"]["texture_payload_bytes"], 12582900)
        self.assertEqual(obj["totals"]["mesh_triangles_by_lod"], {"lod0": 116496, "lod1": 90597, "lod2": 74498})
        self.assertEqual(obj["measured"], [])
        self.assertIsNone(obj["source_receipt"]["sha256"])
        self.assertEqual(resource_accounting.validate(str(target), obj), [])

    def test_emit_json_matches_committed_evidence_when_present(self):
        if not EVIDENCE.exists():
            self.skipTest("docs/evidence/tree-small-02-resource-accounting.json is not generated yet")
        target = self.dir / "accounting.json"
        code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--emit-json", str(target)])
        self.assertEqual(code, 0, err)
        self.assertEqual(target.read_bytes(), EVIDENCE.read_bytes())

    def test_check_doc_passes_for_public_page(self):
        code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--check-doc", str(DOC)])
        self.assertEqual(code, 0, err)

    def test_emit_doc_table_matches_doc_block(self):
        code, out, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--emit-doc-table"])
        self.assertEqual(code, 0, err)
        lines = out.split("\n")
        self.assertEqual(lines[0], "| Part | LOD | Vertices | Triangles | File bytes |")
        self.assertEqual(len([line for line in lines if line.startswith("| ")]), 11)

    def test_full_mode_requires_receipt_bytes_in_manifest(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        receipt = self._receipt_with(lambda data: data.pop("trimmed"))
        for entry in manifest["files"]:
            if entry["path"] == "conversion-receipt.json":
                entry["sha256"] = "0" * 64
        altered = self.dir / "manifest.json"
        altered.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        code, _, err = _run(["--receipt", str(receipt), "--manifest", str(altered), "--full"])
        self.assertEqual(code, 1)
        self.assertIn("receipt sha256 does not match manifest entry", err)


class NegativeTests(ReceiptTestCase):
    def test_wrong_schema(self):
        self._expect_failure(lambda d: d.update(schema="luminumbra.game.asset-conversion.v0"), "unknown schema")

    def test_wrong_engine_revision(self):
        self._expect_failure(lambda d: d.update(engine_revision="0" * 40), "does not match pinned")

    def test_seventeen_files(self):
        self._expect_failure(lambda d: d["files"].pop(), "files has 17 entries, expected 18")

    def test_missing_path_in_manifest(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["files"] = [e for e in manifest["files"] if e["path"] != LEAF_LOD1]
        altered = self.dir / "manifest.json"
        altered.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(altered)])
        self.assertEqual(code, 1)
        self.assertIn("%s: not in manifest" % LEAF_LOD1, err)

    def test_size_mismatch(self):
        def mutate(data):
            self._entry(data, LEAF_BRANCHES_LOD0)["size"] += 1

        self._expect_failure(mutate, "does not match manifest")

    def test_sha_mismatch(self):
        def mutate(data):
            self._entry(data, LEAF_BRANCHES_LOD0)["sha256"] = "1" * 64

        self._expect_failure(mutate, "sha256 does not match manifest")

    def test_mesh_size_formula_broken(self):
        def mutate(data):
            self._entry(data, LEAF_BRANCHES_LOD0)["vertices"] += 1

        self._expect_failure(mutate, "28 + 32*")

    def test_leaf_triangles_60499(self):
        def mutate(data):
            self._entry(data, LEAF_LOD1)["triangles"] = 60499

        self._expect_failure(mutate, "triangles 60499, expected 60500")

    def test_leaf_surfaces_30249(self):
        def mutate(data):
            data["leaf_fitter"]["result"]["leaf_surfaces"] = 30249

        self._expect_failure(mutate, "leaf_surfaces 30249, expected 30250")

    def test_residual_above_bound(self):
        def mutate(data):
            data["leaf_fitter"]["result"]["maximum_relative_fit_error"] = 0.21

        self._expect_failure(mutate, "maximum_relative_fit_error 0.21 exceeds bound 0.20")

    def test_duplicate_path(self):
        def mutate(data):
            data["files"][0]["path"] = data["files"][1]["path"]

        self._expect_failure(mutate, "duplicate path")

    def test_texture_size_1398116(self):
        def mutate(data):
            self._entry(data, TEXTURE)["size"] = 1398116

        self._expect_failure(mutate, "%s: size 1398116, expected 1398117" % TEXTURE)

    def test_measured_entry_without_evidence(self):
        def mutate(data):
            data["measured"] = [{"metric": "vram", "value": 1}]

        self._expect_failure(mutate, "missing key 'evidence_sha256'")

    def test_check_doc_rejects_stale_block(self):
        stale = self.dir / "doc.md"
        text = DOC.read_text(encoding="utf-8").replace("| trunk | 2 | 884 | 998 | 40292 |", "| trunk | 2 | 885 | 998 | 40292 |")
        stale.write_text(text, encoding="utf-8")
        code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--check-doc", str(stale)])
        self.assertEqual(code, 1)
        self.assertIn("does not match the generated table", err)

    def test_check_doc_requires_markers(self):
        bare = self.dir / "bare.md"
        bare.write_text("no markers here\n", encoding="utf-8")
        code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--check-doc", str(bare)])
        self.assertEqual(code, 1)
        self.assertIn("expected exactly one", err)

    def test_unreadable_receipt_is_usage_error(self):
        code, _, err = _run(["--receipt", str(self.dir / "missing.json"), "--manifest", str(MANIFEST)])
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)

    def test_missing_receipt_argument_is_usage_error(self):
        code, _, _ = _run(["--manifest", str(MANIFEST)])
        self.assertEqual(code, 2)


class AccountingValidatorTests(unittest.TestCase):
    def _accounting(self):
        receipt = json.loads(FIXTURE.read_text(encoding="utf-8"))
        return checker.build_accounting(receipt, FIXTURE.read_bytes())

    def test_built_accounting_is_valid(self):
        self.assertEqual(resource_accounting.validate("acc.json", self._accounting()), [])

    def test_measured_entry_requires_evidence_sha256(self):
        obj = self._accounting()
        obj["measured"] = [{"metric": "vram", "value": 1}]
        problems = resource_accounting.validate("acc.json", obj)
        self.assertTrue(any("missing key 'evidence_sha256'" in p for p in problems), problems)

    def test_totals_must_match_lists(self):
        obj = self._accounting()
        obj["totals"]["texture_file_bytes"] += 1
        problems = resource_accounting.validate("acc.json", obj)
        self.assertTrue(any("texture_file_bytes" in p for p in problems), problems)

    def test_wrong_schema_rejected(self):
        obj = self._accounting()
        obj["schema"] = "luminumbra.game.other.v1"
        self.assertEqual(len(resource_accounting.validate("acc.json", obj)), 1)


if __name__ == "__main__":
    unittest.main()
