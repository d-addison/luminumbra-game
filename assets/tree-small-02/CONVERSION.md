# Tree Small 02 runtime conversion

Source: [Tree Small 02 by Rico Cilliers](https://polyhaven.com/a/tree_small_02),
redistributed under [Poly Haven's CC0 terms](https://polyhaven.com/license).
The separately versioned source release is `tree-small-02-source-v1.0.0`.
`source-manifest.json` records every source URL, size, SHA-256 and upstream MD5.
It includes the separate authored leaf opacity map that the JPEG glTF export
cannot carry in its base-color image.

This pack contains only this asset and its provenance. Private recordings and
Steam runtime files are not inputs to this conversion.

## Reproduce

Use Python 3, a C++20 compiler, this repository's conversion tools, and
Luminumbra's `asset_processor` built from the full engine revision recorded in
`conversion-receipt.json`. Build the fitter with:

```sh
c++ -O2 -std=c++20 tools/fit_leaf_cards.cpp -o build/fit_leaf_cards
```

Create `build` first. In a native Windows Developer Command Prompt, the
equivalent is `cl /O2 /EHsc /std:c++20 tools\fit_leaf_cards.cpp /Fe:build\fit_leaf_cards.exe`.
Obtain and verify the source release using the engine acquisition tool's
`--pack tree-small-02-source` option. Then run:

```sh
python3 tools/convert_tree_small_02.py \
  --source path/to/verified/source-pack \
  --processor path/to/luminumbra/asset_processor \
  --leaf-fitter build/fit_leaf_cards \
  --engine-revision FULL_ENGINE_COMMIT \
  --output staging/runtime
python3 tools/package_tree_small_02.py \
  --source path/to/verified/source-pack \
  --runtime staging/runtime \
  --output dist/tree-small-02-runtime-v1.0.0.tar.gz
```

Use an empty runtime output directory. Input verification happens before
conversion. The receipt records tool binary hashes, tool source hashes, portable
commands, source identity and each output file's size/hash. Geometry records
also include actual vertex/triangle counts and bounds. Floating-point output
may vary between toolchains; the published file hashes identify the exact pack.

## Geometry and materials

The source has 30,250 disconnected curved leaf surfaces. The fitter preserves
each surface as a UV-aligned textured card, fitting position against that
surface's normalized UV coordinates. No leaves are removed. The largest
point-fit residual is 15.414% of an individual leaf's bounding-box
diagonal. The fitter rejects nonfinite data, invalid indices, degenerate UVs
and a residual over 20%. This is an approximation of leaf curvature, not a
replacement canopy generated from unrelated shapes.

Every mesh LOD retains those same 60,500 leaf triangles. Branch targets are
46,000 / 27,500 / 13,000 triangles; trunk targets are 10,000 / 2,600 / 1,000.
The receipt gives actual counts. Keeping all leaves avoids the canopy-area
collapse caused by whole-tree positional simplification.

The glTF material's UV-set selection and `KHR_texture_transform` are applied
before mesh export. Three material sets contain 512-square textures and ten
mips: sRGB albedo, linear OpenGL normal maps, and linear ambient-occlusion /
roughness / metallic maps. Leaf opacity comes from the source alpha PNG and
uses a 0.5 cutout threshold. Color mips filter in linear light; normal mips
are renormalized. Opacity mips preserve texture-space cutout coverage.

The engine bakes view-dependent albedo, normal, roughness and occlusion from
the actual runtime meshes and textures. The bake is a derived runtime resource,
not an independently authored replacement image. Appearance and performance
acceptance must accompany changes to meshes, thresholds, mip filtering or bake
resolution; correct hashes alone do not establish visual fidelity.
