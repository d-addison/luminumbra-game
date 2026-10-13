"""H2's extension of the H1 captured-byte transaction and receipt boundary."""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import export_game_data as exporter  # noqa: E402
from lumlib.engine_inventory import INVENTORY_PATH, load_inventory  # noqa: E402
from lumlib.schema import SchemaError  # noqa: E402
from validators import items  # noqa: E402

FIXTURES = ROOT / "tests/fixtures/items"
GAME = "d912c04aa2453d995d5c0c517ca1f66d860c7e46"


class ItemsExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "source"
        self.output = self.base / "output"
        self.engine = load_inventory(ROOT)["engine_revision"]
        for source in (INVENTORY_PATH, *(row[0] for row in exporter.MAPPINGS)):
            target = self.root / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, target)
        self.path = self.root / items.ITEMS_PATH

    def export(self):
        return exporter.export(self.root, self.output, engine_revision=self.engine, game_revision=GAME)

    def assert_no_output(self):
        self.assertFalse(os.path.lexists(self.output))
        self.assertEqual(list(self.base.glob(".h1-export-*")), [])

    def test_exact_item_bytes_receipt_and_only_three_runtime_files(self):
        raw = (b'{ "items": [{"payload":0, "id":"farming-seed", "despawn_after":900}], '
               b'"schema":"luminumbra.game.items.v1" }\n')
        self.path.write_bytes(raw)
        # Author-only files are never candidates for runtime copying.
        (self.root / "content/items/identity.json").write_bytes(b'{}\n')
        (self.root / "acceptance.json").write_bytes(b'{}\n')
        receipt = self.export()
        self.assertEqual(receipt["schema"], "luminumbra.game.h1-export-receipt.v1")
        self.assertEqual(receipt["semantic_encoding"], "canonical-integer-json-fnv1a64.v1")
        self.assertEqual(receipt["game_revision"], GAME)
        self.assertEqual(receipt["engine_revision"], self.engine)
        self.assertEqual(receipt["inventory_sha256"],
                         hashlib.sha256((self.root / INVENTORY_PATH).read_bytes()).hexdigest())
        entry = next(row for row in receipt["files"] if row["source"] == items.ITEMS_PATH)
        expected_canonical = (b'{"items":[{"despawn_after":900,"id":"farming-seed","payload":0}],'
                              b'"schema":"luminumbra.game.items.v1"}')
        checksum = 14695981039346656037
        for byte in expected_canonical:
            checksum = ((checksum ^ byte) * 1099511628211) % (1 << 64)
        self.assertEqual(entry, {"source": items.ITEMS_PATH, "destination": "data/common/items/items.json",
                                 "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                                 "semantic_identity": "%016x" % checksum})
        runtime = self.output / "bundle/runtime"
        self.assertEqual((runtime / entry["destination"]).read_bytes(), raw)
        self.assertEqual({p.relative_to(runtime).as_posix() for p in runtime.rglob("*") if p.is_file()},
                         {"data/common/sim/distant_policy.json", "data/common/sim/region_population.json",
                          "data/common/items/items.json"})
        self.assertEqual(json.loads((self.output / "bundle/export-receipt.json").read_bytes()), receipt)
        self.assertEqual(list(self.base.glob(".h1-export-*")), [])

    def test_all_sources_captured_once_and_item_mutation_cannot_change_export(self):
        captured = {source: (self.root / source).read_bytes() for source, _, _ in exporter.MAPPINGS}
        original_parse = items.parse_items
        original_capture = exporter.capture_source
        def mutate_after_parse(raw, inventory):
            candidate = original_parse(raw, inventory)
            for source in (INVENTORY_PATH, *captured):
                (self.root / source).write_bytes(b'changed after capture\n')
            return candidate
        mappings = tuple((source, dest, mutate_after_parse if source == items.ITEMS_PATH else parser)
                         for source, dest, parser in exporter.MAPPINGS)
        with patch.object(exporter, "capture_source", wraps=original_capture) as capture, \
                patch.object(exporter, "MAPPINGS", mappings):
            receipt = self.export()
        self.assertEqual([call.args[1] for call in capture.call_args_list], [INVENTORY_PATH, *captured])
        for row in receipt["files"]:
            raw = captured[row["source"]]
            self.assertEqual((self.output / "bundle/runtime" / row["destination"]).read_bytes(), raw)
            self.assertEqual(row["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(row["bytes"], len(raw))

    def test_semantic_identity_ignores_formatting_and_keys_but_covers_content(self):
        first = self.export()
        original = next(row for row in first["files"] if row["source"] == items.ITEMS_PATH)
        shutil.rmtree(self.output)
        obj = json.loads(self.path.read_bytes())
        self.path.write_bytes((json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode())
        formatted = next(row for row in self.export()["files"] if row["source"] == items.ITEMS_PATH)
        self.assertEqual(original["semantic_identity"], formatted["semantic_identity"])
        self.assertNotEqual(original["sha256"], formatted["sha256"])
        shutil.rmtree(self.output)
        obj["items"][0]["despawn_after"] = 901
        self.path.write_bytes((json.dumps(obj) + "\n").encode())
        changed = next(row for row in self.export()["files"] if row["source"] == items.ITEMS_PATH)
        self.assertNotEqual(original["semantic_identity"], changed["semantic_identity"])

    def test_item_refusal_precedes_any_output_mutation(self):
        for fixture in sorted(FIXTURES.glob("invalid-*.json")):
            self.path.write_bytes(fixture.read_bytes())
            with self.subTest(fixture=fixture.name):
                with patch.object(exporter.tempfile, "TemporaryDirectory") as staging:
                    with self.assertRaises(SchemaError):
                        self.export()
                    staging.assert_not_called()
                self.assert_no_output()

    def test_item_encoding_size_and_required_file_refusals(self):
        raw = self.path.read_bytes()
        for bad in (b'broken\n', raw[:-1], raw.replace(b'\n', b'\r\n'), b'\xef\xbb\xbf' + raw,
                    b'\xff\n', raw + b' ' * items.MAX_ITEMS_BYTES):
            self.path.write_bytes(bad)
            with self.assertRaises(SchemaError):
                self.export()
            self.assert_no_output()
        self.path.unlink()
        with self.assertRaisesRegex(SchemaError, "missing file"):
            self.export()
        self.assert_no_output()
        self.path.mkdir()
        with self.assertRaisesRegex(SchemaError, "regular file"):
            self.export()
        self.assert_no_output()
        self.path.rmdir()
        self.path.write_bytes(raw)
        original_open = os.open
        def deny_item(path, flags):
            if Path(path) == self.path:
                raise PermissionError("denied")
            return original_open(path, flags)
        with patch("lumlib.engine_inventory.os.open", side_effect=deny_item):
            with self.assertRaisesRegex(SchemaError, "cannot read"):
                self.export()
        self.assert_no_output()

    @unittest.skipIf(os.name == "nt", "symlink privilege is not assumed on Windows CI")
    def test_item_symlinks_and_nonregular_files_refuse(self):
        raw = self.path.read_bytes()
        self.path.unlink()
        other = self.base / "other.json"
        other.write_bytes(raw)
        self.path.symlink_to(other)
        with self.assertRaisesRegex(SchemaError, "symlink"):
            self.export()
        self.assert_no_output()
        self.path.unlink()
        os.mkfifo(self.path)
        with self.assertRaisesRegex(SchemaError, "regular file"):
            self.export()
        self.assert_no_output()
        self.path.unlink()
        self.path.write_bytes(raw)
        directory = self.path.parent
        retained = directory.with_name("retained-items")
        directory.rename(retained)
        directory.symlink_to(retained, target_is_directory=True)
        with self.assertRaisesRegex(SchemaError, "symlink"):
            self.export()
        self.assert_no_output()

    def test_item_staging_failure_cleans_whole_bundle(self):
        original_write = Path.write_bytes
        def refuse(path, raw):
            if path.name == "items.json" and ".h1-export-" in str(path):
                raise OSError("item stage refused")
            return original_write(path, raw)
        with patch.object(Path, "write_bytes", refuse):
            with self.assertRaisesRegex(OSError, "item stage refused"):
                self.export()
        self.assert_no_output()

    def test_bundle_publication_failure_and_foreign_content_preservation(self):
        with patch.object(exporter.os, "rename", side_effect=OSError("publication refused")):
            with self.assertRaises(OSError):
                self.export()
        self.assert_no_output()
        def refuse_with_foreign(source, target):
            (self.output / "foreign").write_bytes(b"retain this")
            raise OSError("publication refused")
        with patch.object(exporter.os, "rename", side_effect=refuse_with_foreign):
            with self.assertRaises(OSError):
                self.export()
        self.assertEqual((self.output / "foreign").read_bytes(), b"retain this")
        self.assertFalse((self.output / "bundle").exists())
        self.assertEqual(list(self.base.glob(".h1-export-*")), [])

    def test_successful_output_remains_unchanged_on_subsequent_refusal(self):
        self.export()
        before = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        self.path.write_bytes((FIXTURES / "invalid-collision.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.export()
        after = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
