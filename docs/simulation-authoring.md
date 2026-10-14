# H1 simulation authoring, slice 2

H1 authoring supplies validated policy/population data, a public engine inventory,
species identities and exact-byte export receipts. Runtime is **UNQUALIFIED**:
there is no engine adoption, population callback, persistent creature consumer or
native evidence in this slice. Source integration requires a named DS revision;
packaged population, restart, Frozen and promotion/demotion remain
`NEEDS-NATIVE-RUN`. Fixtures demonstrate authoring contracts only.

H2 now extends the same exporter with a third mapping for the item catalogue.
See [item authoring](items-authoring.md) for slice 3's schema, identities and Q25
matrix. The H1-specific gates and history below remain applicable.

The declared stack is the game acceptance harness at
`7a54e52e34dd0c29504907ca7da9c4c45a5a1835`, then this slice. Distant-scene
authoring is deferred to v0.3.1. This slice uses no distant-scene file and introduces
the minimal independent `tools/export_game_data.py` and captured-byte loader support.
There is no cave copy, scene mapping or engine modification here. This declared
order change supersedes Q2's original distant-scene prerequisite.

The engine authoring pin is `4c15419e9ba064c94e2933df73106991d92f1623` (S5/S6).
The uncommitted DistantPolicy draft informed structural fields; it supplies no
qualified coarse units or compiled fallback table. The H1 pin is independent of
the historical terrain/workload baseline documented in `content-layout.md`.

## Runtime documents

| Source | Engine destination | Schema |
|---|---|---|
| `content/sim/distant_policy.json` | `data/common/sim/distant_policy.json` | `luminumbra.distant_policy.v1` |
| `content/sim/region_population.json` | `data/common/sim/region_population.json` | `luminumbra.game.region-population.v1` |

Policy root keys are exactly `schema`, `creature_species`, `plant_species`.
Species collections are objects keyed by exact names from the pinned inventory,
including underscores. Omission of a species selects a consumer fallback; a
present block requires every field. The shipping policy is empty. Validators and
export refuse nonempty shipping overrides until DS publishes reviewed units,
rounding, saturation, eligibility, promotion behavior and fallback values.
Nonempty test examples live only in `tests/fixtures/simulation/` and are not tuning.

| Block | Required integer field | Inclusive range |
|---|---|---|
| Creature | `coarse_need_rate_ppm` | 0..4294967295 |
| Creature | `coarse_travel_m_per_cadence` | 0..4294967295 |
| Creature | `promote_distance_m` | 0..65535 |
| Creature | `lifespan_cadences` | 0..4294967295 |
| Creature | `reproduce_cadences` | 0..4294967295 |
| Plant | `max_cadence_shift` | 1..8 |
| Plant | `resume_cap_ticks` | 0..36000 |

Population root keys are exactly `schema`, `rules`; each rule requires exactly
`id`, `species`, `biomes`, `count`, `max_attempts`. IDs are unique lowercase
kebab-case, 1..64 ASCII bytes, sorted by ID. Species resolve to creatures only;
nonempty, unique biome lists resolve against the pinned biome table. The starter
`grovestrider-herd` requests two creatures in plains/wetland with eight attempts.
Plant and item population rules are excluded from v1, preserving H1 independence
from H2. Empty rule arrays are legal.

Named authoring limits in `validators/simulation.py` are `MAX_POPULATION_RULES=32`,
`MAX_POPULATION_COUNT=8`, `MAX_POPULATION_ATTEMPTS=128`,
`MAX_POPULATION_TOTAL=64`, and `MAX_RULE_ID_BYTES=64`. Count is 1..8;
max_attempts is count..128; total requested count is at most 64 per region.
DS must mirror these constants in its loader. These are population request/staging
bounds, independent of the S5 ground-object store cap (65,536 objects / 4 MiB).

Both documents are at most 1,048,576 bytes. Policy entries cannot exceed the whole
pin (10 creatures, 6 plants). Integer fields require `type(value) is int`:
booleans, fractions, exponent tokens, strings, null and out-of-range numbers
refuse. The shared strict loader rejects duplicate keys; validators reject missing
and unknown keys, unknown/future schemas and references. Files must be UTF-8,
LF only, no BOM, with a final LF. No runtime provenance or qualification keys are
added to these exact schemas.

`load_policy` is an author-side candidate loader: only clean leaf absence in an
existing directory produces empty overrides. Read failures, nonregular files,
symlinks, oversize and malformed present content refuse. Parsing does not mutate
previous objects. Committed/exported sources are required; export never synthesizes
an absent file. These helpers do not prove engine loader/admission parity.

## Inventory and identities

`tools/lumlib/engine_inventory.json` records the engine SHA, all shipped creature
and plant source paths, raw-byte SHA-256 and expected u16 species IDs, plus the
biome table path/hash and name/ID pairs. Inventory resolution runs before policy
or population validation, even with empty overrides/rules, and checks collisions
across each complete engine registry. It does not merely hash referenced rows.
Names and their source paths must agree; no kebab-case conversion is applied.

The dedicated `species_identity.py` uses offset **1469598103934665603**, prime
**1099511628211**, wrapping u64 at every byte, folding `(h ^ (h >> 32)) & 65535`,
then replacing zero with one. Empty names and NUL refuse. `grovestrider=56165`,
`wheat=7403`. Independent fixtures `vector_7999` (folded zero) and `vector_67098`
(folded one) both resolve to one and must collide. Existing preset identity uses
its unchanged offset **14695981039346656037**.

Refresh the inventory against the named integration revision before adoption:
verify the exact complete species file sets, hashes, names, computed IDs and biome
entries with `verify_engine_sources`, then review the regenerated pin. A renamed,
removed, added or newly colliding species requires review. CI needs no sibling
engine checkout; source verification is an explicit read-only integration check.

Receipt semantic identities use canonical integer JSON (sorted object keys,
compact separators, raw UTF-8) with standard FNV-1a-64 and a versioned authoring
encoding label `canonical-integer-json-fnv1a64.v1`. Rule arrays have already been
validated in stable ID order. Missing policy and explicit empty overrides have
the same effective author checksum. These tokens are **not** qualified ARL5 or
snapshot identities. DS owns TLV type 5, species-content framing and the versioned
compiled-fallback contract, matching vectors and compatibility refusal. There is
no competing persisted sidecar or fallback identity in this slice.

## Export and refusal examples

Run the exporter with independently supplied exact game and engine revision pins;
it never discovers them from a working tree or claims that a pin makes dirty
content committed. A caller must retain the source revision provenance. The engine
pin must equal the inventory pin; refreshing that pin requires review.

```sh
python3 -I -B tools/export_game_data.py --root . --output staging/h1-candidate \
  --engine-revision 4c15419e9ba064c94e2933df73106991d92f1623 \
  --game-revision 7a54e52e34dd0c29504907ca7da9c4c45a5a1835
```

The shown game SHA identifies this slice's parent, for an illustrative test export;
a reviewed delivery must supply its actual H1 source revision. The output's parent
must already exist. The output must be fresh, including no dangling symlink.
The bundle layout is:

```text
h1-candidate/
  bundle/
    export-receipt.json
    runtime/
      data/common/sim/distant_policy.json
      data/common/sim/region_population.json
      data/common/items/items.json
```

Only `bundle/runtime/` is a runtime copy root. Inventory, receipt, identity
sidecars and acceptance evidence are excluded from it. Engine copies are a later,
separate reviewed operation. Each receipt row records source/destination path,
byte count, raw SHA-256 and semantic identity; the receipt also records independent
pins, inventory raw SHA-256 and semantic encoding version.

The exporter captures each source once and validates those exact bytes, including
all inventory/species/biome references, before output mutation. It stages the
entire bundle in a temporary sibling directory on the destination filesystem,
claims the fresh output by exclusive mkdir, verifies the reservation and renames
one complete bundle into it. Runtime bytes are never canonicalized or re-rendered.
Competing exporters refuse at the claim. There is no output merge/replace mode.
Readers must require the complete `bundle/`, which appears in one directory rename;
an empty outer reservation is not a successful export. This stdlib transaction
uses a reserved outer directory to provide portable exclusive publication.

On publication failure, rollback removes only the same owned, still-empty outer
directory by device/inode check and rmdir. Foreign files, replaced directories
and existing outputs are preserved. Staging is cleaned independently. A concurrent
writer who modifies the reservation can leave a refused outer directory for human
inspection, without a successful receipt. As with the rest of these filesystem
tools, arbitrary adversarial filesystem mutation is outside the cooperative
exclusive-reservation contract; rollback never recursively deletes the output.

| Input/refusal | Result |
|---|---|
| Policy key `grove-strider` instead of `grovestrider` | Unknown species; no fallback for a rejected present document |
| `resume_cap_ticks: true` or population `count: true` | Integer refusal |
| Unknown biome or plant/item population species | Reference refusal before publication |
| Nonempty valid policy fixture copied into shipping path | Empty-policy shipping boundary refusal |
| Existing output directory/file/symlink | Refusal; existing bytes unchanged |
| Item names `costarring` and `liquid` (H2) | Both FNV32 1582148253; the H2 validator/export extension refuses this collision |

## CI coverage and later runtime checks

The unchanged `.github/workflows/ci.yml` discovers `test_simulation.py` and
`test_simulation_export.py` using stdlib unittest on Linux and Windows. Dynamic
`SCHEMAS` discovery registers both validators. The shared content dispatcher parses
the captured bytes once and supplies `ctx.raw` for encoding/limit validation;
no family-specific registration list is introduced. Public-tree/content checks
remain required. This task permits local stdlib unittest with a clone-local TMPDIR,
removed afterwards; no engine/native/Blender/GPU or network execution is needed.

| Q25 Game policy / population requirement | Authoring coverage | Subsequent engine proof |
|---|---|---|
| Exact policy shape, duplicate/missing/unknown keys, future schema | Dedicated fixtures and all root/block key tests | Strict candidate parse/admission, previous policy unchanged |
| Absent versus malformed file | Candidate loader absence/read/nonregular/oversize/malformed tests | Enabled world open refuses rejected present file; flag-off consumers inert |
| Every numeric boundary | Every creature/plant minimum/maximum and adjacent refusal; population count/attempt endpoints | Matching strict engine fields/constants |
| Booleans/decimals/exponents, UTF-8/LF/BOM/final-LF/byte cap | Parsed-type and token tests; exact byte cap and oversize; dynamic content path | Engine strict loader encoding/resource parity |
| Unknown species/full-inventory collisions | All pinned names/IDs; collision after zero remap outside overrides; unresolved references | Strict resolved engine registry before session adoption |
| Deterministic rule/RNG order | Sorted unique IDs required, order preserved, shuffled order refused | Region-key order, ascending attempts, supplied region RNG mapping/rejection order and public vectors: **UNQUALIFIED** |
| Biome refusal | Nonempty unique pinned biome names; unknown/duplicate/invalid refusal | Authoritative biome/terrain/water/density query validation |
| Attempt/staging caps | count..128 attempts, 32 rules, per-rule 1..8 and total 64, exact/over limits | Bounded attempts and validated staging; reserve/prevalidate before commit |
| No callback before required terrain available | No runtime callback implemented; no fake terrain/store evidence | DS residency gating test; unavailable terrain must not mean successful empty population: **UNQUALIFIED** |
| Export exact bytes, one capture, references, fresh output, unchanged refusal, qualified rollback | Dedicated transaction tests, source mutation after capture, injected stage/publish failures and races | Review exact engine copies at named revision |
| Existing preset/species identity vectors and zero-remap collision | Existing preset suite unchanged; species byte-loop/golden/collision tests | Cross-language species/ARL5 vectors; item vectors remain H2 |

DS's later G2 consumer must run on the first eligible Active tick of an unpopulated
region, after required residency; process region keys, rule IDs and attempts in
order using the supplied RNG; sample inside the owning 512 m region; and stage
validated commands. Only successful callback and capacity/admission validation
may commit entities and allocate persistent IDs in staged order. Callback failure
must consume no IDs, discard staging, leave `populated` clear and latch the fault.
Repeated public `SpawnGroundObject` calls cannot implement this rollback seam.
Once-only population across restart/thaw and persistent evolution references need
real engine host/store tests, not an authoring simulator.

Enabled adoption retires only legacy wildlife and duplicate entities; trees,
rocks, bushes and their shared dressing RNG sequence remain intact. Local host
and headless server need common authoritative composition, including drinking
spots and every evolution-relevant reference. Default-off hashes, save trees,
artifacts and net/LREC1 bytes must remain unchanged. Shared integer activation
configuration and ARL5 integration remain DS prerequisites; no new ignored terrain
keys or float-backed u64 settings are authored here.

## Binding Q&A coverage and deviations

| Q&A | Slice 2 handling |
|---|---|
| Q1 | Authoring, source integration and native milestones separated; runtime unqualified |
| Q2 | Explicit authorized order change: acceptance harness parent; distant scenes deferred; independent exporter and portable reserved-output bundle transaction |
| Q3 | Exact two H1 mappings/schemas; author provenance excluded from runtime |
| Q4 | Exact policy root/block fields, domains, candidate-only parsing |
| Q5 | Empty shipping overrides enforced; examples only in fixtures |
| Q6 | Author-side absence/error/refusal tests; runtime admission/flag-off behavior remains DS work |
| Q7 | Full ds-fields engine pin, paths/hashes/expected IDs and biome pin; strict resolution and explicit source verification |
| Q8 | Dedicated exact engine species hash, UTF-8/NUL checks, required/zero-remap vectors; preset helper unchanged |
| Q9 | New bounded, sorted creature-only rules and starter population |
| Q10 | Author request/attempt/staging caps; residency, RNG and transaction acceptance documented as unqualified DS work |
| Q11 | Wildlife-only retirement/common-host composition/persistent references recorded for adoption; no engine files edited |
| Q12 | Dynamic SCHEMAS, strict shared byte loader, named limits and encoding; items deferred to slice 3 |
| Q13–Q20 | H2 catalogue/drop/seed persistence/ageing/presentation outside this slice; no H2 consumer or runtime claim |
| Q21 | Versioned canonical authoring checksums in transport receipt; ARL5 and complete species/fallback identity remain DS-owned |
| Q22 | Shared activation loader/host settings deferred to engine slice; no systems.json or preset changes |
| Q23 | Exact captured export, references, independent pins and receipts; documented refusals/qualified rollback |
| Q24 | Authoring may precede S8; nonempty policy and durable creature population require real adoption |
| Q25 | Every Game policy/population row above mapped to author tests or explicit subsequent runtime proof; export/species identity suites added |
| Q26 | Python author checks only; native/GPU acceptance stays NEEDS-NATIVE-RUN |

The independent exporter and its outer reservation/bundle layout replace the
unavailable distant-scene transaction under the declared order change. Population RNG
vectors and terrain callback tests are not invented: no engine contract/consumer
exists in this author slice, so those Q25 clauses remain adoption gates. No other
schema/identity/limit deviation is intended.
