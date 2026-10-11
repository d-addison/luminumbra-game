# Tree Small 02 canopy conversion

This page describes the Tree Small 02 runtime pack: what it contains, how it is
converted, how its leaf geometry was fitted, and how its resource figures are
derived and checked. The conversion steps themselves are in
[`assets/tree-small-02/CONVERSION.md`](../assets/tree-small-02/CONVERSION.md),
which this page links rather than repeats.

## What ships

- Pack: Tree Small 02 runtime, release tag `tree-small-02-runtime-v1.0.0`.
- Archive: `tree-small-02-runtime-v1.0.0.tar.gz`, sha256
  `d443c9873a6e0f1e00927a2550b6bdb9240f76c3d8508b96fde4685f7989c20d`.
- Contents: 9 `.lmesh` meshes (branches, leaves and trunk, each at LOD 0, 1 and 2),
  9 `.ltex` textures (albedo, ARM and normal maps for branch, leaves and trunk),
  plus `CONVERSION.md`, `LICENSE.txt`, `conversion-receipt.json` and
  `source-manifest.json`. The runtime manifest lists 22 archive members in total.
- Attribution: Tree Small 02 by Rico Cilliers, Poly Haven, CC0. The license text
  ships in the pack as `LICENSE.txt`.

## Conversion pipeline

The pipeline has three stages. The full procedure, including the native fitter
build, is in `assets/tree-small-02/CONVERSION.md`.

1. Verify the source release (`tree-small-02-source-v1.0.0`) before conversion.
2. Convert with `tools/convert_tree_small_02.py`, which calls the engine's
   asset processor and the leaf-card fitter (`tools/fit_leaf_cards.cpp`) and writes
   `conversion-receipt.json`.
3. Package with `tools/package_tree_small_02.py`, which writes the archive and
   the manifest.

## Leaf-card fitting

- The source has 30,250 disconnected curved leaf surfaces. Each surface is kept
  as a UV-aligned textured card. No leaves are removed.
- Every mesh LOD keeps the same 60,500 leaf triangles, with 121,000 vertices per
  leaf LOD file.
- The largest residual, the maximum relative fit error, is 15.414% of an individual
  leaf's bounding-box diagonal. The fitter refuses any residual above 20%.
- LOD policy: LOD 1 and LOD 2 of the leaves copy the LOD 0 cards. Branch and trunk
  LODs are separately simplified meshes.

## Rejected geometry

- Whole-tree positional simplification was rejected because it collapsed canopy
  area. See `assets/tree-small-02/CONVERSION.md`.
- Lower-canopy simplification candidates are mentioned only as a historical
  assertion in the text of issue #3. No candidate mesh, log or other artifact
  was retained in this repository or in the pack, so they cannot be re-checked.

## Materials

The material rules are specified in
[`assets/tree-small-02/CONVERSION.md`](../assets/tree-small-02/CONVERSION.md),
which this page links rather than repeats.

- Material maps: 512-square textures with ten mips for each of branch, leaves and
  trunk. Albedo is sRGB; normal maps are linear OpenGL; ambient-occlusion,
  roughness and metallic maps are linear.
- Leaf opacity comes from the source alpha PNG and uses a 0.5 cutout threshold.
- Mip rules: color mips filter in linear light, normal mips are renormalized, and
  opacity mips preserve texture-space cutout coverage.

## Conversion outputs

The 18 conversion outputs listed in `conversion-receipt.json`, with the size and
sha256 of each file. These rows are outside the generated accounting block.

| Output | Bytes | sha256 |
| --- | ---: | --- |
| `data/models/trees/tree_small_02_branches.lmesh` | 1574460 | `a75313ee29bcaebb55d2c2f41f2cffc4c40d168eb14bc2f58003b5b34ed17534` |
| `data/models/trees/tree_small_02_branches.lod1.lmesh` | 994764 | `2f3708b7420fa7b92bf6ad701cedd31642abe235bbb8dfda701fbc71b87e2bf8` |
| `data/models/trees/tree_small_02_branches.lod2.lmesh` | 548060 | `1d9d7c400e95c70c86cc4b1738416d589da49cfc22faf937226b34e534599f34` |
| `data/models/trees/tree_small_02_leaves.lmesh` | 4598028 | `3581c046b685027e4cdf1125cba35bccbcdb3e6d9caf96bf5b64c51024a5aa4e` |
| `data/models/trees/tree_small_02_leaves.lod1.lmesh` | 4598028 | `3581c046b685027e4cdf1125cba35bccbcdb3e6d9caf96bf5b64c51024a5aa4e` |
| `data/models/trees/tree_small_02_leaves.lod2.lmesh` | 4598028 | `3581c046b685027e4cdf1125cba35bccbcdb3e6d9caf96bf5b64c51024a5aa4e` |
| `data/models/trees/tree_small_02_trunk.lmesh` | 317612 | `de9e2226f83e00d315e1b00fac20d6312ee4d637b1a0d7aaad8877c6a4d960b9` |
| `data/models/trees/tree_small_02_trunk.lod1.lmesh` | 92632 | `5b1a8c02ef1b464822020825d211d52c17b726d49305d1e8529d5dddd239e395` |
| `data/models/trees/tree_small_02_trunk.lod2.lmesh` | 40292 | `dac80d04502da379689c332525e531fdda6cb0962da5c6c5605c5361f4fbe567` |
| `data/textures/models/tree_branch_albedo_512.ltex` | 1398117 | `1193631ba5cac2d5ed589d54181bb0d451c9957d334a138b7bcab534e3c7b7f9` |
| `data/textures/models/tree_branch_arm_512.ltex` | 1398117 | `870a76a98d215b033ba54151f498539d25740edebdcef8a13973b8acd582870d` |
| `data/textures/models/tree_branch_normal_512.ltex` | 1398117 | `2ecfee044ef739a903e0ce4317114ac01e1ddec7dfc92c5dfd46589fe977e54f` |
| `data/textures/models/tree_leaves_albedo_512.ltex` | 1398117 | `12af70783d2d79e1f83151ed4819cce4f5ac3980f2bce37dacb793c7ecea164d` |
| `data/textures/models/tree_leaves_arm_512.ltex` | 1398117 | `4e99735963cdc9cb3aa9ccb31e7550ced3465c8188937495c0d8395110817e75` |
| `data/textures/models/tree_leaves_normal_512.ltex` | 1398117 | `772127f91359c94d88b855a146a5fb816c279f03984fa8bfb3370b8b2b87fb94` |
| `data/textures/models/tree_trunk_albedo_512.ltex` | 1398117 | `559d42d4364d4dd73dd5174688e81c736de3fe11bf9771c40fb47ceb0a676ca5` |
| `data/textures/models/tree_trunk_arm_512.ltex` | 1398117 | `d9f3d3f4b31adaf1234e2c10fce2483f6604b4c77b22f8b52b215d278f590038` |
| `data/textures/models/tree_trunk_normal_512.ltex` | 1398117 | `e2e0ae26a9bb3481bd9ea45c029d1f0272c6dfcf69d47485b728d492ebe0c4bb` |

## Resource accounting

The figures below are derived from `conversion-receipt.json` by
`tools/check_tree_small_02_receipts.py`. Every value is labelled `estimated` in
the accounting record. The table lists file sizes per mesh LOD.

- Mesh file size is `28 + 32 * vertices + 12 * triangles` bytes for each `.lmesh`.
- Texture file size is 17 header bytes plus a 1,398,100-byte mip-chain payload
  (ten mips of 512-square RGBA8). Each `.ltex` is 1,398,117 bytes, and the nine
  textures total 12,583,053 bytes (12,582,900 bytes of payload).
- Totals: 30,250 leaf surfaces; 60,500 leaf triangles at every LOD.

Exclusions. These are file and payload sizes only. They make no claim about GPU
allocation: texture-array padding, driver overhead and separate LOD buffers are
not modelled. Measured VRAM is a native item. Engine-side estimates for
static-model textures, impostor textures and forest resources are in the engine's
`docs/v0.3-acceptance.md` and are not duplicated here.

The engine's impostor atlas is a derived bake. The engine produces it at run time
from the pack's meshes and textures. It is not shipped content in this pack, is
not listed in the runtime manifest, and is not part of any figure above.

Measured VRAM status: NEEDS-NATIVE-RUN. The native method is:

1. Query driver memory use (NVML or NVAPI) on the qualified RTX 5070 Ti before and
   after loading the pack.
2. Record GL allocation accounting for the same load: `glGetTextureLevelParameter`
   for texture levels and buffer sizes for mesh buffers.

Each result is added to the accounting record as a `measured` entry carrying an
`evidence_sha256` that identifies the captured evidence. Until that run is
recorded, the `measured` list is empty and no GPU figure is claimed.

<!-- accounting:begin -->
| Part | LOD | Vertices | Triangles | File bytes |
| --- | ---: | ---: | ---: | ---: |
| branches | 0 | 31951 | 46000 | 1574460 |
| branches | 1 | 20773 | 27500 | 994764 |
| branches | 2 | 12251 | 13000 | 548060 |
| leaves | 0 | 121000 | 60500 | 4598028 |
| leaves | 1 | 121000 | 60500 | 4598028 |
| leaves | 2 | 121000 | 60500 | 4598028 |
| trunk | 0 | 6176 | 9996 | 317612 |
| trunk | 1 | 1920 | 2597 | 92632 |
| trunk | 2 | 884 | 998 | 40292 |
<!-- accounting:end -->

## Reproducing the figures

The receipt pins the inputs needed to reproduce the conversion:

- Engine revision: `f18098d72077a4682dae1df96915a4d0c95b6889`.
- Converter script: sha256 `4fc92b290d9808e62b46982824a10c85bff67b6a2946a04f7ede52ac4b83721f`,
  7,797 bytes.
- Leaf fitter source: sha256 `efd89d3bd03140912a2e20500887f23f0585959c1d598265ed3c329d1a4400aa`.
- Asset processor: sha256 `4f592137703dcd11cbbd609bbdecb4b86d2bcc1e1f628305907eed219f89c479`.

Float output can vary between toolchains. The archive hash is therefore the
identity of the pack; a rebuild that differs only in float bits is a different
pack and must be published under a new version.

Verify the figures with the checker, run from the repository root:

```sh
python3 -I tools/check_tree_small_02_receipts.py --receipt PATH/conversion-receipt.json --full
python3 -I tools/check_tree_small_02_receipts.py --receipt tests/fixtures/tree-small-02-receipt-counts.json --check-doc docs/canopy-conversion.md
python3 -I tools/check_tree_small_02_receipts.py --receipt tests/fixtures/tree-small-02-receipt-counts.json --check-json docs/evidence/tree-small-02-resource-accounting.json
python3 -I tools/check_tree_small_02_receipts.py --receipt tests/fixtures/tree-small-02-receipt-counts.json --emit-doc-table
```

`PATH/conversion-receipt.json` is the receipt inside an extracted pack. An untrimmed
receipt is always checked against its manifest entry (size and sha256); `--full`
is accepted as a no-op alias. The fixture is a
trimmed receipt that carries the same counts and sizes, so the committed
accounting record and this table are checked against it.

## Policy

- Archive members are hash-pinned in the runtime manifest. Any change to
  `CONVERSION.md`, `LICENSE.txt`, the receipt, the source manifest or an output
  file requires a new pack version and a new archive hash.
- Changes to meshes, leaf thresholds, mip filtering or bake resolution need
  appearance and performance acceptance. Matching hashes do not establish visual
  fidelity.
