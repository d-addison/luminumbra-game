"""Captured H1 export transaction, exact receipts and failure preservation."""

import contextlib
import hashlib
import io
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
from lumlib import engine_inventory as inv  # noqa: E402
from lumlib.schema import SchemaError  # noqa: E402
from validators import simulation as sim  # noqa: E402
import validate_content  # noqa: E402

ENGINE = "4c15419e9ba064c94e2933df73106991d92f1623"
GAME = "7a54e52e34dd0c29504907ca7da9c4c45a5a1835"


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "source"
        self.output = self.base / "output"
        for source in (inv.INVENTORY_PATH, sim.POLICY_PATH, sim.POPULATION_PATH):
            path = self.root / source
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, path)

    def export(self, **kwargs):
        return exporter.export(self.root, self.output, engine_revision=kwargs.get("engine_revision", ENGINE),
                               game_revision=kwargs.get("game_revision", GAME))

    def rewrite(self, path, transform):
        full = self.root / path
        obj = json.loads(full.read_bytes())
        transform(obj)
        full.write_bytes((json.dumps(obj, indent=2) + '\n').encode())

    def test_exact_byte_receipts_semantic_identity_and_runtime_boundary(self):
        # Legal raw formatting differs from canonical JSON; runtime must retain it.
        path = self.root / sim.POLICY_PATH
        raw = b'{ "plant_species" : {}, "creature_species": {}, "schema":"luminumbra.distant_policy.v1" }\n'
        path.write_bytes(raw)
        receipt = self.export()
        self.assertEqual(receipt["engine_revision"], ENGINE)
        self.assertEqual(receipt["game_revision"], GAME)
        self.assertEqual(receipt["inventory_sha256"], hashlib.sha256((self.root / inv.INVENTORY_PATH).read_bytes()).hexdigest())
        self.assertEqual(json.loads((self.output / "bundle/export-receipt.json").read_bytes()), receipt)
        runtime = self.output / "bundle/runtime"
        self.assertEqual({p.relative_to(runtime).as_posix() for p in runtime.rglob('*') if p.is_file()},
                         {entry["destination"] for entry in receipt["files"]})
        for entry in receipt["files"]:
            original = (self.root / entry["source"]).read_bytes()
            self.assertEqual((runtime / entry["destination"]).read_bytes(), original)
            self.assertEqual(entry["bytes"], len(original))
            self.assertEqual(entry["sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(entry["semantic_identity"], sim.semantic_identity(json.loads(original)))
        self.assertEqual(receipt["files"][0]["semantic_identity"], sim.semantic_identity(sim.empty_policy()))
        self.assertEqual(list(self.base.glob('.h1-export-*')), [])

    def test_each_source_captured_once_and_never_reread_after_validation(self):
        seen = []
        original_capture = exporter.capture_source
        original_parse = sim.parse_population
        def capture(root, source):
            seen.append(source)
            return original_capture(root, source)
        def parse(raw, inventory):
            result = original_parse(raw, inventory)
            # Alter both sources once all captures have occurred. Neither output nor
            # receipt may follow the new source bytes.
            for path in (sim.POLICY_PATH, sim.POPULATION_PATH):
                (self.root / path).write_bytes(b'mutated after capture\n')
            return result
        sources = {source: (self.root / source).read_bytes() for source, _, _ in exporter.MAPPINGS}
        mapping = (exporter.MAPPINGS[0], (sim.POPULATION_PATH, exporter.MAPPINGS[1][1], parse))
        with patch.object(exporter, "capture_source", side_effect=capture), patch.object(exporter, "MAPPINGS", mapping):
            receipt = self.export()
        self.assertEqual(seen, [inv.INVENTORY_PATH, sim.POLICY_PATH, sim.POPULATION_PATH])
        for entry in receipt["files"]:
            self.assertEqual((self.output / 'bundle/runtime' / entry['destination']).read_bytes(), sources[entry['source']])
            self.assertEqual(entry["sha256"], hashlib.sha256(sources[entry["source"]]).hexdigest())

    def test_cross_reference_and_encoding_refusal_before_publication(self):
        scenarios = [
            (sim.POPULATION_PATH, lambda o:o['rules'][0].update(species='unknown')),
            (sim.POPULATION_PATH, lambda o:o['rules'][0].update(species='wheat')),
            (sim.POPULATION_PATH, lambda o:o['rules'][0].update(biomes=['unknown'])),
            (sim.POPULATION_PATH, lambda o:o['rules'][0].update(count=True)),
            (sim.POLICY_PATH, lambda o:o['plant_species'].update(unknown={})),
            (sim.POLICY_PATH, lambda o:o.update(schema='luminumbra.distant_policy.v2')),
        ]
        for path, transform in scenarios:
            original = (self.root / path).read_bytes()
            self.rewrite(path, transform)
            with self.subTest(path=path):
                with self.assertRaises(ValueError): self.export()
                self.assertFalse(self.output.exists())
                self.assertEqual(list(self.base.glob('.h1-export-*')), [])
            (self.root / path).write_bytes(original)
        for path in (sim.POLICY_PATH, sim.POPULATION_PATH):
            full = self.root / path; original = full.read_bytes()
            for raw in (b'broken\n', original[:-1], original.replace(b'\n', b'\r\n'),
                        b'\xef\xbb\xbf'+original, b'\xff\n', original+b' '*inv.MAX_DOCUMENT_BYTES):
                full.write_bytes(raw)
                with self.assertRaises(ValueError): self.export()
                self.assertFalse(self.output.exists())
            full.write_bytes(original)

    def test_nonempty_policy_fixture_cannot_ship_or_export(self):
        shutil.copyfile(ROOT / 'tests/fixtures/simulation/valid-policy.json', self.root / sim.POLICY_PATH)
        with self.assertRaisesRegex(ValueError, "remain empty"): self.export()
        self.assertFalse(self.output.exists())

    def test_missing_nonregular_symlink_sources_and_inventory_refuse(self):
        path = self.root / sim.POLICY_PATH
        original = path.read_bytes(); path.unlink()
        with self.assertRaises(SchemaError): self.export()
        path.mkdir()
        with self.assertRaises(SchemaError): self.export()
        path.rmdir(); path.write_bytes(original)
        if os.name != 'nt':
            other = self.base / 'other.json'; other.write_bytes(original)
            path.unlink(); path.symlink_to(other)
            with self.assertRaisesRegex(SchemaError, "symlink"): self.export()
            path.unlink(); os.mkfifo(path)
            with self.assertRaisesRegex(SchemaError, "regular"): self.export()
            path.unlink(); path.write_bytes(original)
            directory = self.root / 'content/sim'
            saved = self.root / 'content/original-sim'; directory.rename(saved); directory.symlink_to(saved, target_is_directory=True)
            with self.assertRaisesRegex(SchemaError, "symlink"): self.export()
        self.assertFalse(self.output.exists())
        self.rewrite(inv.INVENTORY_PATH, lambda o:o['plants'][0].update(species_id=0))
        with self.assertRaisesRegex(SchemaError, "ID mismatch"): self.export()

    def test_existing_output_file_directory_symlink_and_success_are_unchanged(self):
        self.output.mkdir(); marker = self.output / 'keep'; marker.write_bytes(b'foreign')
        with self.assertRaisesRegex(ValueError, "already exists"): self.export()
        self.assertEqual(marker.read_bytes(), b'foreign'); marker.unlink(); self.output.rmdir()
        self.output.write_bytes(b'foreign')
        with self.assertRaises(ValueError): self.export()
        self.assertEqual(self.output.read_bytes(), b'foreign'); self.output.unlink()
        if os.name != 'nt':
            self.output.symlink_to(self.base / 'missing')
            with self.assertRaises(ValueError): self.export()
            self.assertTrue(self.output.is_symlink()); self.output.unlink()
        self.export()
        before = {p.relative_to(self.output):p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        with self.assertRaises(ValueError): self.export()
        self.assertEqual(before, {p.relative_to(self.output):p.read_bytes() for p in self.output.rglob('*') if p.is_file()})

    def test_independent_pins_required_and_inventory_revision_match(self):
        for kind, value in [('engine_revision', 'bad'), ('game_revision', ''),
                            ('engine_revision', 'f'*40), ('game_revision', True)]:
            with self.assertRaises(ValueError): self.export(**{kind:value})
            self.assertFalse(self.output.exists())
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            result = exporter.main(['--root', str(self.root), '--output', str(self.output),
                                    '--engine-revision', ENGINE, '--game-revision', 'bad\n\x1b'])
        self.assertEqual(result, 1)
        self.assertEqual(len(output.getvalue().splitlines()), 1)

    def test_staging_failure_never_creates_destination(self):
        original_write = Path.write_bytes
        def fail(path, raw):
            if path.name == 'region_population.json' and '.h1-export-' in str(path):
                raise OSError('disk refusal')
            return original_write(path, raw)
        with patch.object(Path, 'write_bytes', fail):
            with self.assertRaises(OSError): self.export()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob('.h1-export-*')), [])

    def test_exclusive_claim_survives_racing_exporter(self):
        original_mkdir = Path.mkdir
        def race(path, *args, **kwargs):
            if path == self.output:
                original_mkdir(path)
                (path / 'foreign').write_bytes(b'competing output')
            return original_mkdir(path, *args, **kwargs)
        with patch.object(Path, 'mkdir', race):
            with self.assertRaises(FileExistsError): self.export()
        self.assertEqual((self.output/'foreign').read_bytes(), b'competing output')
        self.assertFalse((self.output/'bundle').exists())
        self.assertEqual(list(self.base.glob('.h1-export-*')), [])

    def test_publish_failure_removes_only_owned_empty_reservation(self):
        with patch.object(exporter.os, 'rename', side_effect=OSError('publication refusal')):
            with self.assertRaises(OSError): self.export()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob('.h1-export-*')), [])
        def fail_with_foreign(source, target):
            (self.output / 'foreign').write_bytes(b'concurrent writer')
            raise OSError('publication refusal')
        with patch.object(exporter.os, 'rename', side_effect=fail_with_foreign):
            with self.assertRaises(OSError): self.export()
        self.assertEqual((self.output/'foreign').read_bytes(), b'concurrent writer')
        self.assertFalse((self.output/'bundle/export-receipt.json').exists())
        self.assertEqual(list(self.base.glob('.h1-export-*')), [])

    def test_replaced_reservation_is_never_deleted(self):
        retained = self.base / 'owned-reservation'
        original_rename = os.rename
        def replace_and_fail(source, target):
            original_rename(self.output, retained)
            self.output.mkdir()
            raise OSError('publication refusal')
        with patch.object(exporter.os, 'rename', side_effect=replace_and_fail):
            with self.assertRaises(OSError): self.export()
        self.assertTrue(self.output.is_dir())
        self.assertTrue(retained.is_dir())
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(list(self.base.glob('.h1-export-*')), [])

    def test_ci_discovery_uses_captured_bytes_for_final_lf_and_limit(self):
        self.assertEqual(validate_content.validate_tree(str(self.root), True, False), [])
        path = self.root / sim.POLICY_PATH
        original = path.read_bytes(); path.write_bytes(original[:-1])
        self.assertTrue(any('final LF' in p for p in validate_content.validate_tree(str(self.root), True, False)))
        path.write_bytes(original+b' '*inv.MAX_DOCUMENT_BYTES)
        self.assertTrue(any('byte limit' in p for p in validate_content.validate_tree(str(self.root), True, False)))


if __name__ == '__main__':
    unittest.main()
