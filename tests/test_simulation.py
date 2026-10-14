"""H1 author contracts; no simulated runtime, callback or terrain qualification."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from lumlib import identity  # noqa: E402
from lumlib.engine_inventory import (load_inventory, validate_inventory,
                                     verify_engine_sources)  # noqa: E402
from lumlib.schema import SchemaError  # noqa: E402
from lumlib.species_identity import resolved_species, species_id  # noqa: E402
from validators import Context, discover  # noqa: E402
from validators import simulation as sim  # noqa: E402
import validate_content  # noqa: E402

FIXTURES = ROOT / "tests/fixtures/simulation"


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.inventory = load_inventory(ROOT)
        self.policy = json.loads((FIXTURES / "valid-policy.json").read_bytes())
        self.population = json.loads((FIXTURES / "valid-population.json").read_bytes())

    def test_shipping_and_registry(self):
        schemas, _ = discover()
        self.assertIs(schemas[sim.POLICY_SCHEMA], sim.validate_policy)
        self.assertIs(schemas[sim.POPULATION_SCHEMA], sim.validate_population)
        self.assertEqual(sim.parse_policy((ROOT / sim.POLICY_PATH).read_bytes(), self.inventory), sim.empty_policy())
        self.assertEqual(sim.parse_population((ROOT / sim.POPULATION_PATH).read_bytes(), self.inventory), self.population)
        self.assertEqual(validate_content.validate_tree(str(ROOT), True, False), [])
        ctx = Context(str(ROOT), True, False)
        self.assertIn("remain empty", sim.validate_policy(sim.POLICY_PATH, self.policy, ctx)[0])
        self.assertTrue(sim.validate_population("content/other.json", self.population, ctx))

    def test_dedicated_fixtures(self):
        for path in sorted(FIXTURES.glob("*policy*.json")):
            with self.subTest(path=path.name):
                if path.name.startswith("valid-"):
                    sim.parse_policy(path.read_bytes(), self.inventory)
                else:
                    with self.assertRaises(SchemaError):
                        sim.parse_policy(path.read_bytes(), self.inventory)
        for path in sorted(FIXTURES.glob("*population*.json")):
            with self.subTest(path=path.name):
                if path.name.startswith("valid-"):
                    sim.parse_population(path.read_bytes(), self.inventory)
                else:
                    with self.assertRaises(SchemaError):
                        sim.parse_population(path.read_bytes(), self.inventory)

    def test_every_policy_numeric_boundary_and_type(self):
        for key, species, fields in (("creature_species", "grovestrider", sim.CREATURE_FIELDS),
                                      ("plant_species", "wheat", sim.PLANT_FIELDS)):
            for field, (low, high) in fields.items():
                for value in (low, high):
                    obj = copy.deepcopy(self.policy)
                    obj[key][species][field] = value
                    with self.subTest(field=field, valid=value):
                        sim.check_policy(obj, self.inventory)
                for value in (low - 1, high + 1, True, False, None, "1", Decimal("1.0"), 1.0):
                    obj = copy.deepcopy(self.policy)
                    obj[key][species][field] = value
                    with self.subTest(field=field, invalid=value):
                        with self.assertRaises(SchemaError):
                            sim.check_policy(obj, self.inventory)
                # Token-level exponent refusal for every field.
                obj = copy.deepcopy(self.policy)
                obj[key][species][field] = 123456
                raw = (json.dumps(obj).replace('123456', '1e0') + '\n').encode()
                with self.subTest(field=field, token="1e0"):
                    with self.assertRaisesRegex(SchemaError, "exponent"):
                        sim.parse_policy(raw, self.inventory)

    def test_policy_exact_shape_at_every_level_and_transactional_refusal(self):
        for key in self.policy:
            for operation in ("missing", "extra"):
                obj = copy.deepcopy(self.policy)
                if operation == "missing":
                    del obj[key]
                else:
                    obj["extra"] = 1
                with self.assertRaises(SchemaError):
                    sim.check_policy(obj, self.inventory)
        for collection, species in (("creature_species", "grovestrider"), ("plant_species", "wheat")):
            for field in self.policy[collection][species]:
                obj = copy.deepcopy(self.policy)
                del obj[collection][species][field]
                with self.assertRaises(SchemaError):
                    sim.check_policy(obj, self.inventory)
            for value in (None, [], True, 1):
                obj = copy.deepcopy(self.policy); obj[collection] = value
                with self.assertRaises(SchemaError): sim.check_policy(obj, self.inventory)
            obj = copy.deepcopy(self.policy)
            obj[collection][species + "-typo"] = obj[collection].pop(species)
            with self.assertRaisesRegex(SchemaError, "unknown species"):
                sim.check_policy(obj, self.inventory)
        previous = sim.check_policy(copy.deepcopy(self.policy), self.inventory)
        before = copy.deepcopy(previous)
        with self.assertRaises(SchemaError):
            candidate = sim.parse_policy(b'{broken}\n', self.inventory)
            previous = candidate
        self.assertEqual(previous, before)

    def test_complete_policy_inventory_entry_bounds(self):
        obj = sim.empty_policy()
        for collection, kind, fields in (("creature_species", "creatures", sim.CREATURE_FIELDS),
                                          ("plant_species", "plants", sim.PLANT_FIELDS)):
            obj[collection] = {row["name"]: {f: low for f, (low, _) in fields.items()}
                               for row in self.inventory[kind]}
        sim.check_policy(obj, self.inventory)
        self.assertEqual(len(obj["creature_species"]), 10)
        self.assertEqual(len(obj["plant_species"]), 6)
        for key in ("creature_species", "plant_species"):
            candidate = copy.deepcopy(obj); candidate[key]["extra"] = {}
            with self.assertRaisesRegex(SchemaError, "entry limit"):
                sim.check_policy(candidate, self.inventory)

    def test_absence_malformed_nonregular_read_failure_and_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            self.assertEqual(sim.load_policy(path, self.inventory), sim.empty_policy())
            self.assertEqual(sim.semantic_identity(sim.load_policy(path, self.inventory)),
                             sim.semantic_identity(sim.empty_policy()))
            path.mkdir()
            with self.assertRaises(SchemaError): sim.load_policy(path, self.inventory)
            path.rmdir(); path.write_bytes(b'broken\n')
            with self.assertRaises(SchemaError): sim.load_policy(path, self.inventory)
            raw = (json.dumps(sim.empty_policy()) + '\n').encode()
            path.write_bytes(raw)
            with patch("lumlib.engine_inventory.os.open", side_effect=PermissionError("denied")):
                with self.assertRaisesRegex(SchemaError, "cannot read"):
                    sim.load_policy(path, self.inventory)
            for parser, good in ((sim.parse_policy, raw), (sim.parse_population, (json.dumps(self.population)+'\n').encode())):
                for bad in (b'\xef\xbb\xbf' + good, good.replace(b'\n', b'\r\n'), good[:-1], b'\xff\n',
                            good + b' ' * sim.MAX_POLICY_BYTES):
                    with self.subTest(parser=parser.__name__, length=len(bad)):
                        with self.assertRaises(SchemaError): parser(bad, self.inventory)
                exact = good[:-1] + b' ' * (sim.MAX_POLICY_BYTES - len(good)) + b'\n'
                parser(exact, self.inventory)
            path.write_bytes(raw + b' ' * sim.MAX_POLICY_BYTES)
            with self.assertRaisesRegex(SchemaError, "byte limit"):
                sim.load_policy(path, self.inventory)

    def test_population_numeric_domains(self):
        for count in (1, 8):
            for attempts in (count, 128):
                obj = copy.deepcopy(self.population)
                obj["rules"][0].update(count=count, max_attempts=attempts)
                sim.check_population(obj, self.inventory)
        for field, invalids in (("count", [0, -1, 9]), ("max_attempts", [0, 1, 129])):
            for value in invalids + [True, False, None, "2", Decimal("2.0")]:
                obj = copy.deepcopy(self.population); obj["rules"][0][field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(SchemaError): sim.check_population(obj, self.inventory)
            for token in ("2.0", "2e0"):
                raw = json.dumps(self.population).replace('"%s": %d' % (field, self.population['rules'][0][field]), '"%s": %s' % (field, token))
                with self.assertRaises(SchemaError): sim.parse_population((raw+'\n').encode(), self.inventory)

    def test_rule_order_unique_ids_ascii_length_biomes_and_creatures_only(self):
        row = self.population["rules"][0]
        for name in ("a", "a" * 64):
            obj = copy.deepcopy(self.population); obj["rules"][0]["id"] = name
            sim.check_population(obj, self.inventory)
        for name in ("", "a" * 65, "Bad", "bad_id", "é", "bad-", None, True):
            obj = copy.deepcopy(self.population); obj["rules"][0]["id"] = name
            with self.assertRaises(SchemaError): sim.check_population(obj, self.inventory)
        ordered = {"schema": sim.POPULATION_SCHEMA, "rules": [dict(row, id="a"), dict(row, id="b")]}
        before = copy.deepcopy(ordered)
        sim.check_population(ordered, self.inventory)
        self.assertEqual(ordered, before)
        for rules in ([dict(row, id="b"), dict(row, id="a")], [row, row]):
            with self.assertRaises(SchemaError): sim.check_population(dict(ordered, rules=rules), self.inventory)
        for biomes in ([], ["plains", "plains"], ["unknown"], "plains", None, [True], [{}]):
            with self.assertRaises(SchemaError):
                sim.check_population(dict(ordered, rules=[dict(row, biomes=biomes)]), self.inventory)
        for species in ("wheat", "farming-seed", "grove-strider", {}, None):
            with self.assertRaises(SchemaError):
                sim.check_population(dict(ordered, rules=[dict(row, species=species)]), self.inventory)

    def test_population_exact_keys_future_schema_duplicate_keys(self):
        for key in self.population:
            obj = copy.deepcopy(self.population); del obj[key]
            with self.assertRaises(SchemaError): sim.check_population(obj, self.inventory)
        for key in self.population["rules"][0]:
            obj = copy.deepcopy(self.population); del obj["rules"][0][key]
            with self.assertRaises(SchemaError): sim.check_population(obj, self.inventory)
        for obj in (dict(self.population, unknown=1), dict(self.population, schema=sim.POPULATION_SCHEMA[:-1]+"2"),
                    dict(self.population, rules=None)):
            with self.assertRaises(SchemaError): sim.check_population(obj, self.inventory)
        raw = json.dumps(self.population).replace('"count": 2', '"count": 2, "count": 3')
        with self.assertRaisesRegex(SchemaError, "duplicate"):
            sim.parse_population((raw+'\n').encode(), self.inventory)

    def test_rule_attempt_and_staging_caps(self):
        row = self.population["rules"][0]
        def rules(number, count):
            return {"schema": sim.POPULATION_SCHEMA, "rules": [dict(row, id="rule-%02d" % i, count=count, max_attempts=128) for i in range(number)]}
        sim.check_population(rules(32, 2), self.inventory)  # exactly 32 rules, 64 staged creatures
        sim.check_population(rules(8, 8), self.inventory)
        sim.check_population(rules(0, 1), self.inventory)
        with self.assertRaisesRegex(SchemaError, "at most 32"):
            sim.check_population(rules(33, 1), self.inventory)
        obj = rules(32, 2); obj["rules"][-1]["count"] = 3
        with self.assertRaisesRegex(SchemaError, "staging cap 64"):
            sim.check_population(obj, self.inventory)
        with self.assertRaises(SchemaError): sim.check_population(rules(9, 8), self.inventory)


class SpeciesInventoryTests(unittest.TestCase):
    def test_exact_vectors_utf8_and_zero_remap_collision(self):
        vectors = json.loads((FIXTURES / "species-vectors.json").read_bytes())["vectors"]
        for row in vectors:
            self.assertEqual(species_id(row["name"]), row["id"])
        with self.assertRaisesRegex(SchemaError, "collision"):
            resolved_species([vectors[-2]["name"], vectors[-1]["name"]])
        for name in ("", "bad\0name", None, "\ud800"):
            with self.assertRaises(SchemaError): species_id(name)
        with self.assertRaises(SchemaError): resolved_species(["wheat", "wheat"])
        # Independent byte-loop check for non-ASCII input; no normalization.
        h = 1469598103934665603
        for b in "é".encode("utf-8"): h = ((h ^ b) * 1099511628211) % (1 << 64)
        self.assertEqual(species_id("é"), ((h ^ (h >> 32)) & 65535) or 1)
        self.assertEqual(identity.FNV64_OFFSET, 14695981039346656037)

    def test_whole_inventory_collision_even_with_empty_authored_policy(self):
        inventory = load_inventory(ROOT)
        vectors = json.loads((FIXTURES / "species-vectors.json").read_bytes())["vectors"]
        for row, vector in zip(inventory["creatures"][:2], vectors[-2:]):
            row.update(name=vector["name"], species_id=1,
                       source="data/common/creatures/species/%s.json" % vector["name"])
        inventory["creatures"].sort(key=lambda row: row["name"])
        for checker, obj in ((sim.check_policy, sim.empty_policy()),
                             (sim.check_population, {"schema": sim.POPULATION_SCHEMA, "rules": []})):
            with self.assertRaisesRegex(SchemaError, "collision"): checker(obj, inventory)

    def test_pinned_names_expected_ids_and_provenance(self):
        inventory = load_inventory(ROOT)
        self.assertEqual(inventory["engine_revision"], "4c15419e9ba064c94e2933df73106991d92f1623")
        self.assertEqual([r["name"] for r in inventory["creatures"]],
                         ["ashen_corvid", "dusk_heron", "ember_skink", "glimmer_finch", "gloomstalker", "grovestrider", "lumen_moth", "mire_lurker", "ridgeback_stalker", "tide_grazer"])
        self.assertEqual([r["name"] for r in inventory["plants"]], ["frostberry", "maize", "moonpetal", "oak", "sungourd", "wheat"])
        for kind in ("creatures", "plants"):
            for row in inventory[kind]:
                self.assertEqual(species_id(row["name"]), row["species_id"])
                self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")
        broken = copy.deepcopy(inventory); broken["plants"][0]["species_id"] += 1
        with self.assertRaisesRegex(SchemaError, "ID mismatch"): validate_inventory(broken)

    def test_resolved_source_inventory_refuses_changes_and_missing_extra_files(self):
        # A portable miniature engine tree exercises the verification seam; actual
        # ds-fields verification is a separate read-only local check, never a CI dependency.
        inventory = load_inventory(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp)
            for kind in ("creatures", "plants"):
                for row in inventory[kind]:
                    path = engine / row["source"]; path.parent.mkdir(parents=True, exist_ok=True)
                    raw = (json.dumps({"id": row["name"]})+'\n').encode(); path.write_bytes(raw)
                    row["sha256"] = hashlib.sha256(raw).hexdigest()
            row = inventory["biomes"]
            raw = (json.dumps({"biomes": row["entries"]})+'\n').encode()
            (engine / row["source"]).write_bytes(raw); row["sha256"] = hashlib.sha256(raw).hexdigest()
            verify_engine_sources(inventory, engine)
            path = engine / inventory["creatures"][0]["source"]
            original = path.read_bytes(); path.write_bytes(original + b' ')
            with self.assertRaisesRegex(SchemaError, "hash mismatch"): verify_engine_sources(inventory, engine)
            path.write_bytes(original); path.unlink()
            with self.assertRaisesRegex(SchemaError, "file set changed"): verify_engine_sources(inventory, engine)
            path.write_bytes(original)
            extra = path.parent / "new.json"; extra.write_bytes(b'{}\n')
            with self.assertRaisesRegex(SchemaError, "file set changed"): verify_engine_sources(inventory, engine)


if __name__ == "__main__":
    unittest.main()
