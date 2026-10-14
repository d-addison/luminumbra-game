# H2 item authoring, slice 3

H2 supplies the catalogue, type identities, strict validator, collision fixtures
and exact-byte export receipts. Runtime remains **UNQUALIFIED**. Engine catalogue
admission, dropping, durable seed inventory and rendering belong to later slices;
authoring tests do not qualify those consumers. Packaged interaction, settling,
restart, due expiry/Frozen behavior and drawing remain `NEEDS-NATIVE-RUN`.

The declared stack is the game acceptance harness, then H1 simulation authoring at
`d912c04aa2453d995d5c0c517ca1f66d860c7e46`, then this slice on
`feat/h2-item-authoring-20261013`. Distant-scene authoring is deferred to v0.3.1.
This slice extends H1's independent exporter, captured-byte loader, identities and
dynamic validator registry. It has no dependency on a distant-scene file or sibling
engine checkout.
The binding H1/H2 Q&A supersedes the earlier planning documents.

## Catalogue and identities

| Source | Engine destination | Schema |
|---|---|---|
| `content/items/items.json` | `data/common/items/items.json` | `luminumbra.game.items.v1` |

```json
{
  "schema": "luminumbra.game.items.v1",
  "items": [
    {"id": "farming-seed", "despawn_after": 900, "payload": 0}
  ]
}
```

Root keys are exactly `schema` and `items`. Every definition requires `id`,
`despawn_after` and `payload`; only `render` is optional. IDs are unique lowercase
kebab-case, 1..64 ASCII bytes, and entries must already be sorted by ID. Validation
never sorts or inserts derived type IDs into runtime data. An empty catalogue is
structurally permitted; shipping content contains the first seed definition.

Lifetime and payload require strict u32 integers, 0..4294967295. The first seed's
payload must be zero: one generic plantable seed, with no species, genome or stack
count encoded. `900` counts **due ageing updates**, equivalent to 30 seconds only
when the owning region is due every 30 Hz tick. Zero lifetime means never despawn.

An optional render block has exactly `model_id` and `material_id`, both required.
The validator checks a nonempty model string and strict u32 material ID, then
refuses every rendering reference as unpinned. Even the proposed
`{"model_id":"farming-seed","material_id":2}` cannot resolve yet. Slice 7 must
implement/review the model resolver and procedural mesh; slice 8 must pin its
public model/material inventory before adding and exporting the render block.
No invented model registry, asset or rendering provenance is shipped here.

`tools/lumlib/item_identity.py` calls the existing `identity.fnv1a32` over the exact
ASCII item ID bytes: offset 2166136261, prime 16777619, wrapping modulo 2^32 at
each byte. Zero results refuse without remapping. `resolved_items` checks the
complete catalogue for duplicate names and distinct-name collisions. It uses
neither load order, display names, schema prefixes nor the catalogue checksum.

| Exact input | FNV-1a-32 result | Use |
|---|---:|---|
| Empty bytes | 2166136261 / `811c9dc5` | Hash helper vector only; empty ID refuses |
| `a` | 3826002220 / `e40c292c` | Item vector |
| `farming-seed` | 516719959 / `1ecc8557` | First item type |
| `costarring` | 1582148253 / `5e4daa9d` | Real collision with `liquid`; refuse both together |
| `liquid` | 1582148253 / `5e4daa9d` | Real collision with `costarring` |
| `fxdsatwp` | 0 / `00000000` | Real lowercase zero-result fixture; refuse, never remap |

The zero vector was independently derived by reversing FNV's odd-prime
multiplication and matching four-byte prefixes/suffixes; tests recompute every
vector with the binding constants. Existing preset/species vectors and the species
zero-to-one remap remain unchanged. Item zero refusal is a different rule.

Keep three identities separate: catalogue-derived u32 **type**, engine-allocated
u64 persistent object **id**, and game-defined u32 **payload**. Renaming an item
changes its type and requires compatibility refusal/review. The receipt's whole
catalogue semantic identity uses H1's canonical integer JSON (sorted object keys,
compact separators, UTF-8, already sorted item arrays) and standard FNV-1a-64,
offset 14695981039346656037. Its encoding label remains
`canonical-integer-json-fnv1a64.v1`. This checksum is authoring evidence; DS owns
the versioned ARL type-5 encoding, snapshot compatibility and cross-language
vectors. No competing persistence extension or identity sidecar is introduced.

## Validation and export

`tools/validators/items.py` registers `luminumbra.game.items.v1` through `SCHEMAS`.
The shared content dispatcher supplies captured bytes as `ctx.raw`. The item
document must live at the exact source path above. The shared strict JSON loader
refuses duplicate keys, exponent tokens, nonfinite numbers, invalid UTF-8, BOM
and CR. Final LF is required. Integer fields refuse booleans, decimals, floats,
strings, null, negatives and overflow. Missing/unknown keys, future schemas,
duplicate IDs, type collisions, zero types and unresolved references refuse.

Named limits are `MAX_ITEMS_BYTES = 1048576`, `MAX_ITEM_DEFINITIONS = 4096`,
`MAX_ITEM_ID_BYTES = 64` and `U32_MAX = 4294967295`. The catalogue definition cap
is independent of S5's live store limits, 65,536 objects / 4 MiB. Engine loaders
must match these authoring domains and encoding rules in a later slice.

The existing exporter now includes the two H1 simulation files and the item
catalogue in one transaction. Each fixed source is captured once, validated from
those bytes, staged completely and published by the same exclusive reservation
and complete bundle rename. A late item refusal leaves no simulation-only output.
Runtime copies preserve exact source bytes. The receipt retains source/destination,
byte count, raw SHA-256, semantic identity, inventory SHA-256 and independently
supplied game/engine revision pins. The engine revision must match H1's inventory.

```sh
python3 -I -B tools/validate_content.py --root . --allow-pending
python3 -I -B tools/export_game_data.py --root . --output staging/h2-candidate \
  --engine-revision 4c15419e9ba064c94e2933df73106991d92f1623 \
  --game-revision d912c04aa2453d995d5c0c517ca1f66d860c7e46
```

The example game SHA is this slice's H1 parent, suitable for an illustrative test
export only. A reviewed delivery must supply the actual H2 source revision and
retain its provenance; a supplied pin does not assert that working bytes were
committed. The output parent must already exist and the output must be fresh.

```text
h2-candidate/
  bundle/
    export-receipt.json
    runtime/
      data/common/sim/distant_policy.json
      data/common/sim/region_population.json
      data/common/items/items.json
```

Only `bundle/runtime/` is copied in a later, separately reviewed engine operation.
Inventory, receipts, sidecars and acceptance evidence stay outside runtime data.
The receipt schema remains `luminumbra.game.h1-export-receipt.v1`: its generic file
row shape has not changed, and now includes H2. H1's staging prefix and portable
outer-reservation layout are also retained. On failure, rollback removes only the
same owned, empty reservation, preserving foreign/replaced paths and existing
outputs. See [H1 export guarantees](simulation-authoring.md#export-and-refusal-examples).

| Refused input | Result |
|---|---|
| `despawn_after: true`, `900.0` or `9e2` | Strict integer/token refusal |
| `farming-seed` with payload equal to a species ID | Generic seed payload-zero refusal |
| Definitions `costarring` and `liquid` | Whole-catalogue collision refusal |
| Item `fxdsatwp` | Zero type refusal, no zero-to-one remap |
| Proposed or unknown model/material reference | Unpinned reference refusal before any publication |
| H1 policy species `grove-strider`, or unknown population biome | Shared bundle reference refusal |
| Missing/malformed/nonregular item source | Required source refusal; no default catalogue synthesized |
| Existing output directory, file, symlink or successful bundle | Refusal; existing bytes unchanged |

## Q25 coverage matrix and later gates

The unchanged `.github/workflows/ci.yml` discovers `test_items.py` and
`test_items_export.py` with stdlib unittest on Linux and Windows, alongside all
H1 tests. Public-tree/content checks remain required. Symlink/FIFO tests run on
POSIX; Windows tests do not assume symlink privileges. Local test temporary files
use a clone-local TMPDIR that is deleted afterwards. No native workload is needed
for authoring validation.

| Q25 area / every item-relevant requirement | Authoring coverage | Subsequent proof and owner |
|---|---|---|
| Game policy | H1 suites unchanged: exact shape, absence/malformed, all numeric domains/types/tokens/keys/references/full-inventory collisions | DS strict engine admission; [H1 matrix](simulation-authoring.md#ci-coverage-and-later-runtime-checks) |
| Identities: existing preset vectors | Existing `test_identity.py` retained and run | Engine vectors retained at integration |
| Identities: species vectors and zero-remap collision | Existing `test_simulation.py` retained and run | DS complete registry / content identity parity |
| Identities: item vectors | `ItemIdentityTests.test_binding_vectors_including_real_zero_and_collision`; empty helper vector and exact first type | Slice 6 must use matching engine FNV32 vectors |
| Identities: real costarring/liquid collision and zero item refusal | Real fixtures, independent byte-loop vectors, resolver/checker/export refusal; fixture repair tests | Slice 6 candidate/admission refusal; zero never remapped |
| Population | H1 sorted IDs/biome/attempt/staging tests retained | DS region RNG vectors and residency callback gating remain UNQUALIFIED |
| Export: exact byte receipts | Item raw formatting, destination/length/SHA-256, independent canonical checksum, pins and only three runtime files | Review separate exact engine copies |
| Export: single captured input | Mutation of all sources after item parsing; one capture of inventory and each source; output/receipts retain captured bytes | Same exact candidate/source revision provenance |
| Export: cross-reference refusal | Unpinned render fixtures refuse before staging; H1 unknown species/biome tests retained | Slice 8 pinned reference resolution; DS integration admission |
| Export: fresh destination and unchanged output on refusal | New successful item bundle retained on second export refusal; H1 file/directory/symlink/race tests retained | Delivery uses a fresh destination |
| Export: qualified rollback | Item-stage and whole-publication failure cleanup; foreign-content preservation; H1 replaced-reservation tests retained | Same owned-empty reservation boundary |
| Engine policy/items: transactional load/admission | Author candidate parsing leaves previous object unchanged; exact shape/u32/token/encoding/count/ID limits; required source refuses; runtime loader not implemented here | Slices 4/6: real engine candidate load/admission, matching vectors/limits, malformed present files never silently fall back; unknown restored types refuse |
| Drop: one press/one item and exhausted stock | No input, inventory or host caller in this slice | Slices 6/7: FarmDropSeed/B edge trigger; local interactive unpaused host; UI capture; held refusal never retries |
| Drop: catalogue/position refusal consumes neither seed nor ID | No fake host/store evidence | Slice 6: catalogue, generic payload, seeds, finite position/direction and session/enable prevalidation on real host |
| Drop: post-allocation failure burns ID while preserving seeds | Separate from prevalidation; no claim from author tests | Slice 6: real SpawnGroundObject post-allocation failure; decrement only on nonzero success; harvest telemetry unchanged |
| Durability: real caller, settling, save/reopen same ID/type/payload/lifetime/age/inventory | Catalogue supplies type 516719959, payload 0, lifetime 900 only | Slices 5/6: DS type-5 identity; narrow farmingInventory v1/seeds 0..INT_MAX in world_info.json; objects/inventory/allocator share snapshot transaction; no legacy migration or competing file |
| Durability: uninterrupted/resumed hashes, rollback/tamper refusal | Receipt checksum is transport/author evidence only | Real GameSession/headless tests in slices 5/6; packaged restart NEEDS-NATIVE-RUN |
| Ageing: unsettled expiry and zero lifetime | u32 zero/maximum accepted; due-update semantics documented | Real S5 store/host: unsettled objects also age; nonzero lifetime expires at threshold; u32 age saturation |
| Ageing: Reduced due-only, Frozen invariance and thaw | No simulated scheduler acceptance | Real host suite and packaged run: due-only Reduced ageing; Frozen no age; thaw continuation NEEDS-NATIVE-RUN |
| Presentation: same-count settling transform refresh | Render omitted; no renderer implemented | Slice 7: invalidate static cache or dynamic submission when y/settled changes at unchanged count |
| Presentation: expiry removal, reload rebuild, world-close cleanup | Unpinned references refuse | Slice 7: const-store mirror keyed by persistent ID, lifecycle tests; actual draw NEEDS-NATIVE-RUN/GPU |
| Presentation: no authoritative hash/activation effect | No assets, render entities or state authored | Slice 7: mirror never allocates IDs, activates regions or enters persistence/hash projections |
| Population adoption | H1 authoring only; no item population rules in v1 | DS: no-ID staging failure, atomic durable commit, once-only restart/thaw population, persistent references and promotion/demotion |
| Default off | No engine, systems.json, saved state, config or net format edits | Slices 4–7: existing hashes/save trees/artifacts/net/LREC1 bytes unchanged; malformed optional new files inert when active_regions is off |

Extend the real engine ground-object/headless suites for later proofs. Authoring
tests must not substitute a fake store for the caller/host acceptance path.
Catalogue-compatible durable H2 requires DS's split S8 type-5 identity prerequisite
even though full S8 creature adoption and S6 field consumers are not intrinsic
drop requirements. Source integration still needs named reviewed engine revisions
and CI; native/GPU qualification remains a separate gate.

The later drop caller uses player feet plus one metre of finite horizontal
forward direction and 0.25 m vertical clearance. It calls the real host
`SpawnGroundObject(type, position, despawn_after, payload)` and observes through
`GetGroundObjects() const`. Catalogue parsing/reference resolution happens in a
candidate; admission makes it immutable. Failed load leaves live state unchanged;
restored unknown types refuse rather than being removed or reinterpreted. Pickup
and a general inventory system are outside the first-drop contract.

The enabled consumer must save exactly the narrow
`"farmingInventory": {"version": 1, "seeds": 4}` shape in the existing
`world_info.json` transaction, with the actual authoritative count in 0..INT_MAX.
Planting, harvesting and dropping share this count; the HUD reads it. A new
H2-qualified save missing the required block refuses. The existing flag-off
controller path remains intact; no independent game inventory file is allowed.

S5 quantizes positions to integer millimetres, rounding the floating overload
half away from zero. Settling uses a downward authoritative terrain probe;
missing resident terrain leaves an object unsettled. Settling changes only y_mm
and the settled bit. Each due update increments active age once, saturating at
u32 maximum, including unsettled objects. Nonzero lifetime expires when that age
reaches its threshold. These are engine source contracts requiring real host
tests and later packaged evidence, not behaviors demonstrated by Python tests.

## Binding Q&A coverage and deviations

| Q&A | Slice 3 handling |
|---|---|
| Q1 | Authoring/source/native milestones separate; runtime UNQUALIFIED |
| Q2 | Authorized distant-scene deferral; explicit H1 simulation authoring parent; reuse independent exporter |
| Q3 | Exact item source/destination/schema; inventory and provenance excluded from runtime |
| Q4 | H1 exact policy shape retained |
| Q5 | H1 empty shipping overrides retained/enforced |
| Q6 | Rejected required item source refuses export; enabled/default-off engine admission remains later work |
| Q7 | H1 complete pinned species/biome inventory reused; no invented rendering inventory |
| Q8 | Species helper/vectors/remap unchanged; preset hash unchanged |
| Q9 | H1 bounded creature-only population retained; no item population keys |
| Q10 | H1 author caps retained; real DS callback/RNG/staging remains later adoption |
| Q11 | Wildlife-only retirement remains engine adoption; no engine changes |
| Q12 | Dynamic items SCHEMAS, strict shared encoding/loader, named bytes/definitions/ID/u32 limits |
| Q13 | Exact first catalogue, lifetime 900, payload 0; sorted IDs; omit render until slice 8 |
| Q14 | Existing FNV32 reused; exact vectors, real collision and zero refusal; never remap |
| Q15 | Type/object ID/payload distinctions; seed payload zero enforced, no species/stack interpretation |
| Q16 | Author candidate validation only; immutable admitted catalogue, host API/drop/restore unknown-type admission belong to slice 6 |
| Q17 | FarmDropSeed/B, edge/capture/position/stock and both allocation failure categories recorded as slices 6/7 gates |
| Q18 | Narrow transactional authoritative seed persistence recorded as slice 6 gate; no game save format |
| Q19 | Due-update lifetime, unsettled ageing, zero/Frozen/Reduced/thaw and actual caps documented; real host proof deferred |
| Q20 | Existing static/procedural surface distinguished from proposed resolver/mirror; no render block or runtime claim |
| Q21 | Shared canonical author checksum/receipt; DS alone owns ARL5/versioned compatibility |
| Q22 | Shared strict host activation profile remains engine work; no ignored terrain/config keys |
| Q23 | Third captured mapping extends H1 transaction/receipts; exact bytes, independent pins and refusal examples |
| Q24 | H2 authoring may land before S8; durable runtime needs slices 4–7 and split type-5 prerequisite |
| Q25 | Every item-relevant clause mapped above to author test or explicit later real engine/native/GPU proof |
| Q26 | Python checks only; no native/Blender/GPU execution; native rows NEEDS-NATIVE-RUN |

The only order deviation is the declared distant-scene deferral: H2 follows H1 instead
and reuses its reviewed independent export transaction. Retaining H1's receipt
identifier/layout avoids an unnecessary wire-format change. Refusing optional
render references until a public pin exists implements Q13/Q20's authoring
boundary; accepting the proposed reference now would invent integration evidence.
Engine catalogue/drop/durability and runtime qualification remain explicitly
outside slice 3. No other schema, identity or limit deviation is intended.
