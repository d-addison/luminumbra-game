"""Tests for tools/check_tree_small_02_receipts.py and validators/resource_accounting.py."""

import contextlib
import copy
import hashlib
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


def _json_text(data):
    return json.dumps(data, indent=2) + "\n"


def _write_text_bytes(path, text):
    path.write_bytes(text.encode("utf-8"))
    return path


class ReceiptTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.fixture = json.loads(FIXTURE.read_bytes().decode("utf-8"))

    def _receipt_with(self, mutate, name="receipt.json"):
        data = copy.deepcopy(self.fixture)
        mutate(data)
        return _write_text_bytes(self.dir / name, _json_text(data))

    def _manifest_with(self, mutate, name="manifest.json"):
        manifest = json.loads(MANIFEST.read_bytes().decode("utf-8"))
        mutate(manifest)
        return _write_text_bytes(self.dir / name, _json_text(manifest))

    def _write_with_token(self, name, data, token):
        """Write data as JSON with the placeholder string "__TOKEN__" replaced by a raw JSON number token."""
        return _write_text_bytes(self.dir / name, _json_text(data).replace('"__TOKEN__"', token))

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

    def _untrimmed_data(self):
        """A full-format receipt: the fixture without 'trimmed' plus the other required root keys."""
        data = copy.deepcopy(self.fixture)
        data.pop("trimmed")
        data["license"] = "https://polyhaven.com/license"
        data["processor"] = {"size": 1, "sha256": "0" * 64}
        data["source_manifest"] = {"size": 1, "sha256": "1" * 64}
        data["converter_script"] = {"size": 1, "sha256": "2" * 64}
        data["leaf_fitter"].update(
            size=1,
            sha256="3" * 64,
            source={"size": 1, "sha256": "4" * 64},
            command=["fit_leaf_cards", "scratch/source-leaves.lmesh", "output/leaves.lmesh"],
            lod_policy="Retain all source leaf surfaces at each mesh LOD",
        )
        data["command_roots"] = {"source": "verified source pack/source", "output": "runtime pack"}
        data["commands"] = [["source/tree_small_02_2k.gltf", "output/tree.lmesh", "--primitive", "0"]]
        return data


class PositiveTests(ReceiptTestCase):
    def test_fixture_passes(self):
        code, out, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST)])
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")

    def test_sphere_at_exact_bound_is_accepted(self):
        data = copy.deepcopy(self.fixture)
        self._entry(data, LEAF_BRANCHES_LOD0)["bounding_sphere"] = ["__TOKEN__", 0, 0, 1]
        receipt = self._write_with_token("receipt-sphere-edge.json", data, "1000000000000.000000000000000000")
        code, _, err = _run(["--receipt", str(receipt), "--manifest", str(MANIFEST)])
        self.assertEqual(code, 0, err)

    def test_full_flag_is_accepted_as_alias(self):
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

    def test_emit_json_matches_committed_evidence(self):
        self.assertTrue(EVIDENCE.exists(), "docs/evidence/tree-small-02-resource-accounting.json is missing")
        target = self.dir / "accounting.json"
        code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--emit-json", str(target)])
        self.assertEqual(code, 0, err)
        self.assertEqual(target.read_bytes(), EVIDENCE.read_bytes())

    def test_check_doc_passes_for_public_page(self):
        code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--check-doc", str(DOC)])
        self.assertEqual(code, 0, err)

    def test_doc_table_has_header_and_nine_mesh_rows(self):
        accounting = checker.build_accounting(self.fixture, FIXTURE.read_bytes())
        lines = checker.render_doc_table(accounting).split("\n")
        self.assertEqual(lines[0], "| Part | LOD | Vertices | Triangles | File bytes |")
        self.assertEqual(len([line for line in lines if line.startswith("| ")]), 11)

    def test_untrimmed_receipt_matching_manifest_passes(self):
        receipt = _write_text_bytes(self.dir / "receipt-full.json", _json_text(self._untrimmed_data()))
        body = receipt.read_bytes()

        def mutate(manifest):
            for entry in manifest["files"]:
                if entry["path"] == "conversion-receipt.json":
                    entry["size"] = len(body)
                    entry["sha256"] = hashlib.sha256(body).hexdigest()

        manifest = self._manifest_with(mutate)
        code, _, err = _run(["--receipt", str(receipt), "--manifest", str(manifest)])
        self.assertEqual(code, 0, err)


class NegativeTests(ReceiptTestCase):
    def test_wrong_schema(self):
        self._expect_failure(lambda d: d.update(schema="luminumbra.game.asset-conversion.v0"), "unknown schema")

    def test_wrong_engine_revision(self):
        self._expect_failure(lambda d: d.update(engine_revision="0" * 40), "does not match pinned")

    def test_seventeen_files(self):
        self._expect_failure(lambda d: d["files"].pop(), "files has 17 entries, expected 18")

    def test_unknown_root_key(self):
        self._expect_failure(lambda d: d.update(extra=1), "unknown key 'extra'")

    def test_unknown_result_key(self):
        self._expect_failure(lambda d: d["leaf_fitter"]["result"].update(extra=1), "unknown key 'extra'")

    def test_unknown_file_key(self):
        self._expect_failure(lambda d: self._entry(d, LEAF_BRANCHES_LOD0).update(extra=1), "unknown key 'extra'")

    def test_unknown_key_in_leaf_fitter_source(self):
        self._expect_failure(
            lambda d: d["leaf_fitter"].update(source={"size": 1, "sha256": "0" * 64, "extra": 1}),
            "unknown key 'extra'",
        )

    def test_leaf_fitter_source_missing_sha256(self):
        self._expect_failure(lambda d: d["leaf_fitter"].update(source={"size": 1}), "missing key 'sha256'")

    def test_unknown_key_in_manifest_member(self):
        def mutate(manifest):
            for entry in manifest["files"]:
                if entry["path"] == LEAF_BRANCHES_LOD0:
                    entry["extra"] = 1

        manifest = self._manifest_with(mutate)
        code, out, err = _run(["--receipt", str(FIXTURE), "--manifest", str(manifest)])
        self.assertEqual(code, 1, err)
        self.assertIn("unknown key 'extra'", err)
        self.assertEqual(out, "")

    def test_unknown_key_in_manifest_root(self):
        manifest = self._manifest_with(lambda m: m.update(extra=1))
        code, out, err = _run(["--receipt", str(FIXTURE), "--manifest", str(manifest)])
        self.assertEqual(code, 1, err)
        self.assertIn("unknown key 'extra'", err)
        self.assertEqual(out, "")

    def test_unknown_key_in_manifest_archive(self):
        manifest = self._manifest_with(lambda m: m["archive"].update(extra=1))
        code, out, err = _run(["--receipt", str(FIXTURE), "--manifest", str(manifest)])
        self.assertEqual(code, 1, err)
        self.assertIn("unknown key 'extra'", err)
        self.assertEqual(out, "")

    def test_huge_integer_bounding_sphere_in_receipt_is_controlled(self):
        def mutate(data):
            self._entry(data, LEAF_BRANCHES_LOD0)["bounding_sphere"] = [10**400, 0, 0, 1]

        receipt = self._receipt_with(mutate)
        code, out, err = _run(["--receipt", str(receipt), "--manifest", str(MANIFEST)])
        self.assertEqual(code, 1, err)
        self.assertNotIn("Traceback", err)

    def test_huge_integer_bounding_sphere_in_manifest_is_controlled(self):
        def mutate(manifest):
            for entry in manifest["files"]:
                if entry["path"] == LEAF_BRANCHES_LOD0:
                    entry["bounding_sphere"] = [10**400, 0, 0, 1]

        manifest = self._manifest_with(mutate)
        code, out, err = _run(["--receipt", str(FIXTURE), "--manifest", str(manifest)])
        self.assertEqual(code, 1, err)
        self.assertNotIn("Traceback", err)

    def test_deeply_nested_receipt_is_controlled(self):
        receipt = _write_text_bytes(self.dir / "deep.json", "[" * 200000 + "]" * 200000 + "\n")
        code, out, err = _run(["--receipt", str(receipt), "--manifest", str(MANIFEST)])
        self.assertEqual(code, 1, err)
        self.assertIn("json nesting is too deep", err)
        self.assertNotIn("Traceback", err)

    def test_deeply_nested_manifest_is_controlled(self):
        manifest = _write_text_bytes(self.dir / "deep-manifest.json", "[" * 200000 + "]" * 200000 + "\n")
        code, out, err = _run(["--receipt", str(FIXTURE), "--manifest", str(manifest)])
        self.assertEqual(code, 1, err)
        self.assertIn("json nesting is too deep", err)
        self.assertNotIn("Traceback", err)

    def test_negative_residual_refused(self):
        self._expect_failure(
            lambda d: d["leaf_fitter"]["result"].update(maximum_relative_fit_error=-1),
            "maximum_relative_fit_error -1 is negative",
        )

    def test_residual_just_above_bound_refused(self):
        self._expect_failure(
            lambda d: d["leaf_fitter"]["result"].update(maximum_relative_fit_error=0.2000001),
            "maximum_relative_fit_error 0.2000001 exceeds bound 0.20",
        )

    def test_oversized_mesh_count_in_receipt_is_controlled(self):
        data = copy.deepcopy(self.fixture)
        self._entry(data, LEAF_BRANCHES_LOD0)["vertices"] = "__TOKEN__"
        receipt = self._write_with_token("receipt-huge-count.json", data, "9" * 4300)
        code, out, err = _run(["--receipt", str(receipt), "--manifest", str(MANIFEST)])
        self.assertEqual(code, 1, err)
        self.assertIn("%s: vertices must be a non-negative integer no larger than" % LEAF_BRANCHES_LOD0, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(out, "")

    def test_oversized_mesh_count_in_manifest_is_controlled(self):
        manifest = json.loads(MANIFEST.read_bytes().decode("utf-8"))
        for entry in manifest["files"]:
            if entry["path"] == LEAF_BRANCHES_LOD0:
                entry["triangles"] = "__TOKEN__"
        path = self._write_with_token("manifest-huge-count.json", manifest, "9" * 4300)
        code, out, err = _run(["--receipt", str(FIXTURE), "--manifest", str(path)])
        self.assertEqual(code, 1, err)
        self.assertIn("triangles must be a non-negative integer no larger than", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(out, "")

    def test_sphere_rounding_trap_in_receipt_is_refused(self):
        data = copy.deepcopy(self.fixture)
        self._entry(data, LEAF_BRANCHES_LOD0)["bounding_sphere"] = ["__TOKEN__", 0, 0, 1]
        receipt = self._write_with_token("receipt-sphere-trap.json", data, "1000000000000.000000000000000001")
        code, out, err = _run(["--receipt", str(receipt), "--manifest", str(MANIFEST)])
        self.assertEqual(code, 1, err)
        self.assertIn("%s: bounding_sphere must be four finite numbers" % LEAF_BRANCHES_LOD0, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(out, "")

    def test_sphere_rounding_trap_in_manifest_is_refused(self):
        manifest = json.loads(MANIFEST.read_bytes().decode("utf-8"))
        for entry in manifest["files"]:
            if entry["path"] == LEAF_BRANCHES_LOD0:
                entry["bounding_sphere"] = ["__TOKEN__", 0, 0, 1]
        path = self._write_with_token("manifest-sphere-trap.json", manifest, "1000000000000.000000000000000001")
        code, out, err = _run(["--receipt", str(FIXTURE), "--manifest", str(path)])
        self.assertEqual(code, 1, err)
        self.assertIn("bounding_sphere must be four finite numbers", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(out, "")

    def test_huge_plain_decimal_sphere_in_receipt_is_refused(self):
        data = copy.deepcopy(self.fixture)
        self._entry(data, LEAF_BRANCHES_LOD0)["bounding_sphere"] = ["__TOKEN__", 0, 0, 1]
        receipt = self._write_with_token("receipt-sphere-huge.json", data, "1" + "0" * 1000000 + ".0")
        code, out, err = _run(["--receipt", str(receipt), "--manifest", str(MANIFEST)])
        self.assertEqual(code, 1, err)
        self.assertIn("%s: bounding_sphere must be four finite numbers" % LEAF_BRANCHES_LOD0, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(out, "")

    def test_huge_plain_decimal_sphere_in_manifest_is_refused(self):
        manifest = json.loads(MANIFEST.read_bytes().decode("utf-8"))
        for entry in manifest["files"]:
            if entry["path"] == LEAF_BRANCHES_LOD0:
                entry["bounding_sphere"] = ["__TOKEN__", 0, 0, 1]
        path = self._write_with_token("manifest-sphere-huge.json", manifest, "1" + "0" * 1000000 + ".0")
        code, out, err = _run(["--receipt", str(FIXTURE), "--manifest", str(path)])
        self.assertEqual(code, 1, err)
        self.assertIn("bounding_sphere must be four finite numbers", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(out, "")

    def test_missing_path_in_manifest(self):
        manifest = self._manifest_with(lambda m: m.update(files=[e for e in m["files"] if e["path"] != LEAF_LOD1]))
        code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(manifest)])
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

    def test_compensating_change_fails_manifest_vertices(self):
        def mutate(data):
            entry = self._entry(data, LEAF_BRANCHES_LOD0)
            entry["vertices"] = 31954
            entry["triangles"] = 45992

        self._expect_failure(mutate, "vertices 31954 does not match manifest 31951")

    def test_leaf_triangles_60499(self):
        def mutate(data):
            self._entry(data, LEAF_LOD1)["triangles"] = 60499

        self._expect_failure(mutate, "triangles 60499, expected 60500")

    def test_leaf_surfaces_30249(self):
        def mutate(data):
            data["leaf_fitter"]["result"]["leaf_surfaces"] = 30249

        self._expect_failure(mutate, "leaf_surfaces 30249, expected 30250")

    def test_leaf_surfaces_float_is_not_an_integer(self):
        def mutate(data):
            data["leaf_fitter"]["result"]["leaf_surfaces"] = 30250.0

        self._expect_failure(mutate, "leaf_fitter.result.leaf_surfaces must be an integer")

    def test_leaf_triangles_boolean_is_not_an_integer(self):
        def mutate(data):
            data["leaf_fitter"]["result"]["triangles"] = True

        self._expect_failure(mutate, "leaf_fitter.result.triangles must be an integer")

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

    def test_check_doc_rejects_stale_block(self):
        text = DOC.read_text(encoding="utf-8").replace("| trunk | 2 | 884 | 998 | 40292 |", "| trunk | 2 | 885 | 998 | 40292 |")
        stale = _write_text_bytes(self.dir / "doc.md", text)
        code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--check-doc", str(stale)])
        self.assertEqual(code, 1)
        self.assertIn("does not match the generated table", err)

    def test_check_doc_requires_markers(self):
        bare = _write_text_bytes(self.dir / "bare.md", "no markers here\n")
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

    def test_untrimmed_receipt_with_different_bytes_fails(self):
        receipt = _write_text_bytes(self.dir / "receipt-full.json", _json_text(self._untrimmed_data()))
        code, out, err = _run(["--receipt", str(receipt), "--manifest", str(MANIFEST)])
        self.assertEqual(code, 1, err)
        self.assertIn("receipt sha256 does not match manifest entry", err)
        self.assertEqual(out, "")

    def test_untrimmed_receipt_missing_full_key_fails(self):
        data = self._untrimmed_data()
        data.pop("commands")
        receipt = _write_text_bytes(self.dir / "receipt-partial.json", _json_text(data))
        code, _, err = _run(["--receipt", str(receipt), "--manifest", str(MANIFEST)])
        self.assertEqual(code, 1)
        self.assertIn("missing key 'commands'", err)


class AccountingValidatorTests(ReceiptTestCase):
    def _accounting(self):
        receipt = json.loads(FIXTURE.read_bytes().decode("utf-8"))
        return checker.build_accounting(receipt, FIXTURE.read_bytes())

    def test_built_accounting_is_valid(self):
        self.assertEqual(resource_accounting.validate("acc.json", self._accounting()), [])

    def test_measured_entry_requires_evidence_sha256(self):
        obj = self._accounting()
        obj["measured"] = [{"metric": "vram", "value": 1}]
        problems = resource_accounting.validate("acc.json", obj)
        self.assertTrue(any("missing key 'evidence_sha256'" in p for p in problems), problems)

    def test_measured_value_must_be_integer(self):
        obj = self._accounting()
        obj["measured"] = [{"evidence_sha256": "0" * 64, "value": True}]
        problems = resource_accounting.validate("acc.json", obj)
        self.assertTrue(any("value must be an integer" in p for p in problems), problems)

    def test_totals_must_match_lists(self):
        obj = self._accounting()
        obj["totals"]["texture_file_bytes"] += 1
        problems = resource_accounting.validate("acc.json", obj)
        self.assertTrue(any("texture_file_bytes" in p for p in problems), problems)

    def test_leaf_surfaces_total_is_pinned(self):
        obj = self._accounting()
        obj["totals"]["leaf_surfaces"] = 1
        problems = resource_accounting.validate("acc.json", obj)
        self.assertTrue(any("leaf_surfaces" in p and "must be 30250" in p for p in problems), problems)

    def test_emit_json_to_missing_directory_is_a_controlled_failure(self):
        target = self.dir / "no-such-dir" / "acc.json"
        code, out, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--emit-json", str(target)])
        self.assertEqual(code, 1)
        self.assertIn("cannot write", err)
        self.assertNotIn("Traceback", err)

    def test_wrong_schema_rejected(self):
        obj = self._accounting()
        obj["schema"] = "luminumbra.game.other.v1"
        self.assertEqual(len(resource_accounting.validate("acc.json", obj)), 1)

    def test_scope_constant_matches_committed_evidence(self):
        committed = json.loads(EVIDENCE.read_bytes().decode("utf-8"))
        self.assertEqual(resource_accounting.SCOPE, committed["scope"])

    def test_scope_must_be_the_mandated_string(self):
        cases = {
            "null": None,
            "object": {},
            "empty string": "",
            "unrelated string": "tree-small-02 pack only",
        }
        for label, bad in cases.items():
            with self.subTest(case=label):
                obj = self._accounting()
                obj["scope"] = bad
                problems = resource_accounting.validate("acc.json", obj)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("scope", problems[0])

    def test_part_of_unhashable_type_is_a_problem(self):
        for bad in ([], {}):
            with self.subTest(part=bad):
                obj = self._accounting()
                obj["meshes"][0]["part"] = bad
                problems = resource_accounting.validate("acc.json", obj)
                self.assertTrue(any("unknown part" in p for p in problems), problems)

    def test_duplicate_path_with_adjusted_totals(self):
        obj = self._accounting()
        duplicate = copy.deepcopy(obj["meshes"][0])
        obj["meshes"].append(duplicate)
        obj["totals"]["mesh_file_bytes"] += duplicate["file_bytes"]
        obj["totals"]["mesh_triangles_by_lod"]["lod%d" % duplicate["lod"]] += duplicate["triangles"]
        problems = resource_accounting.validate("acc.json", obj)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("duplicate path %s" % duplicate["path"], problems[0])

    def test_path_with_backslash_or_leading_slash_rejected(self):
        for bad in ("data\\models\\x.lmesh", "/data/models/x.lmesh", ""):
            with self.subTest(path=bad):
                obj = self._accounting()
                obj["textures"][0]["path"] = bad
                problems = resource_accounting.validate("acc.json", obj)
                self.assertTrue(any("path" in p for p in problems), problems)

    def test_windows_reserved_device_name_rejected(self):
        for bad in ("data/CON.lmesh", "data/com1.tar.gz", "data/Lpt9/x.ltex"):
            with self.subTest(path=bad):
                obj = self._accounting()
                obj["textures"][0]["path"] = bad
                problems = resource_accounting.validate("acc.json", obj)
                self.assertTrue(any("reserved device name" in p for p in problems), problems)

    def test_windows_invalid_characters_rejected(self):
        for bad in ("data/x?.ltex", "data/a<b.ltex", 'data/a"b.ltex', "data/a|b.ltex", "data/a\x01b.ltex"):
            with self.subTest(path=bad):
                obj = self._accounting()
                obj["textures"][0]["path"] = bad
                problems = resource_accounting.validate("acc.json", obj)
                self.assertTrue(any("invalid on Windows" in p for p in problems), problems)

    def test_trailing_dot_or_space_component_rejected(self):
        for bad in ("data/x.ltex.", "data/x.ltex ", "data/models /x.ltex"):
            with self.subTest(path=bad):
                obj = self._accounting()
                obj["textures"][0]["path"] = bad
                problems = resource_accounting.validate("acc.json", obj)
                self.assertTrue(any("dot or space" in p for p in problems), problems)

    def test_case_only_alias_duplicate_rejected(self):
        obj = self._accounting()
        alias = copy.deepcopy(obj["meshes"][0])
        alias["path"] = alias["path"].upper()
        obj["meshes"].append(alias)
        obj["totals"]["mesh_file_bytes"] += alias["file_bytes"]
        obj["totals"]["mesh_triangles_by_lod"]["lod%d" % alias["lod"]] += alias["triangles"]
        problems = resource_accounting.validate("acc.json", obj)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("duplicate path %s" % alias["path"], problems[0])

    def test_malformed_check_json_is_a_controlled_failure(self):
        for bad in ([], {}):
            with self.subTest(part=bad):
                obj = self._accounting()
                obj["meshes"][0]["part"] = bad
                target = _write_text_bytes(self.dir / "acc.json", _json_text(obj))
                code, _, err = _run(["--receipt", str(FIXTURE), "--manifest", str(MANIFEST), "--check-json", str(target)])
                self.assertEqual(code, 1)
                self.assertIn("unknown part", err)


if __name__ == "__main__":
    unittest.main()
