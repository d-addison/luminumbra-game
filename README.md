# Luminumbra game

This repository owns the current Luminumbra game's code and content. The reusable engine remains at [d-addison/luminumbra](https://github.com/d-addison/luminumbra).

The initial repository supplies independently versioned, verified game asset packs for engine v0.3.0 acceptance. Game code will move here after the engine release is verified and the revised implementation roadmap is approved. That extraction has not been implemented yet.

Public art packs contain redistributable source/runtime content, provenance, conversion instructions and checksums. Private audio recordings and Steam SDK payloads are excluded. Public engine software releases remain source-only.

## Tree Small 02

The initial tree source is [Tree Small 02](https://polyhaven.com/a/tree_small_02) by Rico Cilliers, published by Poly Haven under [CC0](https://polyhaven.com/license). Local glTF, buffer and nine JPG source files were compared byte-for-byte by size and upstream MD5 with Poly Haven's API manifest; the separate leaf alpha PNG was downloaded and verified as well. SHA-256 identities are recorded in `assets/tree-small-02/source-manifest.json`.

The [conversion instructions](assets/tree-small-02/CONVERSION.md) describe the source-derived leaf cards, mesh LODs and material processing. The engine acquisition manifest pins the published runtime archive and every required file. No engine dependency on this repository is required for building the engine.

Repository software and conversion tools use the [MIT license](LICENSE). Tree Small 02 art remains CC0, as recorded in its source manifest and each pack’s `LICENSE.txt`.
