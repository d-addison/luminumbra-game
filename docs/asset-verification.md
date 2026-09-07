# Published tree pack verification

On September 7, 2026, both published packs and their companions were downloaded
into fresh verification directories, separately from conversion and acquisition
caches. Release/tag identities, archive sizes/checksums, every regular member,
source provenance and conversion receipts matched. The [full member report](evidence/tree-small-02-download-verification.json)
records the archive and member SHA-256 identities and acquisition script identities.

| Pack | Release | Tag target | Bytes | Regular members |
|---|---|---|---:|---:|
| Source | [tree-small-02-source-v1.0.0](https://github.com/d-addison/luminumbra-game/releases/tag/tree-small-02-source-v1.0.0) | `9f3a66d697c58a96fcde51e88978ac874c090c15` | 64,772,126 | 14 |
| Runtime | [tree-small-02-runtime-v1.0.0](https://github.com/d-addison/luminumbra-game/releases/tag/tree-small-02-runtime-v1.0.0) | `addab429aced2c3a6817a357f67a032491eef67b` | 15,194,266 | 22 |

Source archive SHA-256: `c128b8d93463f4f7676294533b6808b21e6481f16a31b2d3c3dc2300eead6004`.
Runtime archive SHA-256: `d443c9873a6e0f1e00927a2550b6bdb9240f76c3d8508b96fde4685f7989c20d`.

Clean HTTPS acquisition and verified offline installation passed on Linux and
native Windows. All 13 acquisition regressions passed on each platform, including
corrupt input, unsafe archive paths, bounded extraction, interrupted publication,
repair preservation and link/reparse refusal. The source pack also acquired over
HTTPS on both platforms. Ordinary engine builds/tests require no downloaded pack.

The runtime retains all 30,250 source leaf surfaces as fitted cards; all three
leaf LODs contain 60,500 triangles. The conversion documentation records the
curvature approximation and the rejected canopy simplifications. Authored cutouts,
color, normal and surface maps remain in the verified member manifest.

These findings complete the source/runtime download verification work packages.
Final composed-game visual/performance acceptance, signed engine v0.3.0 publication
and the new private preview remain separate open work. No private audio or Steam
SDK payload is part of either public art pack. See the [roadmap](roadmap.md).
