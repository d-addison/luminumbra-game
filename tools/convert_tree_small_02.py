#!/usr/bin/env python3
"""Convert the verified source pack with Luminumbra's asset_processor.

All inputs are verified before conversion. The output receipt records the exact
processor binary, source manifest and resulting runtime files. Publish only after
the engine revision and packaged rendering acceptance have been verified.
"""

import argparse
import hashlib
import json
import math
import re
import shutil
from pathlib import Path
import struct
import subprocess
import tempfile


def identity(path):
    data = path.read_bytes()
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Extracted source pack directory")
    parser.add_argument("--processor", type=Path, required=True)
    parser.add_argument("--leaf-fitter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine-revision", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.engine_revision):
        raise ValueError("Record the full verified engine commit identity")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use an empty output directory to prevent mixed pack contents")
    manifest_path = args.source / "source-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    source = args.source / "source"
    for item in manifest["files"]:
        path = Path(item["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe source path: {path}")
        actual = identity(source / path)
        if any(actual[key] != item[key] for key in actual):
            raise ValueError(f"Source verification failed: {path}")

    model_dir = args.output / "data/models/trees"
    texture_dir = args.output / "data/textures/models"
    model_dir.mkdir(parents=True, exist_ok=True)
    texture_dir.mkdir(parents=True, exist_ok=True)
    commands = []

    def convert(*arguments):
        arguments = [str(arg) for arg in arguments]
        # Portable command roots avoid publishing machine-specific source/output paths.
        commands.append([arg.replace(str(source), "source").replace(str(args.output), "output")
                         for arg in arguments])
        subprocess.run([str(args.processor.resolve()), *arguments], check=True)

    # Keep the thin branches at a higher budget near the player. Explicit budgets
    # avoid a whole-tree error tolerance collapsing almost all branch surfaces.
    for name, primitive, budgets in [("branches", 0, [46000, 27500, 13000]),
                                      ("trunk", 2, [10000, 2600, 1000])]:
        for lod, budget in enumerate(budgets):
            suffix = "" if lod == 0 else f".lod{lod}"
            convert(source / "tree_small_02_2k.gltf",
                    model_dir / f"tree_small_02_{name}{suffix}.lmesh",
                    "--primitive", primitive, "--max-tris", budget)
    # Each of the source's 30,250 separate leaf surfaces becomes one textured
    # card. Preserve every leaf at every mesh LOD; positional decimation loses
    # canopy area. The fitter refuses a leaf outside its planar error bound.
    with tempfile.TemporaryDirectory(prefix="tree-small-02-conversion-") as temporary:
        full_leaves = Path(temporary) / "source-leaves.lmesh"
        convert(source / "tree_small_02_2k.gltf", full_leaves, "--primitive", 1)
        commands[-1][1] = "scratch/source-leaves.lmesh"
        leaf_path = model_dir / "tree_small_02_leaves.lmesh"
        fit_result = subprocess.run([str(args.leaf_fitter.resolve()), str(full_leaves), str(leaf_path)],
                                    check=True, capture_output=True, text=True)
        leaf_fit = json.loads(fit_result.stdout)
        if leaf_fit["leaf_surfaces"] != 30250 or leaf_fit["triangles"] != 60500:
            raise ValueError("The source leaf topology changed; repeat appearance acceptance")
        for lod in [1, 2]:
            shutil.copyfile(leaf_path, model_dir / f"tree_small_02_leaves.lod{lod}.lmesh")
    for part in ["branch", "leaves", "trunk"]:
        texture_prefix = "tree_small_02" if part == "trunk" else f"tree_small_02_{part}"
        mask = (["--alpha-mask", source / "textures/tree_small_02_leaves_alpha_2k.png"]
                if part == "leaves" else [])
        convert(source / f"textures/{texture_prefix}_diff_2k.jpg",
                texture_dir / f"tree_{part}_albedo_512.ltex", 512, "--srgb", *mask)
        convert(source / f"textures/{texture_prefix}_nor_gl_2k.jpg",
                texture_dir / f"tree_{part}_normal_512.ltex", 512, "--normal-map")
        convert(source / f"textures/{texture_prefix}_arm_2k.jpg",
                texture_dir / f"tree_{part}_arm_512.ltex", 512, "--linear")

    files = []
    for path in sorted(args.output.rglob("*")):
        if not path.is_file() or path.suffix not in {".lmesh", ".ltex"}:
            continue
        item = {"path": path.relative_to(args.output).as_posix(), **identity(path)}
        data = path.read_bytes()
        if path.suffix == ".lmesh":
            magic, vertices, indices, *sphere = struct.unpack_from("<III4f", data)
            if magic != 0x48534D4C or not vertices or not indices or indices % 3:
                raise ValueError(f"Invalid mesh: {path}")
            if len(data) != 28 + vertices * 32 + indices * 4:
                raise ValueError(f"Invalid mesh byte count: {path}")
            if not all(math.isfinite(value) for value in sphere) or sphere[3] <= 0:
                raise ValueError(f"Invalid mesh bounds: {path}")
            if max(struct.unpack_from(f"<{indices}I", data, 28 + vertices * 32)) >= vertices:
                raise ValueError(f"Invalid mesh indices: {path}")
            item.update(vertices=vertices, triangles=indices // 3, bounding_sphere=sphere)
        else:
            magic, version, mips, width, height, channels = struct.unpack_from("<IHHIIB", data)
            if (magic, version, mips, width, height, channels) != (0x5845544C, 1, 10, 512, 512, 4):
                raise ValueError(f"Invalid texture: {path}")
            if len(data) != 17 + sum(max(1, 512 >> mip) ** 2 * 4 for mip in range(10)):
                raise ValueError(f"Invalid texture byte count: {path}")
        files.append(item)
    if len(files) != 18:
        raise ValueError(f"Expected exactly 18 runtime files, got {len(files)}")
    receipt = {
        "schema": "luminumbra.game.asset-conversion.v1",
        "asset": manifest["asset"], "license": manifest["license"],
        "engine_revision": args.engine_revision,
        "processor": identity(args.processor), "source_manifest": identity(manifest_path),
        "converter_script": identity(Path(__file__)),
        "leaf_fitter": {**identity(args.leaf_fitter), "source": identity(Path(__file__).with_name("fit_leaf_cards.cpp")),
                        "result": leaf_fit,
                        "command": ["fit_leaf_cards", "scratch/source-leaves.lmesh", "output/data/models/trees/tree_small_02_leaves.lmesh"],
                        "lod_policy": "Retain all source leaf surfaces at each mesh LOD; copy LOD0 cards to LOD1 and LOD2"},
        "command_roots": {"source": "verified source pack/source", "output": "runtime pack"},
        "commands": commands, "files": files,
    }
    (args.output / "conversion-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"files": len(files), "bytes": sum(item["size"] for item in files),
                      "triangles": {item["path"]: item["triangles"] for item in files if "triangles" in item}}, indent=2))


if __name__ == "__main__":
    main()
