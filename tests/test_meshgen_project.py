"""Offline G1 contracts against exact E1 bytes; no Blender or model execution."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock
import zipapp
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "authoring/meshgen"
ENGINE = ROOT / "tests/fixtures/meshgen-engine"
REVISION = "4a01f6d46a83c0e59503c3cb388ec3fbb04dc52a"
INVENTORY_SHA256 = "8035808b14b019e1ebb3bc0e74b87700d88e2d0e2b9612abe0a9a9d7db252560"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_engine_fixture(root):
    """Refuse absent/drifted contracts before importing them, never skip."""
    try:
        inventory_bytes = (root / "inventory.json").read_bytes()
        if sha(inventory_bytes) != INVENTORY_SHA256:
            raise ValueError("inventory digest mismatch")
        inventory = json.loads(inventory_bytes)
        if inventory["revision"] != REVISION:
            raise ValueError("revision mismatch")
        expected = set(inventory["files"]) | {"inventory.json", "README.md"}
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
        if actual != expected or any(p.is_symlink() for p in root.rglob("*")):
            raise ValueError("unexpected, missing or symlinked fixture member")
        for name, expected_sha in inventory["files"].items():
            if sha((root / name).read_bytes()) != expected_sha:
                raise ValueError("changed fixture member: " + name)
    except (OSError, ValueError, KeyError) as error:
        raise RuntimeError("Pinned E1 fixture required; restore reviewed contract bytes: " + str(error)) from error


verify_engine_fixture(ENGINE)
sys.path.insert(0, str(ENGINE))
from luminumbra_author import meshgen_config as config  # noqa: E402
from luminumbra_author import meshgen_registry as registry  # noqa: E402
from luminumbra_author.contracts import Refusal, Toolchain, parse_json  # noqa: E402
from luminumbra_author.meshgen_contracts import packaged_schemas  # noqa: E402
from luminumbra_author.meshgen_scripts import ScriptInventory  # noqa: E402
sys.path.pop(0)


def read_project():
    return config.load_document(PROJECT / "meshgen.config.json")


class ProjectConfigTests(unittest.TestCase):
    def setUp(self):
        self.project = read_project()

    def refusal(self, rule, **layers):
        with self.assertRaises(Refusal) as caught:
            config.resolve(self.project, "rock", **layers)
        self.assertEqual(caught.exception.finding["rule_id"], rule)

    def test_packaged_schema_defaults_and_registry_match(self):
        for name, document in packaged_schemas().items():
            self.assertEqual(config.load_document(ENGINE / "luminumbra_author/schemas" / name), document)
        self.assertEqual(config.load_document(ENGINE / "luminumbra_author/schemas/meshgen.defaults.v1.json"), registry.defaults())
        registry.validate_schema(self.project, registry.config_schema(), partial=True)

    def test_schema_refuses_unsupported_keywords_and_profile_policy(self):
        schema = registry.config_schema()
        schema["properties"]["backend"]["format"] = "unregistered"
        with self.assertRaises(Refusal) as caught:
            registry.validate_schema(self.project, schema, partial=True)
        self.assertEqual(caught.exception.finding["rule_id"], "schema.unsupported")
        self.project["profiles"]["rock"]["policy"] = {"validation_profile": "shipping"}
        self.refusal("config.unknown_key")
        self.project = read_project()
        self.project["policy"]["locks"].append("budgets.max_tris_final")
        self.refusal("config.locked")

    def test_profiles_are_provisional_examples_and_caps_are_derived(self):
        self.assertEqual(self.project["profiles"], registry.PROVISIONAL_PROFILES)
        for profile, cap in {"default": 8000, "prop": 8000, "rock": 6000, "foliage": 4000, "tree": 20000}.items():
            with self.subTest(profile=profile):
                result = config.resolve(self.project, profile)
                self.assertEqual(result.effective["budgets"]["max_tris_final"], cap)
                self.assertEqual(result.effective["finish"]["decimate"]["max_tris"], cap)
                self.assertEqual(result.sources["budgets.max_tris_final"], "L2")
                self.assertIn("config.budgets_uncalibrated", [f["rule_id"] for f in result.findings])
                self.assertNotIn("profiles", result.effective)
        self.assertEqual(config.resolve(self.project, "tree").effective["budgets"]["bounds_m"], [30.0, 30.0, 40.0])
        self.assertEqual(config.resolve(self.project, "foliage").effective["finish"]["decimate"]["hausdorff_max_rel"], 0.02)

    def test_mock_only_and_no_fabricated_policy_evidence(self):
        effective = config.resolve(self.project, "default").effective
        self.assertEqual([name for name, backend in effective["backends"].items() if backend["enabled"]], ["mock"])
        self.assertEqual(effective["backend"]["id"], "mock")
        self.assertEqual(effective["backends"]["mock"]["kind"], "mock")
        licence = effective["policy"]["licence"]
        self.assertEqual(licence["allowed_status"], ["shippable"])
        for name in ("internal_acknowledgements", "counsel_notes", "dataset_chain_waivers"):
            self.assertEqual(licence[name], [])
        self.assertTrue(all(record == {"value": False} for record in licence["attestations"].values()))
        self.assertEqual(effective["policy"]["validation_profile"], "internal")
        self.assertEqual(effective["candidates"]["select"], "manual")
        self.assertEqual(effective["logging"]["keep_prompts"], "digest")

    def test_layer_precedence_and_selected_profile_tightening(self):
        result = config.resolve(self.project, "rock",
            local={"backends": {"mock": {"timeouts": {"job_s": 40}, "token_source": {"file": "authoring/meshgen/tokens/mock"}}}},
            overrides={"budgets": {"max_tris_final": 4000}, "backends": {"mock": {"timeouts": {"job_s": 30}}}})
        self.assertEqual(result.effective["budgets"]["max_tris_final"], 4000)
        self.assertEqual(result.effective["finish"]["decimate"]["max_tris"], 4000)
        self.assertEqual(result.effective["backends"]["mock"]["timeouts"]["job_s"], 30)
        self.assertEqual(result.sources["backends.mock.token_source"], "L3")
        self.assertEqual(result.sources["budgets.max_tris_final"], "L4")
        self.refusal("config.override_denied", overrides={"budgets": {"max_tris_final": 9000}})
        self.refusal("config.override_denied", local={"backends": {"mock": {"timeouts": {"job_s": 61}}}})
        self.refusal("config.override_denied", local={"backends": {"mock": {"timeouts": {"job_s": 40}}}},
                     overrides={"backends": {"mock": {"timeouts": {"job_s": 50}}}})

    def test_profile_is_explicit_and_inheritance_is_bounded(self):
        for name in ("", "missing"):
            with self.subTest(name=name), self.assertRaises(Refusal) as caught:
                config.resolve(self.project, name)
            self.assertEqual(caught.exception.finding["rule_id"], "config.profile_missing")
        variants = [
            ({"inherits": "missing"}, "config.profile_missing"),
            ({"inherits": "rock"}, "config.cycle"),
        ]
        for profile, rule in variants:
            with self.subTest(rule=rule):
                self.project = read_project()
                self.project["profiles"]["rock"] = profile
                self.refusal(rule)
        self.project = read_project()
        self.project["profiles"]["middle"] = {"inherits": "default"}
        self.project["profiles"]["rock"]["inherits"] = "middle"
        config.resolve(self.project, "rock")  # selected + middle + default
        self.project["profiles"]["extra"] = {"inherits": "middle"}
        self.project["profiles"]["rock"]["inherits"] = "extra"
        self.refusal("config.out_of_bounds")

    def test_locks_local_allowlist_and_real_backend_refusals(self):
        self.refusal("config.locked", local={"backends": {"mock": {"endpoint": "http://127.0.0.1:18802"}}})
        self.refusal("config.override_denied", local={"budgets": {"max_tris_final": 4000}})
        self.refusal("config.override_denied", local={"backends": {"direct3d_s2": {"enabled": True}}})
        self.refusal("config.backend_missing", local={"backends": {"mock": {"enabled": False}}})
        self.refusal("config.backend_missing", overrides={"backend": {"id": "direct3d_s2"}})
        self.project["backends"]["direct3d_s2"]["enabled"] = True
        self.refusal("config.pins_missing")

    def test_decimate_target_must_fit_final_cap(self):
        result = config.resolve(self.project, "rock", overrides={"finish": {"decimate": {"max_tris": 4000}}})
        self.assertEqual(result.effective["finish"]["decimate"]["max_tris"], 4000)
        self.assertEqual(result.effective["budgets"]["max_tris_final"], 6000)
        self.refusal("config.out_of_bounds", overrides={"budgets": {"max_tris_final": 3000}, "finish": {"decimate": {"max_tris": 4000}}})

    def test_strict_types_vectors_keys_locks_and_ports(self):
        cases = [
            ({"budgets": {"max_tris_final": True}}, "config.type"),
            ({"budgets": {"max_tris_final": 63}}, "config.out_of_bounds"),
            ({"budgets": {"bounds_m": [1, 2]}}, "config.out_of_bounds"),
            ({"budgets": {"bounds_m": [1, 2, 3, 4]}}, "config.out_of_bounds"),
            ({"budgets": {"bounds_m": [1, 0, 3]}}, "config.out_of_bounds"),
            ({"finish": {"unknown": True}}, "config.unknown_key"),
            ({"policy": {"locks": ["missing.*"]}}, "config.unknown_key"),
            ({"backends": {"mock": {"endpoint": "http://localhost:18800"}}}, "config.out_of_bounds"),
            ({"backends": {"mock": {"endpoint": "http://127.0.0.1:00000"}}}, "config.out_of_bounds"),
            ({"backends": {"mock": {"endpoint": "http://127.0.0.1:65536"}}}, "config.out_of_bounds"),
            ({"backends": {"mock": {"token_source": {"env": "TOKEN", "file": "token.txt"}}}}, "config.type"),
            ({"backends": {"mock": {"unknown": 1}}}, "config.unknown_key"),
        ]
        for change, rule in cases:
            with self.subTest(change=change):
                self.project = config.merge(read_project(), change)
                self.refusal(rule)

    def test_nonfinite_and_duplicate_json_refused(self):
        for data in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_json(data)

    def test_steps_are_fixed_and_later_execution_disabled(self):
        effective = config.resolve(self.project, "default").effective
        self.assertEqual(effective["finish"]["steps"], list(registry.STEPS))
        self.assertEqual(effective["finish"]["decimate"]["method"], "blender_collapse")
        self.assertEqual(effective["finish"]["uv"]["method"], "smart_project")
        self.assertEqual(effective["finish"]["decimate"]["on_over_budget"], "refuse")
        for family in ("lod", "collider", "texture", "rig", "anim"):
            self.assertFalse(effective[family]["enabled"])
        self.assertFalse(effective["agent"]["tier_a"]["enabled"])
        self.assertFalse(effective["agent"]["tier_b"]["enabled"])
        for steps in (list(reversed(registry.STEPS)), list(registry.STEPS)[:-1] + ["uv"], list(registry.STEPS)[1:]):
            self.project = config.merge(read_project(), {"finish": {"steps": steps}})
            self.refusal("config.override_denied")
        self.project = config.merge(read_project(), {"texture": {"enabled": True}})
        self.refusal("config.execution_unavailable")
        self.project = config.merge(read_project(), {"finish": {"uv": {"method": "xatlas"}}})
        self.refusal("config.helper_unavailable")

    def test_digest_is_canonical_sources_separate_and_stored_bytes_bound(self):
        result = config.resolve(self.project, "rock")
        reordered = {key: self.project[key] for key in reversed(self.project)}
        self.assertEqual(result.config_digest, config.resolve(reordered, "rock").config_digest)
        self.assertNotIn("sources", result.effective)
        self.assertNotIn("config_digest", result.effective)
        self.assertEqual(config.verify_effective_config(result.stored_bytes, result.stored_sha256, result.config_digest), result.effective)
        self.assertNotEqual(result.config_digest, result.stored_sha256)
        with self.assertRaises(Refusal) as caught:
            config.verify_effective_config(result.stored_bytes + b"\n", result.stored_sha256, result.config_digest)
        self.assertEqual(caught.exception.finding["rule_id"], "config.digest_mismatch")
        local = {"backends": {"mock": {"token_source": {"env": "OTHER_TOKEN"}}}}
        self.assertNotEqual(result.config_digest, config.resolve(self.project, "rock", local=local).config_digest)
        with mock.patch.dict(os.environ, {"LUMINUMBRA_GEN_TOKEN": "rotation-a"}):
            first = config.resolve(self.project, "rock").config_digest
        with mock.patch.dict(os.environ, {"LUMINUMBRA_GEN_TOKEN": "rotation-b"}):
            self.assertEqual(first, config.resolve(self.project, "rock").config_digest)


class TemporaryProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(PROJECT, self.root / "authoring/meshgen")

    def test_check_config_cli_has_no_state_or_secret_side_effects(self):
        secret = self.root / "authoring/meshgen/token.mock"
        secret.write_bytes(b"unread secret sentinel\xff")
        local = {"backends": {"mock": {"token_source": {"file": "authoring/meshgen/token.mock"}}}}
        (secret.parent / "meshgen.local.json").write_text(json.dumps(local), encoding="utf-8")
        before = {p.relative_to(self.root): p.read_bytes() if p.is_file() else None for p in self.root.rglob("*")}
        command = [sys.executable, "-I", "-S", "-B", str(ENGINE / "launch.py"), "--project", str(self.root),
                   "--toolchain", str(self.root / "absent-toolchain.json"), "meshgen", "check-config", "--profile", "rock", "--print-effective"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        response = json.loads(result.stdout)["result"]
        self.assertEqual(response["backend_validation"], "unavailable")
        self.assertFalse(response["budgets_calibrated"])
        self.assertEqual(response["effective_config"]["budgets"]["max_tris_final"], 6000)
        self.assertIn("sources", response)
        self.assertIn("differences", response)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() if p.is_file() else None for p in self.root.rglob("*")})
        command[command.index("rock")] = "absent"
        failed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(json.loads(failed.stdout)["findings"][0]["rule_id"], "config.profile_missing")

    def test_fixture_absence_and_changed_bytes_refuse_without_skip(self):
        with self.assertRaisesRegex(RuntimeError, "Pinned E1 fixture required"):
            verify_engine_fixture(self.root / "absent-engine")
        copy = self.root / "engine"
        shutil.copytree(ENGINE, copy)
        (copy / "luminumbra_author/meshgen_config.py").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "changed fixture member"):
            verify_engine_fixture(copy)

    def test_installed_fixture_archive_has_schemas_and_no_game_source(self):
        staging = self.root / "installed-fixture"
        staging.mkdir()
        inventory = config.load_document(ENGINE / "inventory.json")
        for name in inventory["files"]:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ENGINE / name, target)
        (staging / "__main__.py").write_text("from luminumbra_author.__main__ import main\nraise SystemExit(main())\n", encoding="utf-8")
        archive = self.root / "service-fixture.pyz"
        zipapp.create_archive(staging, archive, compressed=True)
        with zipfile.ZipFile(archive) as package:
            members = package.namelist()
            self.assertIn("luminumbra_author/schemas/meshgen.config.v1.schema.json", members)
            self.assertIn("luminumbra_author/schemas/meshgen.defaults.v1.json", members)
            self.assertFalse(any(name.startswith("authoring/") or "provenance.json" in name for name in members))
        result = subprocess.run([sys.executable, "-I", "-S", "-B", str(archive), "--project", str(self.root),
                                 "--toolchain", str(self.root / "absent-toolchain.json"), "meshgen", "check-config", "--profile", "tree"],
                                capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"]["profile"], "tree")

    def test_worker_paths_are_local_and_affect_identity(self):
        project = read_project()
        paths = [self.root / name for name in ("worker-a.txt", "worker-b.txt")]
        for path in paths:
            path.write_text("not executed\n", encoding="utf-8")
        digests = []
        for path in paths:
            local = {"workers": {"finisher": {"python": str(path)}}}
            digests.append(config.resolve(project, "rock", local=local).config_digest)
        self.assertNotEqual(*digests)
        project["workers"] = {"finisher": {"python": str(paths[0])}}
        with self.assertRaises(Refusal) as caught:
            config.resolve(project, "rock")
        self.assertEqual(caught.exception.finding["rule_id"], "config.override_denied")
        with self.assertRaises(Refusal) as caught:
            config.resolve(read_project(), "rock", local={"workers": {"finisher": {"python": str(self.root / "absent")}}})
        self.assertEqual(caught.exception.finding["rule_id"], "config.type")

    def test_true_attestation_without_hash_matching_note_is_refused(self):
        project = read_project()
        project["policy"]["licence"]["attestations"]["registration_done"] = {
            "value": True, "attested_by": "negative-test", "attested_at": "2026-10-13",
            "note_id": "absent", "note_sha256": "0" * 64,
        }
        with self.assertRaises(Refusal) as caught:
            config.resolve(project, "rock", project_root=self.root)
        self.assertEqual(caught.exception.finding["rule_id"], "config.attestation_unverified")

    def test_game_pins_transitive_modules_and_execution_recheck(self):
        pins = config.load_document(self.root / "authoring/meshgen/script-pins.json")
        processor = self.root / "processor-fixture.txt"
        processor.write_text("not executed\n", encoding="utf-8")
        manifest = self.root / "toolchain-fixture.json"
        manifest.write_text(json.dumps({"schema": "luminumbra.authoring.toolchain.v1", "id": "g1.fixture",
            "processor": processor.name, "files": {processor.name: sha(processor.read_bytes())}, **pins}), encoding="utf-8")
        toolchain = Toolchain(manifest)
        toolchain.verify_scripts(self.root, "companion")
        with self.assertRaises(Refusal) as caught:
            toolchain.verify_scripts(self.root, "finisher")
        self.assertEqual(caught.exception.finding["rule_id"], "config.pins_missing")
        record = pins["scripts"]["companion"]
        unpinned = deepcopy(record)
        unpinned["modules"] = {}
        with self.assertRaises(Refusal) as caught:
            ScriptInventory(self.root, unpinned).diagnose()
        self.assertEqual(caught.exception.finding["rule_id"], "config.pins_missing")
        helper = self.root / "authoring/meshgen/companion/bootstrap.py"
        helper.write_bytes(helper.read_bytes() + b"# changed after verification\n")
        with self.assertRaises(Refusal) as caught:
            toolchain.verify_scripts(self.root, "companion")
        self.assertEqual(caught.exception.finding["rule_id"], "toolchain.changed")


class CompanionAndOwnershipTests(unittest.TestCase):
    def test_inventory_matches_exact_pins_and_future_roles_have_no_executable(self):
        inventory = config.load_document(PROJECT / "script-inventory.json")["roles"]
        pins = config.load_document(PROJECT / "script-pins.json")
        self.assertEqual(set(pins), {"scripts"})  # toolchain fragment; no invented compiler hash
        self.assertEqual(set(pins["scripts"]), {"companion"})
        for role, record in inventory.items():
            if record["status"] == "planned":
                self.assertNotIn(role, pins["scripts"])
                self.assertFalse((ROOT / record["path"]).exists())
                continue
            pin = pins["scripts"][role]
            self.assertEqual(record["path"], pin["path"])
            self.assertEqual(set(record["modules"]), set(pin["modules"]))
            members = {pin["path"]: pin["sha256"], **pin["modules"]}
            self.assertEqual(set(members), {p.relative_to(ROOT).as_posix() for p in (PROJECT / "companion").glob("*.py")})
            for name, expected in members.items():
                self.assertEqual(sha((ROOT / name).read_bytes()), expected)
            ScriptInventory(ROOT, pin).verify()
            ScriptInventory(ROOT, pin).diagnose()

    def test_manifest_bootstrap_and_declared_lifecycle_surface(self):
        manifest = tomllib.loads((PROJECT / "companion/blender_manifest.toml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "luminumbra_meshgen")
        self.assertEqual(manifest["blender_version_min"], "5.1.0")
        self.assertEqual(manifest["blender_version_max"], "5.1.1")
        self.assertEqual(manifest["license"], ["SPDX:MIT"])
        spec = importlib.util.spec_from_file_location("g1_companion", PROJECT / "companion/__init__.py",
                                                    submodule_search_locations=[str(PROJECT / "companion")])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        self.addCleanup(sys.modules.pop, spec.name + ".bootstrap", None)
        spec.loader.exec_module(module)
        module.register()
        module.unregister()
        surface = module.bootstrap
        self.assertEqual(surface.IMPLEMENTATION_STATUS, "skeleton")
        self.assertEqual(surface.EXECUTION_FEATURES, ())
        self.assertEqual(set(surface.INVALIDATION_EVENTS), {"edit", "undo", "redo", "load", "unload", "scope_changed",
                                                          "config_changed", "project_changed", "session_changed"})
        self.assertIn("validate_origins_at_mark", surface.INTEGRATION_POINTS)
        self.assertIn("validate_origins_at_build", surface.INTEGRATION_POINTS)
        self.assertEqual(surface.REQUIRED_SERVICE_FEATURES, ("meshgen_configuration", "meshgen_script_pins"))
        self.assertEqual(surface.BUDGETED_BUILD_FEATURE, "max_tris_setting")

    def test_engine_fixture_has_only_stdlib_imports_and_no_game_scripts(self):
        allowed = sys.stdlib_module_names
        for path in (ENGINE / "luminumbra_author").glob("*.py"):
            tree = ast.parse(path.read_bytes())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name.split(".")[0], allowed, path.name)
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    self.assertIn(node.module.split(".")[0], allowed, path.name)
        self.assertFalse(any(p.name.startswith("blender_") or p.name == "finish_candidate.py" for p in ENGINE.rglob("*.py")))

    def test_gitignore_excludes_local_state_art_and_native_evidence(self):
        ignored = ["authoring/meshgen/meshgen.local.json", "authoring/meshgen/token.mock", "authoring/meshgen/tokens/mock",
                   "authoring/meshgen/toolchain.local.json", ".luminumbra-author/session.json",
                   ".luminumbra-author-recipes/doc/candidates/job/candidate.glb",
                   "authoring/meshgen/generated/preview.png", "authoring/meshgen/native/evidence/receipt.json", ".test-tmp/probe"]
        result = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "--no-index", "--stdin"],
                                input="\n".join(ignored) + "\n", capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(result.stdout.splitlines()), set(ignored))
        committed = ["authoring/meshgen/meshgen.config.json", "authoring/meshgen/script-pins.json",
                     "authoring/meshgen/companion/bootstrap.py", "authoring/meshgen/native/finish_probe.py"]
        result = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "--no-index", "--stdin"],
                                input="\n".join(committed) + "\n", capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
