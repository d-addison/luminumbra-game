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
- The largest point-fit residual is 15.414% of an individual leaf's bounding-box
  diagonal. The fitter refuses any residual above 20%.
- LOD policy: LOD 1 and LOD 2 of the leaves copy the LOD 0 cards. Branch and trunk
  LODs are separately simplified meshes.

## Rejected geometry

- Whole-tree positional simplification was rejected because it collapsed canopy
  area. See `assets/tree-small-02/CONVERSION.md`.
- Lower-canopy simplification candidates are mentioned only as a historical
  assertion in the text of issue #3. No candidate mesh, log or other artifact
  was retained in this repository or in the pack, so they cannot be re-checked.

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

`PATH/conversion-receipt.json` is the receipt inside an extracted pack. `--full`
also checks that the receipt bytes match the manifest entry. The fixture is a
trimmed receipt that carries the same counts and sizes, so the committed
accounting record and this table are checked against it.

## Policy

- Archive members are hash-pinned in the runtime manifest. Any change to
  `CONVERSION.md`, `LICENSE.txt`, the receipt, the source manifest or an output
  file requires a new pack version and a new archive hash.
- Changes to meshes, leaf thresholds, mip filtering or bake resolution need
  appearance and performance acceptance. Matching hashes do not establish visual
  fidelity.
