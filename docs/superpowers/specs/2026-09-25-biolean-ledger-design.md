# Biolean ledger — design

> **Status as of 2026-09-25: design approved in conversation and revised against a 79-finding adversarial review (22 must-fix, all upheld); implemented per [`plans/2026-09-25-biolean-ledger.md`](../plans/2026-09-25-biolean-ledger.md) (branch `worktree-biolean-ledger`: implementing commits `6730da3..edd9d4c` plus the Task 10 docs commits and the final-review fix wave; merge commit to be recorded by the owner at merge; 1218 passed / 33 skipped in a CI-like checkout). The plan refines the spec in twenty-seven places, listed in its 'Plan refinements' section; the code follows the plan where the two differ.**
>
> This spec extends [Phase A](2026-09-21-biolean-design.md). Where it names kernel behaviour,
> the as-built references are [`docs/biolean/README.md`](../../biolean/README.md) and the
> code; where they disagree with this spec, the code wins and the divergence gets listed here.
>
> One §1 sentence changed after the owner approved it in conversation: a row that differs
> from an existing one **only in date** is now a duplicate (§1 Content key). The owner-agreed
> wording admitted it. The review argued, and the author agrees, that a date-only change is
> not new evidence. Reopen it if you disagree.
>
> ### Divergences
>
> The plan's 'Plan refinements', copied verbatim:
>
> 1. **Step 1a runs first and its fixes feed every later step.** Steps 2–7 evaluate the row after step 1a's character fixes are applied; steps 4 (aspect half), 7a and 8 evaluate the row after every non-null fix is applied. Otherwise a control character hiding a valid term id would yield `UNKNOWN_TERM` (fix `null`) that vanishes once the character fix is applied, breaking the spec's invariant.
> 2. **Step 4 has two halves.** Qualifier membership (`UNKNOWN_QUALIFIER`) always runs; when column 5 does not resolve its `options` are all 13. The aspect half (`LEDGER_ASPECT_MISMATCH`, `QUALIFIER_ASPECT_MISMATCH`) waits on column 5 and is what `deferred: [{"step": 4, "waits_on": [5]}]` names. `deferred` lists steps 4 and 8 only; step 7a runs with step 8 because they share the final row.
> 3. `--fact`, `--derivation` and `--computed` take inline JSON text, or `@<path>` to read a file.
> 4. A `derived` body is `{"derivation": <derivation>, "conclusion"?: <Prop>}`. A missing `conclusion` is filled from the verdict's elaborated goal (as column 15 is filled); a present one that differs is `LEDGER_CONCLUSION_MISMATCH`.
> 5. `show` also accepts `--recheck` (with `--store`), so "unless `--recheck` ran" is reachable. A `show` line is `{"file", "line", "hash", "entry", "fingerprint", "status", "contested", "rechecked", "recheck_errors"}`, `fingerprint` being the `SHA256:<unpadded base64>` form of the entry's signing key (spec §1); `status` is `admitted | stale | superseded_by_base` for `axiom` and `recorded` for `derived`, `null` without `--store`; `contested` is a bool or `null` without `--store`; `rechecked` is a bool and `recheck_errors` a list or `null`.
> 6. `verify` prints `{"ok": true, "ledger": <block>}` on success. Without `--store`, the base-dependent counters (`admitted`, `rechecked_ok`, `stale`, `stale_entries`, `superseded_by_base`, `superseded_entries`, `duplicate_content`, `duplicate_content_entries`, `contested`, `contested_entries`) are `null`, never `0`. `derived_rechecked`, `derived_failed` and `derived_failed_entries` are `null` unless `--recheck` ran.
> 7. A verification-cache hit skips only integrity step 5 (the signature check); steps 1–4, 6 and 7 always run, because they are cheap and the parsed entries are needed anyway.
> 8. The `LEDGER_BAD_OBJECT_TYPE` fix is the `object_type` of the subject's base annotation with the smallest annotation id.
> 9. In a `computed` body, a `conclusion.taxon` not matching `^NCBITaxon:\d+$` is `LEDGER_BAD_COMPUTED` at `/conclusion/taxon` with `fix` the `normalize_taxon` form when there is one, else `null` with `context: {"form": "NCBITaxon:<digits>"}`.
> 10. `init --principal` defaults to the key's comment, or `key16` when the `.pub` has none.
> 11. `load_store` is factored as `load_base` (the three files, their digests, the parser callables) plus store assembly; `ledger/load.py` holds `load_with_ledger`, which `load_store(ledger_dir=…)` calls through a function-level import (`kernel` → `store` at module level, and `ledger.check` → `kernel`, so `store` cannot import `ledger` at module level).
> 12. `init` refuses the two fixture keys through `sshsig.FIXTURE_KEY_DIGESTS`, with `LEDGER_UNSUPPORTED_KEY`.
> 13. The fork fixture's `LEDGER_CHAIN_BROKEN` also carries `context.fork_of_line` when the bad `prev` equals an earlier entry's hash in the same file.
> 14. At integrity, every shape or character failure is `LEDGER_MALFORMED` (with the specific message) except `LEDGER_VERSION` and `LEDGER_WRONG_LEDGER`, which keep their codes; at append, the same body faults use the §2 codes (`LEDGER_BAD_COLUMNS`, `LEDGER_BAD_CHARACTER`, …). At integrity every `LEDGER_MALFORMED` carries `fix: null` (§7, "every §3 integrity code"); `LEDGER_VERSION` keeps `fix: 1`, the §7 value row, which `append` never reports because it builds `v` itself.
> 15. `LEDGER_BAD_REFERENCE` is one error per bad value, each with `field: "/fact/5"` and `got` the whole column.
> 16. `LEDGER_BAD_KIND` carries `fix: null` and `options: ["axiom", "computed", "derived"]` (the §7 table lists it under `options: []`), because each clears the error when written at `/kind`. At integrity the same fault is `LEDGER_MALFORMED` (refinement 14) with `fix: null` and keeps those options.
> 17. In a `computed` body, a precondition `status` outside `met|unmet|unknown` is `LEDGER_BAD_COMPUTED` at `/preconditions/<i>/status` with `fix: null` and `options: ["met", "unknown", "unmet"]`; every other `LEDGER_BAD_COMPUTED` pointer carries `fix: null`, `options: []`, except `/conclusion/taxon` (refinement 9).
> 18. A `--store` lacking one of its three base files is an argparse usage error (text on stderr), as in Phase A. A base file that is present but cannot be read, gunzipped or decoded as UTF-8 is `LEDGER_MALFORMED` with `context.file` the store directory, exit 2, JSON on stdout, from every command that reads the store beside a ledger (`init`, `append`, `verify|show --store`, `prove|check|goals --ledger`); base-only `prove|check|goals` keep their Phase A behaviour.
> 19. Integrity step 7 also refuses an `axiom` whose recomputed annotation id repeats an earlier line of the same file: `LEDGER_INVALID_ENTRY`, `field: "/fact"`, `got` the row, `context.first_line` and `context.annotation_id`. It needs no base, so plain `verify` runs it too. Step 7a is a one-row check (`parse_gaf` over a single row always reports `duplicate_row: 0`) and cannot see a repeat, so the spec's §3 Load sentence crediting that refusal to 7a is corrected here; without this check a hand-signed repeat passes integrity and `StaticFactStore` raises a bare `ValueError` at load.
> 20. Nesting is bounded: `MAX_DEPTH = 64` (`format.py`). `canon` refuses a deeper object with `ValueError`, as it refuses NaN, so nothing deeper is ever hashed or written; `parse_line` returns `(None, "nesting deeper than 64 levels")` on a `RecursionError` from `json.loads` or on that refusal; the append body parser applies `nesting_depth` before any other check. Without the bound a hostile line crashed `verify` with a traceback instead of exit 2: a ~1,500-deep line passed `parse_line` and `shape_errors` and overflowed `character_errors`.
> 21. §2 step 1a applies to dict keys, not only to string values: a key that is not NFC or holds a lone surrogate is `LEDGER_BAD_CHARACTER` at the containing object's pointer (`""` at the top level), `got` the code point, `fix` null (renaming a key is not a value substitution `pointer_set` can apply). Keys the schema fixes are ASCII already; this reaches the free-form objects.
> 22. Column 13 is canonical: `taxon:<digits>` with no leading zeros (and the same for the second `|` value). Step 6 reports every other spelling, `taxon:09606` included, with the canonical fix, so a resubmission under a non-canonical spelling is caught by the step 8 duplicate check instead of being admitted as a distinct row. Step 6 never calls `int()` (Python's 4300-digit limit made a long taxon raise), and in recheck mode a row with a column that is not UTF-8-encodable (a lone surrogate) skips the hashing steps 7a/8 with `annotation` None: the step-1a error already names the fault and `annotation_id` would raise. Other step-1a faults still hash, so a line separator inside a column cannot become a second row.
> 23. The verifier's exception contract is explicit: `verify_ledger` raises `LedgerIntegrityError` and nothing else on any input (a deeply nested `ledger.json`, an unreadable or unstattable file or directory are `LEDGER_MALFORMED` with `context.file`), `check_extends` raises `ValueError` and nothing else (and validates a heads map: key16 keys, non-negative integer `entries`, `head` "" exactly when `entries` is 0, else 64 hex), and the cache is an optimisation that never fails a ledger: a mark that cannot be written is counted in `LedgerState.cache_mark_failures` and reported as `ledger.cache_mark_failures` (spec §3 report block gains that key); a cache that cannot be read is a miss. Stat-style checks treat `OSError` as "not that kind of file" so the contract holds on Python 3.10–3.14 (before 3.13 `pathlib` raises on EACCES).
> 24. **A derived entry is re-proved only by `--recheck`, and only a failure on its own base fails the run.** Derived entries add nothing to the store (they are recorded, not admitted), so no load re-proves one and none fails a load: `append`, `prove|check|goals --ledger` and `verify|show --store` without `--recheck` never run the §2 `derived` rule, and no derived entry is ever `LEDGER_INVALID_ENTRY`. A revoked key's deleted file must not make every load fail through another signer's derived entry that cited one of its facts. `verify|show --recheck` re-run the rule, conclusion comparison included, over the loaded store (base plus admitted ledger facts). Every failure is counted in `derived_failed` and listed in `derived_failed_entries` with its `errors`, `kernel_codes` (the kernel's error codes) and `same_base` (true when the entry's `base` digests are the loaded base's). A failure with `same_base` true makes the report's `ok` false and the exit code 2 (the CI gate), with the report still printed (`show` prints its rows and one line on stderr); a failure on another base is counted and listed the same way, but `ok` stays true and the exit code 0. This amends refinement 6 (`ok` can be false) and the §7 exit-2 output (a `--recheck` exit 2 prints the report, not `{"errors": [...]}`).
> 25. **`append` writes only onto the file it verified.** `LedgerState.file_sha256` keeps the sha256 of each file integrity verified. `append` opens `ledger/<key16>.jsonl` with mode `"ab"`, takes `fcntl.flock(LOCK_EX)` (a no-op where `fcntl` is missing), re-reads the file under the lock through a second descriptor that must be the same open file, and writes its line only when the file still hashes to the verified digest (an absent file counts as empty). Otherwise it raises `LEDGER_CHAIN_BROKEN` ("the file changed since it was verified; retry", `field: "/prev"`, `context.file` and `context.line`) and writes nothing. Two concurrent appends under one key on one machine give one entry and one exit-2 retry instead of a fork; two clones appending under one key still diverge, and `verify` refuses the merged file as a fork.
> 26. **`new_subject` and the `LEDGER_BAD_OBJECT_TYPE` fix read the store `append` checks against.** Step 2's `counters.new_subject` and step 6's object-type fix (refinement 8) consult the loaded store, base plus admitted ledger rows, where spec §2 step 2 and refinement 8 say the base only: a subject an admitted ledger entry introduced is not counted new again, and the fix is the `object_type` of the subject's annotation with the smallest id in that store, which can be a ledger row. `docs/biolean/ledger.md` describes this behaviour.
> 27. **`init` also writes an empty `ledger/<key16>.jsonl` for its key.** Spec §7 says only that `init` creates `ledger/`; git tracks no empty directory, so a clone of a fresh ledger had no `ledger/` and failed `verify`. The empty file (spec §1: an intact chain with no entries; `heads()` gives `{"entries": 0, "head": ""}`) keeps the directory in a clone, and `append` treats it exactly as an absent file (`prev` "", line 1). `init` creates it only when no file is there and never writes to an existing one; an empty key16 file it finds holds no signer, so it is not a key16 collision.

**Date:** 2026-09-25
**Status:** §0 fixed with the owner; §1–§9 revised against the review

Phase A made Biolean a checker: an agent emits a derivation over GO and GOA, the kernel
returns ACCEPTED or REJECTED with typed errors. The facts it can cite are one frozen release
pair. Nothing an agent proves, and nothing a paper reports, has anywhere to go.

The ledger is where it goes. It is an append-only set of signed, hash-chained records, each
one checked by the kernel before it is written, that extends the frozen release with facts
from literature (now) and from discharged analyses (Phase B). Anyone with a key on the
trusted list can append. Anyone can check that every entry present was signed by a key on a
trusted list whose sha256 they pinned (§3). Without a pin, `verify` proves only that the
directory is internally consistent, and the trusted list is whatever was last pushed to it.
`verify` also does not prove that nothing was removed: dropped tail entries, a deleted file,
or an older version of a file all verify. What guards against that is a comparison with an
earlier state (`verify --extends`, §3) and the ledger repo's reviewed history (§6). Git
carries the entries. For the trusted list, git is the trust root unless the consumer pins it.

## §0 — Fixed decisions

Settled with the owner on 2026-09-25. Not reopened by this document.

1. **The trusted base stays one thing.** The ledger's format, append check and verifier live
   in `methods_graph.biolean`, beside the kernel. Dogma and every other agent framework are
   clients. Nothing in a UI repo is in the trust boundary, and the ledger code imports no
   bench or network module (§1, note on `read_release`).
2. **Permissioned first.** Contributors are known keys in an `allowed_signers` list. A cost
   or proof-of-work gate on appends is a roadmap item, added later as a policy on the
   append path. The entry format must not change when it arrives.
3. **Literature facts first, Phase B second, rules never.** The `axiom` kind (a GAF 2.2 row
   with a DOI) is the v1 loop. The `computed` kind is fully specified now and refused at
   append until `discharge` exists. New rules and slices are code and go through the code
   repo's normal review.
4. **An entry is a GAF row plus an envelope.** The ledger is an extension of the existing
   ontology data, in its own format, so the existing parser, annotation id and store apply
   unchanged and any consumer that reads GAF can read a ledger fact.
5. **Signed, hash-chained JSONL, one file per contributor.** Every entry verifies on its
   own, on any machine, against the trusted list. Git is transport. One file per key means
   no merge conflicts and no global order.
6. **Verification is in-repo, from RFC 8032, verify-only.** Signing uses the contributor's
   existing ed25519 SSH key through `ssh-keygen -Y sign`. Verification is a pure-stdlib
   implementation pinned by the RFC's test vectors and by fixture signatures made once with
   real `ssh-keygen`. No new runtime dependency; no subprocess in tests.
7. **The kernel decides structure, never truth.** An `axiom` entry is admitted when it is
   well-formed against the base and carries provenance. A contradiction with an existing
   fact does not reject it; the entry is marked contested and `check()`'s `conflicts`
   report it. Consumers choose which evidence classes and contested states they trust.

**North star, not a requirement.** The error payloads and the CLI are written so that a
weak model, given nothing but the rejection, can produce an accepted entry on the next try.
Every rejection carries a concrete `fix` when one exists, or the complete list of values
that would work. The kernel supplies the biology the model lacks.

## Non-goals for v1

- Anonymous or permissionless contributors, any cost gate, any consensus protocol.
- Resolving a DOI or PMID over the network. v1 checks syntax only.
- Key expiry or a revocation list. Removing a key from `allowed_signers` makes the whole
  ledger fail integrity (exit 2: nothing loads and no one can append) until that key's file
  is also removed from `ledger/` (§3). Softer semantics come with `valid-before` support later.
- Phase B `discharge`. The `computed` kind is schema-checked and then refused.
- Other slices (gene to disease) and other organisms as a first-class concern. The taxon
  column is free; the base is human GOA.
- Any UI. Dogma renders ledger state; this spec gives it a CLI and a JSON contract.

## §1 — Entry format

A ledger is a directory:

```
<ledger>/
  allowed_signers          # OpenSSH allowed-signers file; the trusted list
  base.json                # the base every entry in this ledger is checked against (§6)
  ledger.json              # {"ledger": "<32 hex>"}, minted by init; the ledger's identity
  ledger/<key16>.jsonl     # one file per contributor key; append-only; a single hash chain
```

`key16` is the first 16 hex characters of the sha256 of the contributor's raw public key
blob (the bytes that base64-decode from the `ssh-ed25519 AAAA…` field). The full digest is
the contributor's id everywhere else.

### Canonical bytes

Each line of a `.jsonl` file is one entry, written as `canon(entry) + b"\n"`, where

```python
canon(obj) = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=True, allow_nan=False).encode("ascii")
```

Wherever this spec says **canonical bytes**, it means `canon(...)` with no trailing
newline. A line whose bytes are not `canon(json.loads(line)) + b"\n"` is `LEDGER_MALFORMED`.
So is a line that parses NaN or Infinity (`json.loads` with `parse_constant` raising), a
blank line, a final line without `\n`, or any `\r`. That is how whitespace and key-order
tampering is caught without a parser of its own. An empty file is intact and holds no
entries; the first entry appended to it has `prev: ""`.

### Example

Shown pretty-printed; on disk it is one canonical line.

```json
{"v": 1,
 "kind": "axiom",
 "ledger": "<32 hex>",
 "fact": ["UniProtKB", "P04637", "TP53", "involved_in", "GO:0006915",
          "DOI:10.1038/s41586-026-00001-0", "IDA", "", "P", "", "", "protein",
          "taxon:9606", "20260925", "biolean:3f2a9c1e8b7d6054", "", ""],
 "base": {"obo": "<sha256 hex>", "gaf": "<sha256 hex>", "eco": "<sha256 hex>",
          "release": {"go_basic_data_version": "releases/2026-07-26",
                      "goa_date_generated": "2026-05-21T08:10",
                      "goa_go_version": "http://purl.obolibrary.org/obo/go/releases/2026-04-27/extensions/go-plus.ofn"}},
 "check": {"kernel": "0.1.0", "annotation_id": "gaf:9d1c…", "contested_by": [],
           "counters": {"new_subject": 0}},
 "prev": "",
 "by": "sha256:3f2a9c1e8b7d6054…<64 hex>",
 "ts": "2026-09-25T10:00:00Z",
 "sig": "U1NIU0lH…"}
```

### Fields

Every entry has exactly the common fields `v, kind, ledger, base, check, prev, by, ts,
sig`, plus exactly its kind's fields, plus optionally `admission`. `admission` is reserved
for §8: an object that v1 treats as opaque, covered by the hash and signature, and never
written by v1 `append`. `check` may carry the reserved key `reference_resolved` (§8). Any
missing field, any other key, or a value of the wrong JSON type is `LEDGER_MALFORMED`.
Integer fields must satisfy `type(x) is int`: `true` and `1.0` are not `1`.

| Field | Meaning |
|---|---|
| `v` | Format version. The JSON integer `1`. Anything else is `LEDGER_VERSION`. |
| `kind` | `axiom`, `derived` or `computed`. |
| `ledger` | 32 lowercase hex, minted at random by `init` and stored as `{"ledger": …}` in `<ledger>/ledger.json`. Must equal the directory's id (`LEDGER_WRONG_LEDGER`, an integrity failure). It is inside the signed bytes, so a chain signed for one ledger never verifies in another. Without it, contributor K's whole file from any ledger that lists K (a scratch ledger, another organism's ledger) would copy unchanged into this one and re-check clean. |
| `fact` | `axiom` only. The 17 GAF 2.2 columns, as strings, in GAF order. Column 15 (`assigned_by`) is `biolean:<key16>` of the signer; `append` sets it, and any other non-empty value is `LEDGER_ASSIGNED_BY`. |
| `derivation`, `conclusion` | `derived` only. The **elaborated** Phase A derivation JSON (§2) and its goal `Prop`. |
| `method`, `dataset`, `graph_hash`, `preconditions`, `run`, `conclusion` | `computed` only. §5. |
| `base` | `{obo, gaf, eco, release}`. For each of the three files, the sha256 (64 lowercase hex) of its contents **as `load_store` parses them**. For `goa_human.gaf.gz` that means the decompressed bytes: a gzip header carries an mtime and a file name, so recompressing identical content would otherwise change the base, and a `.gaf` and a `.gaf.gz` of one release are the same base. This is not the `sha256` a `biolean fetch` `snapshot.json` records, which hashes the downloaded `.gz`. `release` is the dict `read_release` returns, verbatim: `go_basic_data_version`, `goa_date_generated`, `goa_go_version`. Base identity is the three digests; `release` is informational. |
| `check` | What `append` found. The hash and signature cover it, and no reader trusts it: §3 recomputes whatever it uses. `axiom`: `{kernel, annotation_id, contested_by, counters: {new_subject}}`. `annotation_id` is the id `parse_gaf` assigns (`"gaf:"` + the first 16 hex of the sha256 of the 17 columns joined by tab), computed over the row after `append` has filled column 15, so it equals what the store will hold. `contested_by` is the append-time snapshot from §2 step 9. `derived`: `{kernel, axioms: [annotation ids cited], conflicts: [annotation ids]}`, taken from the verdict. `kernel` is `methods_graph.__version__` at append time and is informational. v1 never writes a `computed` entry. |
| `prev` | The entry hash (below) of the previous entry in this file, `""` for the first. |
| `by` | `sha256:` + 64 lowercase hex of the signer's public key blob. Must match the file name and the key inside `sig`. This is the digest OpenSSH prints as `SHA256:<unpadded base64>` in `ssh-keygen -lf`; contributors will read out that form, so `init`, `show` and every `LEDGER_UNKNOWN_SIGNER` or `LEDGER_SIGNER_MISMATCH` error print both. |
| `ts` | `YYYY-MM-DDTHH:MM:SSZ` exactly (`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`, a real UTC instant). `append` takes it from its caller, as `fetch.py` takes `created_at`; the CLI reads the clock, tests pass a fixed value, so an entry's canonical bytes and its fixture signature are stable. Covered by the hash and signature like every field except `sig`. Nothing orders or filters by it. A malformed `ts` is `LEDGER_MALFORMED` at verify. |
| `sig` | The SSH signature over the entry's canonical bytes without `sig` (§4): the armor's base64 lines concatenated with no whitespace, standard alphabet, padded. `base64.b64encode(base64.b64decode(sig, validate=True)).decode() == sig`, or `LEDGER_BAD_SIGNATURE`. Python's decoder accepts non-canonical padding bits even in strict mode, and the entry hash excludes `sig`, so this rule is what makes `sig` immutable. |

**Entry hash.** `hashlib.sha256(canon(entry without "sig")).hexdigest()`: 64 lowercase hex
characters, no prefix. The next entry's `prev`, the hash that `append` prints, and the
`expected_prev` carried by `LEDGER_CHAIN_BROKEN` all use this form. The signature covers the
same bytes, `canon(entry without "sig")`, which `append` passes to `ssh-keygen` on stdin
(§4). The signature is not over the entry hash: `ssh-keygen` hashes the message itself,
with sha512.

**Note on `read_release`.** `read_release` and `gaf_header` move to `biolean/store.py`, and
`bench/items.py` and `fetch.py` import them from there, so the ledger code imports no bench
or network module. Today `bench/items.py` imports `kernel.check`, `tactics.prove` and
`methods_graph.fetch.gaf_header`, and `fetch.py` imports `subprocess` and `urllib.request`;
a verifier that called `read_release` there would pull both into the trust boundary §0.1
says stays one thing.

### What is a fact, and what is a duplicate

The GAF row is the whole fact. A fact that differs from a base row in reference, evidence
code or with/from is a different row and is admitted: it is another piece of evidence for
the same proposition, which is how GOA itself works. One that differs only in date,
`assigned_by`, the display columns (3, 10, 11, 12), or the spelling of a pipe list or taxon
is a duplicate (§2 step 8). A near-duplicate flood is a volume problem for the later cost
gate, not a correctness problem here.

**Content key.** The duplicate and supersession rules compare the `Annotation` that
`parse_gaf` builds from a row, not its raw columns and not its annotation id. The key is
`(subject, qualifier, negated, term, taxon, references, code, with_from, interacting_taxon,
extension, form)`. It leaves out `assigned_by`, `date`, the display columns and the fields
derived from other fields (`term_raw`, `aspect`, `eco`). It uses the parsed forms: canonical
term, sorted references, normalized taxon, so reordering a pipe list or writing
`NCBITaxon:` for `taxon:` does not make a new row. The annotation id cannot serve as the
key: it hashes column 15, which is `biolean:<key16>` on every ledger row, on no base row, and
differs between any two signers. The first five key fields are the store's `Prop` key
(`store.py:32`), so a base lookup is `store.matching(prop)` followed by a comparison of the
other six. Neither `parse_gaf` nor the base load changes.

## §2 — Append check

`mg biolean ledger append` runs the check, signs, and only then writes. Before the check it
runs §3 integrity over every `ledger/*.jsonl` and requires the signer's key in
`allowed_signers` with `biolean-ledger` permitted; either failure is exit 2. A `--store`
whose three digests differ from `base.json` is `LEDGER_BASE_MISMATCH`, exit 2. A body that
is not JSON of the expected type is `LEDGER_BAD_BODY`, exit 3. Every rejection is a list of
error objects in the shape §7 defines: `{code, message, field, got, fix, options, context}`.
This is a new shape, not the kernel's `{step, code, message, expected, actual, suggestions}`,
and no kernel `Error` is ever passed through. Exit 3 on rejection, 0 on acceptance, 2 when
the ledger or store cannot be read, fails integrity, or signing fails.

### `axiom`

If step 1 fails, nothing else runs. Otherwise steps 1a to 8 all run, and every failure is
reported in one response, ordered by step and then by column. Two steps depend on answers
from other steps. Step 4 needs the resolved term. Step 8 needs the final row, with column 15
filled. Each is evaluated against the entry with every non-null `fix` in the same response
applied. So an obsolete term whose `replaced_by` is in another namespace gets its column 9
and column 4 errors in that same response, computed against the replacement. A step is not
run if its input waits on an error whose `fix` is `null`; it is listed in the response's
`deferred` list as `{"step": <n>, "waits_on": [<column numbers>]}`. **Invariant:** applying
every non-null `fix` in one response at once leaves exactly the reported errors whose `fix`
was `null`, plus errors from steps in `deferred`, and introduces no other error. Step 9 runs
only when steps 1 to 8 pass.

1. **Shape.** Exactly 17 string columns (`LEDGER_BAD_COLUMNS`, `field: "/fact"`, `fix: null`,
   `options: []`, `context: {"columns": [the 17 GAF 2.2 column names in order]}`). The names
   are a new `GAF_COLUMNS: tuple[str, ...]` in `gaf.py` and are the keys of the object form
   (§7). `v` is the JSON integer 1 (`LEDGER_VERSION`, `field: "/v"`, `fix: 1`; `true` and
   `1.0` fail). `kind` is known (`LEDGER_BAD_KIND`, `field: "/kind"`, `fix: null`).
1a. **Characters.** Every string in the entry encodes to UTF-8, so it has no lone
   surrogates, and equals its Unicode NFC form. No fact column contains U+0000–U+001F (tab
   included), U+007F–U+009F, U+2028, U+2029, or any Cf, Zl or Zp character; that set includes
   every character `str.splitlines()` splits on. Columns 1, 2, 4–9 and 13–17, where
   non-empty, contain only printable ASCII 0x21–0x7E, with no space. This step does not
   decide whether a column may be empty; steps 2–7 do that, and columns 8, 16 and 17 may be
   empty, as may column 15 before step 7 fills it. A failure is `LEDGER_BAD_CHARACTER`,
   `field` the column, `got` the code point as `U+XXXX`, `fix` the value with those
   characters removed and NFC applied. Why: a tab would turn the row into 18 fields at load;
   a trailing `\r` is stripped by `parse_gaf` so the store id would differ from
   `check.annotation_id`; a lone surrogate survives `ensure_ascii` and then crashes
   `annotation_id`; U+2028 in column 17 injects a second row into any loader that splits
   text.
2. **Subject.** Columns 1 and 2 non-empty, column 1 matches `^[A-Za-z][A-Za-z0-9_.-]*$`,
   column 2 has no whitespace or `|` (`LEDGER_BAD_SUBJECT`, one error per bad column). A
   subject the base has never annotated is admitted and counted `new_subject`.
3. **Term.** Column 5 must be a primary id of a non-obsolete term in the base.
   - unknown: `UNKNOWN_TERM`, `fix: null`, `options: []`
   - an `alt_id`: `LEDGER_ALT_ID`. `fix` never names an obsolete term. If the primary is
     live, `fix` is the primary. If the primary is obsolete, `fix` and `options` are whatever
     `OBSOLETE_TERM` gives for that primary, and the message names both hops. The kernel's
     `_check_term` stops at the alt id and never checks the primary; 360 of the pinned
     release's 3,646 alt ids have an obsolete primary.
   - obsolete: `OBSOLETE_TERM`. `fix` is the single live `replaced_by` when there is exactly
     one. Otherwise `fix: null`, and `options` is the live `replaced_by` terms if there are
     several, else the live `consider` terms (even one: `consider` is not a replacement, so
     a caller must choose), else `[]`. `context` carries both raw lists. In the pinned
     release 5,825 of 10,248 obsolete terms have no fix, and 71 single `replaced_by` targets
     are in another namespace.

   Every term a `fix` or `options` offers is a live primary id in the base. `GO:0002391`'s
   `consider` list includes `GO:000666`, which is not a term.
4. **Aspect and qualifier.** Column 9 must equal the term's namespace aspect
   (`LEDGER_ASPECT_MISMATCH`, `fix`: the right letter). Column 4 is `NOT|q` or `q`; `q` must
   be one of the 13 qualifiers (`UNKNOWN_QUALIFIER`) and legal for that aspect
   (`QUALIFIER_ASPECT_MISMATCH`). For both codes `fix: null` and `options` lists only the
   qualifiers legal for the term's aspect (2 for F, 7 for P, 4 for C), never all 13;
   `UNKNOWN_QUALIFIER` lists all 13 only when column 5 does not resolve. Both are whole
   column 4 values: `field` is `/fact/3`, not `q`. When `got` starts with `NOT|`, every option
   starts with `NOT|` too (`NOT|involved_in`, never `involved_in`). If column 4 contains `|`
   but does not start with exactly `NOT|`, `options` is `[]`. The kernel check reused here
   sees only the bare `q` (`Prop.negated` is separate) and returns aspect letters in
   `expected`, so the append check puts the prefix back and never passes the kernel's
   values through. No fix changes polarity: `parse_gaf` reads polarity only from the prefix,
   and a bare substitution would flip the claim and pass.
5. **Evidence.** Column 7 must map to ECO through the base's mapping (`LEDGER_ECO_UNMAPPED`,
   `fix: null`, `options`: the mapped codes). Column 6 is `|`-separated. Every value with
   prefix `DOI:` must match `^DOI:10\.[0-9]{4,9}/\S+$` (non-ASCII allowed, NFC per step 1a),
   `PMID:` must match `^PMID:[1-9][0-9]*$`, and `GO_REF:` must match `^GO_REF:[0-9]{7}$`
   (`LEDGER_BAD_REFERENCE`, `field: "/fact/5"`, `fix: null`). At least one value must carry
   one of these prefixes (`LEDGER_REFERENCE_REQUIRED`, `fix: null`). Values with other
   prefixes are allowed and not checked.
6. **Taxon, date, object type.** Column 13 is one or two `|`-separated values, each exactly
   `taxon:<ASCII digits>` (`LEDGER_BAD_TAXON`). `normalize_taxon` also accepts `9606`,
   `NCBITaxon:9606`, padded values and non-ASCII digits, none of which is GAF 2.2. When
   every value is in a spelling `normalize_taxon` accepts, `fix` is the whole column
   rewritten as `taxon:<d>[|taxon:<d>]`; otherwise `fix: null` and `context: {"form":
   "taxon:<digits>"}`. Column 14 is `YYYYMMDD`, a real date (`LEDGER_BAD_DATE`; `fix` the
   reformatted date when `got` is an unambiguous ISO 8601 date, else `null` with `context:
   {"form": "YYYYMMDD"}`). Column 12 non-empty (`LEDGER_BAD_OBJECT_TYPE`, `field:
   "/fact/11"`, `fix`: the subject's object type in the base when the subject is known, else
   `null`).
7. **Assigned by.** Column 15 is empty (then `append` fills it) or already equals the
   signer's `biolean:<key16>` (`LEDGER_ASSIGNED_BY`, `fix`: that value).
7a. **Round trip.** `parse_gaf(["\t".join(fact)], …)` is called with the fact as a single
   list element, never as text that is then split. It must return exactly one annotation,
   with 0 on every drop counter (`bad_column_count`, `unknown_qualifier`,
   `bad_taxon_cardinality`, `bad_taxon_format`, `duplicate_row`). The annotation's id must
   equal `annotation_id(fact)` computed over the columns as signed. That id is
   `check.annotation_id`. Otherwise `LEDGER_MALFORMED`.
8. **Duplicate.** The row's content key (§1) must not equal that of any base row or of any
   *other* entry in any `ledger/*.jsonl` (`LEDGER_DUPLICATE`, `field: "/fact"`, `fix: null`,
   `options: []`, `context: {"existing": [{"annotation_id": <id>, "source": "base" |
   "ledger/<key16>.jsonl:<line>"}, …]}`, sorted). `existing` is a list because the base
   already holds rows that differ only in column 15 (3 pairs in the pinned GAF). The base's
   keys come from the `Annotation`s `parse_gaf` produced, so no second pass over the GAF is
   needed. No substitution clears this error; the row must change.
9. **Contested.** Not a rejection. `contested_by` is the sorted `annotation` values of
   `check(d, store)["conflicts"]` over base plus the local ledger, where `d` is
   `{goal: P, steps: [{id: "s1", rule: "axiom", conclusion: P}], root: "s1"}` and `P` is the
   fact's `Prop` (subject `col1:col2`, `normalize_taxon` of the first column 13 value,
   negated from the `NOT|` prefix). `check()` takes a derivation, not a `Prop`, and its
   `conflicts` entries are dicts. It is recorded as an append-time snapshot, and no reader
   uses it (§3): a later entry can contest an earlier one. Once the fact is loaded, the
   kernel's recomputed `conflicts` show the contradiction for anything that cites it or its
   counterpart.

Steps 3 and 4 call the kernel's term check (`_check_term`, made public as `check_term`) and
a qualifier/aspect check extracted from `_check_prop` without its subject and taxon checks.
That extraction is a change to the trusted base and gets a test. `_check_prop` itself is
never called: it emits `UNKNOWN_SUBJECT` for subjects step 2 admits as `new_subject`, and
`MALFORMED` for the `taxon:` spelling GAF uses. Each kernel result is re-emitted in the §7
shape with the codes and `fix`/`options` values above: `ALT_ID_IN_KERNEL` becomes
`LEDGER_ALT_ID`, `OBSOLETE_TERM`'s `expected` dict becomes `fix`/`options`/`context`, and
the kernel's aspect letters for `QUALIFIER_ASPECT_MISMATCH` become qualifier options. The
kernel's `Error` is never passed through. An entry the append check admits is one the
kernel can cite.

### `derived`

`derivation` is checked by `elaborate_and_check()` against base plus admitted ledger facts,
the CLI's own path. The entry stores the **elaborated** derivation, so its identifiers are
canonical and `ALT_ID_IN_KERNEL` stays unreachable. It is admitted only if all four of the
following hold, and every one that fails is reported:

- **The verdict is ACCEPTED.** Otherwise one `LEDGER_DERIVATION_REJECTED`: `field:
  "/derivation"`, `got: null`, `fix: null`, `context: {"kernel": {"errors": [...],
  "elaboration": [...]}}`, the verdict's own six-key errors unchanged. No `field` is derived
  from kernel errors: they name a step id, not a path, `step` is null for goal, root and
  document errors alike, and one bad term can appear twice byte for byte. A caller iterates
  on the kernel's errors inside `context`.
- **`sorry_count == 0`.** Otherwise one `LEDGER_SORRY_USED` per used sorry: `field:
  "/derivation/steps/<i>"` (the index of the step whose `id` the verdict's `sorries` entry
  names), `got` that entry, `fix: null`.
- **`unused_sorries == 0`.** Otherwise one `LEDGER_SORRY_UNUSED` per unused sorry, in the
  same shape.
- **`conclusion` equals the verdict's elaborated `goal`.** Otherwise
  `LEDGER_CONCLUSION_MISMATCH`: `field: "/conclusion"`, `got` the given conclusion, `fix`
  the goal.

The kernel accepts a derivation containing a sorry with an empty error list, so the two
sorry codes are the ledger's own. A `derived` entry is a citable record of a proven result:
who, when, against which base. It is **not** replayed as a fact; it adds nothing to the
store. Its value is provenance for an agent's research claim, and `--recheck` (§3)
re-proves it on demand.

### `computed`

Schema-checked as §5 defines, so a producer can test its output today; then refused with
`NOT_YET_DISCHARGEABLE`, exit 3, `fix: null`.

## §3 — Verify and load

### Integrity, per file

`ledger verify` and `load_store(…, ledger_dir=…)` run the same routine over every
`ledger/*.jsonl`:

0. **Signers pin.** When the caller gives a pin (`--signers-sha256 <hex>` on `verify`,
   `show`, `prove`, `check` and `goals`; `expected_signers_sha256=` on `load_store`), the
   sha256 of the `allowed_signers` file bytes must equal it. Otherwise
   `LEDGER_SIGNERS_MISMATCH`, exit 2, and no entry is read. A consumer that does not pin
   trusts whoever last wrote the directory.
1. File names match `^[0-9a-f]{16}\.jsonl$` and are regular files, not symlinks; any other
   entry under `ledger/` is `LEDGER_MALFORMED` naming it. `allowed_signers` parses (§4); two
   listed keys with the same key16 are `LEDGER_MALFORMED`.
2. Each line re-serializes canonically to itself (§1), has `v` the JSON integer 1, `ledger`
   equal to `ledger.json`'s id (`LEDGER_WRONG_LEDGER`), exactly the fields §1 requires for its
   `kind` (an unknown `kind` is `LEDGER_MALFORMED`), and passes §2 step 1a. This runs on every
   line, including a replay, because an entry signed outside `append` reaches this point
   unchecked.
3. `by` equals `sha256:` + the digest of the public key embedded in `sig`, its first 16 hex
   equal the file name, and every entry in the file has the same `by`
   (`LEDGER_SIGNER_MISMATCH`).
4. That public key is in `allowed_signers` with the `biolean-ledger` namespace permitted
   (`LEDGER_UNKNOWN_SIGNER`).
5. `sig` is canonical base64 (§1) and verifies over the entry's canonical bytes without
   `sig` (`LEDGER_BAD_SIGNATURE`).
6. `prev` equals the previous entry's hash, `""` for the first (`LEDGER_CHAIN_BROKEN`, `field:
   "/prev"`, `got`: `prev` as written, `context.expected_prev`: the 64 hex or `""`). Two
   entries naming the same `prev` are a fork, and a fork is `LEDGER_CHAIN_BROKEN`: a file is
   one chain. The fix is operational, not cryptographic: delete the losing branch's lines
   from the file, then `append` their bodies again (new `prev`, new `ts`, new signature).
   Re-appending while the lines are still in the file would hit `LEDGER_DUPLICATE`.
7. For an `axiom` entry, the annotation id recomputed from `fact` equals
   `check.annotation_id` (`LEDGER_INVALID_ENTRY`). This needs no base, so plain `verify`
   runs it too. A `computed` entry in a file is `LEDGER_INVALID_ENTRY` in v1: `append` never
   writes one.

Every integrity error carries `file` (relative to the ledger dir) and `line` (1-based) in
`context`. Any integrity failure is exit 2 and nothing loads. Integrity is not a per-entry
counter: a ledger is either intact or it is not.

Removing a key from `allowed_signers` makes every entry in that key's file fail step 4.
Because any integrity failure stops the load, `verify`, `load_store`, `append` and every
`--ledger` command then exit 2 for the whole ledger until that file is deleted. v1
revocation is therefore one commit that removes the key's line and deletes its file. A pull
request that removes only the line fails the §6 verify CI. This is deliberate: the list is
the whole trust model, so a key's removal must be loud. Any one listed signer can likewise
make the ledger unloadable, by a fork or an invalid line; v1 accepts this, and the recovery
is an owner commit that removes the offending lines.

**What integrity does not prove.** Every chain starts at `prev: ""` and a file has no end
marker. So a prefix of a valid file is a valid file, a missing file is indistinguishable
from a key that has not appended yet, and any other chain the key ever signed (for example
the losing branch of a fork, before it was re-signed) also verifies. Integrity is per-file
consistency, not completeness or freshness.

`verify --extends <older ledger dir | heads.json>` adds that check. It fails with
`LEDGER_ROLLBACK` (exit 2), naming the file, the older entry count and head, and what is
there now, in any of these cases:

- (a) the older value is a directory and one of its `ledger/*.jsonl` files is not a byte
  prefix of the same file now;
- (b) the older value is a heads map and the current file has fewer than `entries` entries,
  or its entry number `entries` does not hash to `head`;
- (c) a file the older state has is missing now and its key is still in the current
  `allowed_signers`.

Deleting the file of a key that has been removed from `allowed_signers` is the one allowed
shrink, because step 4 would otherwise fail the whole ledger.

### Base binding, re-check and staleness

Every entry names the base it was checked against, but `append` is a client: a signature
proves who wrote an entry, never that §2 ran. Every load and every `verify --store`
therefore re-run §2 steps 1 to 7a on every `axiom` entry against the base being loaded,
cheaply and without the kernel, then compare its content key against the base only. At
load, step 7 requires column 15 to equal `biolean:` + the file's key16 (empty fails). A
failure is `LEDGER_INVALID_ENTRY`, an integrity failure (exit 2, carrying file, line and the
§2 code), in two cases: the loaded base's three digests equal the entry's `base`, so
`append` could not have written the entry; or the failing check does not depend on the
base (steps 1, 1a, 2, 6, 7, 7a and the reference half of step 5), whatever `base` says.
Otherwise an entry could dodge the check by naming a base that never existed. Any other
failure against a different base:

- passes: loads normally, counted `ledger.rechecked_ok`
- fails: excluded from the store, counted `ledger.stale`, and listed in the report as
  `{annotation_id, code}`. A term the new release obsoleted is the common case.
- its content key now equals a base row's (GOA caught up): excluded, counted
  `ledger.superseded_by_base`, listed in `superseded_entries` as `{annotation_id,
  base_annotation_id}`. Tested first; wins over `stale`. It uses step 8's key and nothing
  looser, so a base row that was present when the entry was admitted can never supersede
  it. Only identical parsed references match; v1 resolves nothing, so a GOA row citing the
  same paper by PMID where the ledger cites the DOI is not detected.

Step 8's ledger half is checked at append only. Two signers can append the same content at
the same time, in separate files. With no global order (§0.5), neither is the duplicate. On
every load both entries load, because their annotation ids differ in column 15, and each
group is counted `ledger.duplicate_content` as `{content_key, annotation_ids}`.

Nothing is dropped without a counter and an id. `check.contested_by`, `check.counters` and
`check.kernel` are the signer's record, and nothing reads them. The report's `contested`
counts, and `show --contested` lists, the admitted `axiom` entries whose fact's `Prop` has
non-empty kernel `conflicts` recomputed over the loaded store (base plus every admitted
ledger fact); `_conflicts` reads only the store, so a later counterpart contests an earlier
entry. `derived` entries are not re-proved on load; `verify --recheck` applies the §2
`derived` rule, including the conclusion comparison, and reports `ledger.derived_rechecked`
and `ledger.derived_failed` with the kernel's errors. §2 is code: a release that makes it
stricter turns entries it used to admit into `LEDGER_INVALID_ENTRY`. Such a change is a
breaking change for every ledger and ships with a migration.

### Load

```python
load_store(snapshot_dir, *, obo="go-basic.obo", gaf="goa_human.gaf.gz",
           eco="gaf-eco-mapping.txt", ledger_dir=None, expected_signers_sha256=None,
           cache_dir=None, use_cache=True) -> tuple[StaticFactStore, dict[str, dict[str, Any]]]
```

The keyword-only file names already exist and `cli.py` and the test fixture depend on them.
The `ledger` block is present only when `ledger_dir` is given. With a ledger: integrity,
then base binding, then each admitted `fact` is joined by tab and passed to `parse_gaf` as
its own element of a list, with the base's ECO map and ontology callables. Facts are never
concatenated into one text and split. Each must yield exactly one annotation whose id
equals `check.annotation_id`; anything else is `LEDGER_MALFORMED`, exit 2. The ledger rows'
`parse_gaf` report is returned as `report["ledger_gaf"]`, separate from the base's
`report["gaf"]`, so every existing counter applies to ledger rows too. Then the annotations
are appended to the base's before the store is built. `StaticFactStore` still raises on a
duplicate id. Column 15 separates ledger ids from base ids and one signer's from another's,
and the step 7a round trip refuses a repeated row within one file, so a raise there is a
defect. An integrity failure makes `load_store` raise `LedgerIntegrityError(errors)`;
`_biolean_store` and the `ledger` subcommands catch it, print `{"errors": [...]}` as JSON
on stdout and return 2 directly, not through `parser.error`, whose usage text would break
the JSON contract.

The load report gains one block:

```json
"ledger": {"files": 3, "entries": 412, "axioms": 400, "derived": 12, "computed": 0,
           "rechecked_ok": 0, "stale": 0, "stale_entries": [],
           "superseded_by_base": 0, "superseded_entries": [],
           "duplicate_content": 0, "contested": 7,
           "heads": {"<key16>": {"entries": 140, "head": "<entry hash>"}},
           "allowed_signers_sha256": "…", "files_verified_from_cache": 0}
```

`allowed_signers_sha256` is the sha256 of the file bytes, the value a consumer pins.
`contested` is recomputed (above), never read from `check`. A consumer that saves `heads`
can pass it as `heads.json` to `verify --extends` next time.

### Performance and the verification cache

Pure-Python ed25519 verification is a few milliseconds per entry. Target: 1,000 entries
verified in under 5 s on the local machine; the store load it precedes is about 13 s.
`load_store` consults a local cache unless `use_cache=False` (CLI `--no-cache`), in
`cache_dir` (CLI `--cache-dir`, default `~/.cache/biolean-ledger/` resolved at call time;
tests pass `tmp_path`, so no test touches the real home directory). The key is `(ledger id,
file name, sha256 of the file bytes, sha256 of allowed_signers, LEDGER_VERIFIER_VERSION)`;
the constant is bumped on any change to `ed25519.py`, the sshsig parser or §3. The file
name is in the key because step 3 is the only binding between a file's name and its
contents, so a byte-identical copy under another name must not hit. The cache records
"integrity steps 1 to 6 passed" per file and nothing else: the §2 re-run depends on the
base and on the code and is never cached. `ledger verify` never reads the cache, and ledger
CI always passes `--no-cache`. The cache is a local trust shortcut: any process that can
write it can make a forged file load on this machine. It is never inside the ledger
directory and never shared. The report carries `files_verified_from_cache: <int>`.

## §4 — Keys and signing

### Trusted list

`allowed_signers` is OpenSSH's format, one line per key:

```
manu@example.org namespaces="biolean-ledger" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI… comment
```

Blank lines and lines whose first non-blank character is `#` are skipped. Principals are
one token, or a double-quoted token, as OpenSSH parses them; they are labels for humans and
`ledger show`, and trust is the key. Options are matched case-insensitively, as in OpenSSH.
`namespaces` may appear at most once, and its quoted value is a comma-separated list of
literal names: any `*`, `?` or `!` in it is `LEDGER_MALFORMED`, because OpenSSH treats them
as patterns (`!` negates, so a naive `in value.split(",")` would permit
`namespaces="biolean-ledger,!biolean-ledger"`, which OpenSSH denies) and v1 does not
implement patterns. Any other option (`cert-authority`, `valid-after`, `valid-before`), or a
key type other than exactly `ssh-ed25519`, is `LEDGER_MALFORMED` naming it. Refusing is the
point: an option the verifier does not implement must not be silently unenforced. The same
key on two lines is `LEDGER_MALFORMED`. A key with no `namespaces` option is permitted for
every namespace, as OpenSSH does. A key whose point A satisfies [8]A = identity (the eight
small-order encodings, including `0x01` followed by 31 zero bytes) is `LEDGER_MALFORMED` at
parse, naming the line: cofactorless verification accepts one fixed signature (R =
identity, S = 0) for every message under such a key, and OpenSSH accepts it too.

### Signing

`append` reads the signer's public key before signing, because `by`, column 15 and the
annotation id are inside the signed bytes: from `--key` itself when it is a `.pub` file,
otherwise from `<key>.pub` beside it. If neither exists, or the key type is not exactly
`ssh-ed25519` (this refuses `sk-ssh-ed25519@openssh.com` and `*-cert-v01@openssh.com`), the
result is `LEDGER_UNSUPPORTED_KEY`, exit 2, before anything is signed. It never runs
`ssh-keygen -y`.

`append` then shells out once, through the injectable `runner` seam `fetch.py` uses
(`runner=subprocess.run`):

```python
runner(["ssh-keygen", "-Y", "sign", "-f", key, "-n", "biolean-ledger"],
       input=canonical_bytes, capture_output=True, check=True)
```

The message goes on stdin, so the armored signature comes back on `stdout`, as bytes (no
`text=True`). Given a file argument, ssh-keygen would write `<file>.sig`, print no signature,
and prompt when that file exists; signatures go to standard output only when the message
was read from standard input. No temp file is used. `key` is an unencrypted private key
file, or a public key file whose private half is loaded in `ssh-agent`. The agent is the
only way to use a passphrase-protected key: because stdin carries the message, ssh-keygen
given an encrypted key file reads the passphrase from stdin, uses the entry as the
passphrase, and exits 255 with `incorrect passphrase`. The armor (`-----BEGIN SSH
SIGNATURE-----` … `-----END SSH SIGNATURE-----`) is stripped and the base64 lines are
concatenated with no whitespace; that string is `sig` (§1). `append` then runs the in-repo
verifier on the entry it just built before writing it, so a signing misconfiguration
surfaces at append, not at load. A `runner` failure or a failed self-verify is
`LEDGER_SIGNING_FAILED`, exit 2, nothing is written, and the message names the agent route.
`append` takes `ts` from its caller (§1).

### Verification, in-repo

The `sig` body decodes to the `sshsig` blob (OpenSSH `PROTOCOL.sshsig`):

```
byte[6]  "SSHSIG"     uint32 version = 1     string publickey
string   namespace    string reserved        string hash_algorithm     string signature
```

The verifier requires `version == 1`, `namespace == "biolean-ledger"`, `hash_algorithm ==
"sha512"` (ssh-keygen's default; allowing both algorithms would let the key holder produce
two valid `sig` values for one entry), `reserved` empty, `publickey` of type `ssh-ed25519`
with a 32-byte key, `signature` of type `ssh-ed25519` with a 64-byte value, and no bytes
after `signature` in the blob or inside the signature string. It then builds the signed
data

```
byte[6] "SSHSIG"  string namespace  string reserved  string hash_algorithm  string H(message)
```

with `H` sha512 over the entry's canonical bytes, and checks it with Ed25519 verification
as RFC 8032 §5.1.7 (`[S]B = R + [k]A`, cofactorless), implemented over the stdlib in
`biolean/ed25519.py`: field arithmetic mod `2^255 − 19`, point decoding with the RFC's
rejection of non-canonical encodings, `S < L`, `hashlib.sha512`. Verify-only. There is no
signing code in the repo. The in-repo verifier is deliberately stricter than OpenSSH, which
accepts `S + L`. To cross-check an entry with `ssh-keygen -Y verify`, re-armor `sig` wrapped
at 70 columns.

The module is pinned by the RFC 8032 §7.1 test vectors (all Ed25519 vectors), by mutated
vectors that must fail, and by fixture signatures produced once with a real `ssh-keygen`
and checked in under `tests/fixtures/biolean/ledger/`, with their public keys. Passing
those tests is necessary but not sufficient. The vectors do not exercise every path (see
Risks), so any change to the module also needs review against RFC 8032 §5.1.3 and §5.1.7.

## §5 — Phase B reservation: the `computed` kind

Specified now so that Dogma's sidecar can produce it and so that no early entry becomes
legacy when `discharge` lands.

```json
{"v": 1, "kind": "computed", "ledger": "…",
 "method": "m:deseq2",
 "dataset": {"id": "GEO:GSE12345", "sha256": "<digest of the input manifest>"},
 "graph_hash": "sha256:<64 hex from methods.lock.json>",
 "preconditions": [{"id": "replicates>=3", "status": "met", "diagnostic": "n=4 per group"},
                   {"id": "count_data", "status": "met", "diagnostic": "integer matrix"}],
 "run": {"command": "nextflow run nf-core/differentialabundance -r 1.5.0 …",
         "container": "quay.io/biocontainers/…@sha256:…", "exit_code": 0},
 "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in",
                "term": "GO:0006915", "taxon": "NCBITaxon:9606", "negated": false},
 "base": {…}, "check": {…}, "prev": "…", "by": "…", "ts": "…", "sig": "…"}
```

Schema check in v1: `method` is `m:` followed by a non-empty string that equals its own
lowercase form, with no leading or trailing whitespace and no control characters. Method
ids are `m:` + the lowercased method name, and some real ones contain spaces (for example
`m:bcftools plugin fill-tags`), so a `[a-z0-9_.+-]+` pattern would reject real ids.
`dataset.id` and `dataset.sha256` are non-empty strings. `graph_hash` matches
`^sha256:[0-9a-f]{64}$`, the form `methods.lock.json` records. `preconditions` is a
non-empty list of `{id, status ∈ {met, unmet, unknown}, diagnostic}`. `run.command` and
`run.container` are non-empty, and `run.exit_code` is a JSON integer, not a boolean. A
failure in any of these fields is `LEDGER_BAD_COMPUTED` (exit 3, one error per failing
pointer, e.g. `field: "/run/exit_code"`, `fix: null`). `conclusion` must be a valid `Prop`:
the kernel's own term, qualifier and taxon checks run and are re-emitted in the §7 shape
with the §2 step 3 and 4 codes. Then `NOT_YET_DISCHARGEABLE`.

When Phase B arrives, `discharge` turns this into a `computed` rule application: every
precondition `met` against `method_preconditions(method)` at `graph_hash`, or a typed
refusal. Only then does a `computed` entry contribute a fact, and it does so with evidence
code `RCA` or a code the owner chooses then, which is why the evidence class stays a type.

## §6 — Where the data lives

Code and format: `methods_graph.biolean` in this repo. Entries: a separate, small git repo,
`biolean-ledger`, cloned outside this repo or at `/biolean-ledger/`, which the plan adds to
`.gitignore` next to `/biolean-bench/` (today a clone at the root would be recorded as a
gitlink by `git add -A`), and named with `--ledger`. Its `.gitattributes` holds `*.jsonl
-text`, so autocrlf never rewrites a line. It is kept out of the code repo for the same
reason `snapshots/` is: data, not code, on its own cadence.

```
biolean-ledger/
  README.md            # what this is, how to contribute, the base to fetch
  .gitattributes       # *.jsonl -text
  allowed_signers
  base.json            # {"obo": …, "gaf": …, "eco": …, "release": {…}}, the §1 base object
  ledger.json          # {"ledger": "<32 hex>"}
  ledger/
    3f2a9c1e8b7d6054.jsonl
    a91e….jsonl
```

`base.json` is the ledger's declared base, the §1 `base` object. It is read only by `init`,
which writes it from the snapshot directory it is given, and by `append`, which refuses to
write an entry whose `base` differs from it (`LEDGER_BASE_MISMATCH`, exit 2), so a ledger is
checked against one base at a time. `verify`, `show` and `load_store` never read it; they
compute the three digests from the files under `--store`. Changing the base is an
owner-approved edit to `base.json` followed by `verify --store <new snapshot dir>`, which
then reports what went stale.

`allowed_signers`, `base.json` and `ledger.json` are unsigned. In `biolean-ledger` they
change only in commits the owner approves. That approval is a git-host control, and
`verify` cannot tell an owner-approved key from one added by anyone with push access. Keys
are added in the owner's own commits.

Contributor flow: clone, `append` locally, push, open a PR. The PR CI runs

```
mg biolean ledger verify --ledger . --store <snapshot dir> \
  --signers-sha256 <target branch's allowed_signers digest> \
  --recheck --extends <checkout of the merge base> --no-cache
```

Nobody can add a valid entry to another key's file. `--extends` refuses a PR that
truncates, deletes or rolls back one. The pin fails a contributor PR that edits the list.
Changes to `allowed_signers`, `base.json`, `ledger.json` and anything outside
`ledger/*.jsonl` need owner review (a CODEOWNERS or branch-protection rule, or the
equivalent on the chosen host). Without that rule, a PR could remove a key and delete its
file together and still pass `--extends`.

**Dependency:** that CI needs the exact base pair on a runner, and today the pair cannot be
re-fetched (decision O-02, release skew). A federated ledger therefore needs O-02 settled or
the base files published alongside the ledger. This spec does not decide it; it records
that the first outside contributor forces it.

## §7 — CLI

```
mg biolean ledger init    --ledger <dir> --store <snapshot dir> --key <pubkey file> [--principal NAME]
mg biolean ledger append  --ledger <dir> --store <snapshot dir> --key <key file> (--fact <json> | --derivation <json> | --computed <json>)
mg biolean ledger verify  --ledger <dir> [--store <snapshot dir>] [--recheck] [--no-cache] [--cache-dir DIR] [--extends <dir|heads.json>] [--signers-sha256 HEX]
mg biolean ledger show    --ledger <dir> [--store <snapshot dir>] [--by KEY16] [--kind axiom|derived|computed] [--contested] [--stale] [--signers-sha256 HEX]
mg biolean prove  "<claim>" --ledger <dir> [--signers-sha256 HEX] …
mg biolean check  <derivation.json> --ledger <dir> [--signers-sha256 HEX] …
mg biolean goals  <subject> --ledger <dir> [--signers-sha256 HEX] …
```

Ledger subcommands take `--store`, as every `mg biolean` subcommand does; `--base` is not a
flag, and `base` names only the entry field and `base.json`. `ledger` is a nested subparser
(`bl_sub.add_parser("ledger")`, `dest="ledger_cmd"`) dispatched before `_biolean_store`, as
`bench` is. `init` and `append` default `--store` to `snapshots/go`; `verify` and `show`
default it to None, where None means integrity only. `verify --recheck`, `show
--contested` and `show --stale` without `--store` are usage errors (exit 2).

- `init` writes `allowed_signers` with the given key, `base.json`, `ledger.json`, and creates
  `ledger/`. It refuses a key whose type is not `ssh-ed25519` (`LEDGER_UNSUPPORTED_KEY`) and
  a `ledger/<key16>.jsonl` that exists with a different `by` (`LEDGER_KEY16_COLLISION`,
  exit 2).
- `append` reads one entry body (`--fact` is the 17-column list, or an object with exactly
  the 17 keys below, converted to the list before any check), builds the envelope, checks,
  signs, self-verifies, writes, and prints `{"verdict": "ACCEPTED", "entry": <entry>,
  "hash": <64 hex>, "file": "ledger/<key16>.jsonl", "line": <n>}`. On rejection it prints
  `{"verdict": "REJECTED", "errors": [...], "deferred": [...]}` and writes nothing.
  `deferred` is `[]` for `derived` and `computed`.
- `verify` without `--store` checks integrity only. With `--store` it also re-runs §2 and
  reports staleness. `--extends` fails with `LEDGER_ROLLBACK`, exit 2, as §3 defines.
- `show` prints entries as JSON lines, filtered; `--contested` and `--stale` need `--store`.
  Each `derived` entry is printed with `"rechecked": false` beside the signed object, never
  inside it, unless `--recheck` ran.
- `prove`, `check` and `goals` accept `--ledger`; the store is base plus admitted ledger
  facts, and a derivation's `axiom` steps may cite them. The kernel's `axioms` entries carry
  `{step, annotation, code, eco, references}` and no `assigned_by`, so a ledger-sourced
  axiom is one whose annotation id's row in the store has `assigned_by` starting with
  `biolean:`; the kernel's `axioms` list is unchanged. `prove --ledger` post-processes in
  `cmd_biolean`, not in `tactics.prove`. When every row `store.matching(s1.conclusion)`
  returns is ledger-sourced, it sets s1's `reference` to the smallest `DOI:` value, else
  `PMID:`, else `GO_REF:`, taken from the row with the smallest annotation id (references
  are stored sorted). When any base row also matches, it leaves `reference` unset, because
  the kernel's reference filter would drop the base rows from `axioms`.
- `bench` never takes `--ledger`. Items and scores are over the frozen base only.

### Rejection payload

Every ledger error object is `{"code", "message", "field", "got", "fix", "options",
"context"}`, always all seven keys. This is not the kernel's six-key shape, and no kernel
`Error` is ever passed through.

- `field` is an RFC 6901 JSON Pointer into the entry `append` builds, counting from 0,
  after an object-form `--fact` has been converted to the 17-list, or `null` when nothing
  in the body is addressed (`NOT_YET_DISCHARGEABLE`). GAF column N is `/fact/<N-1>`: column
  4 (qualifier) is `/fact/3`, column 5 (GO ID) is `/fact/4`, column 9 (aspect) is `/fact/8`.
  Whole-row errors use `/fact`; `/v`, `/kind`, `/base`, `/conclusion`, `/derivation`,
  `/derivation/steps/<i>` and the §5 key paths (`/preconditions/0/status`) name those
  fields. Each error has exactly one pointer, so a bad column 1 and a bad column 2 are two
  `LEDGER_BAD_SUBJECT` errors. An elaboration-report `path` p appears as `/derivation/` + p.
- `got` is the whole value at `field` as submitted, or `null` if absent. For column 4 that
  includes any `NOT|` prefix; for column 13 both values.
- `fix` is `null`, or exactly one JSON value that clears this error when written at `field`
  (an RFC 6901 replace). It is a whole value for `field`, never a set of alternatives and
  never a template. For a negated row it keeps the `NOT|` prefix.
- `options` lists complete candidate values for `field`, each of which clears this error
  when written there. Sorted, no duplicates, `[]` when there are none. Term ids are live
  primary ids only. Qualifiers carry `NOT|` exactly when `got` does. The order is not a
  preference; choosing is the caller's judgment. Aspect and qualifier fixes move toward the
  term, never the reverse.
- `context` is `null` or an object that must never be substituted: `{"columns": [...]}`,
  `{"existing": [...]}`, `{"form": "taxon:<digits>"}`, `{"kernel": {...}}`, `{"file",
  "line", "expected_prev"}`. It is deliberately not named `expected`: the kernel's
  `expected` is often the value to substitute.
- Terminal codes, which no change to the body can clear, so a loop must stop on them:
  `NOT_YET_DISCHARGEABLE`, `LEDGER_DUPLICATE`, `LEDGER_BASE_MISMATCH`. Integrity errors
  (exit 2) are outside the retry contract and carry `file` and `line` in `context`.
- Output: a rejection prints `{"verdict": "REJECTED", "errors": [...], "deferred": [...]}`;
  an acceptance prints `{"verdict": "ACCEPTED", "entry": ..., "hash": ..., "file": ...,
  "line": ...}`.
- Exit codes: 0 accepted; 3 rejected (the body is wrong and fixable); 2 usage error
  (argparse, text on stderr), unreadable store or ledger, integrity failure, base mismatch,
  signers mismatch, rollback, or signing failure (JSON on stdout). Exit 2 never means the
  body is wrong.

This is the contract a small model iterates against: write `fix` at `field` when it is
non-null, otherwise pick from `options`, then retry; stop on a terminal code.

The object form of `--fact` has exactly these 17 keys, in column order, so the key at
position i is `/fact/i`: `db`, `db_object_id`, `db_object_symbol`, `qualifier`, `go_id`,
`db_reference`, `evidence_code`, `with_from`, `aspect`, `db_object_name`,
`db_object_synonym`, `db_object_type`, `taxon`, `date`, `assigned_by`,
`annotation_extension`, `gene_product_form_id`. A missing key is `""`; any other key is
`LEDGER_BAD_COLUMNS` naming it.

Normative table, which §9 enumerates:

| `fix` | codes |
|---|---|
| a value | `LEDGER_ALT_ID` (the live primary, or its replacement); `OBSOLETE_TERM` with exactly one live `replaced_by`; `LEDGER_ASPECT_MISMATCH` (the term's aspect letter); `LEDGER_ASSIGNED_BY` (`biolean:<key16>`); `LEDGER_CONCLUSION_MISMATCH` (the elaborated goal); `LEDGER_VERSION` (`1`); `LEDGER_BAD_TAXON` when every value normalizes; `LEDGER_BAD_DATE` when `got` is an unambiguous ISO date; `LEDGER_BAD_CHARACTER` (the cleaned value); `LEDGER_BAD_OBJECT_TYPE` when the subject is known |
| `null` with `options` | `UNKNOWN_QUALIFIER` and `QUALIFIER_ASPECT_MISMATCH` (the qualifiers legal for the term's aspect); `OBSOLETE_TERM` with several live `replaced_by`, or with only live `consider`; `LEDGER_ALT_ID` whose obsolete primary has only those; `LEDGER_ECO_UNMAPPED` (the mapped codes) |
| `null`, `options: []` | `UNKNOWN_TERM`; `OBSOLETE_TERM` with no live `replaced_by` or `consider`; `LEDGER_BAD_SUBJECT`; `LEDGER_BAD_REFERENCE`; `LEDGER_REFERENCE_REQUIRED`; `LEDGER_BAD_TAXON` and `LEDGER_BAD_DATE` otherwise (`context.form`); `LEDGER_BAD_OBJECT_TYPE` otherwise; `LEDGER_BAD_COLUMNS` (`context.columns`); `LEDGER_BAD_KIND`; `LEDGER_BAD_BODY`; `LEDGER_DUPLICATE` (`context.existing`); `LEDGER_BASE_MISMATCH` (`context`: `base.json`'s digests); `LEDGER_DERIVATION_REJECTED` (`context.kernel`); `LEDGER_SORRY_USED`; `LEDGER_SORRY_UNUSED`; `NOT_YET_DISCHARGEABLE`; `LEDGER_BAD_COMPUTED`; every §3 integrity code |

## §8 — Seams for what comes next

- **Cost gate.** `append` gains a policy hook, `admit(entry) -> Admission`, that runs after
  the check and before signing. v1 ships one policy, `allowed_signers`. A stake, a fee, or a
  proof of work is another policy. The entry format does not change; a policy may fill the
  reserved top-level `admission` object, which the hash and signature then cover.
- **Dogma.** Reads `show` output and the load report's `ledger` block to render contested
  and stale state; produces `computed` bodies from its edge evaluation plan and guardrail
  output. Its evidence ledger stays factual and local; a Biolean entry is what one of its
  records becomes after the kernel accepts it.
- **Phase B.** §5. `discharge` is the only new kernel rule.
- **Resolution.** A later `append --resolve` may fetch the DOI or PMID and record the
  title and journal under the reserved `check.reference_resolved`. Off by default; the repo
  forbids network in the checker.
- **Other organisms.** The base is any GAF; `init` records whatever pair it is given, and
  the `ledger` id keeps one organism's chains out of another's ledger.

## §9 — Tests

Under the repo's mutation rule: each test names the break it catches, and the break was
applied to the implementation and made the test fail before the test was accepted.

**Fixtures**, all small, under `tests/fixtures/biolean/ledger/`: a ledger ontology (not
`go-mini.obo`, whose term and obsolete counts `tests/test_biolean_obo.py` pins) across two
namespaces, one of them molecular_function, with a live term carrying an `alt_id`; an
obsolete term with one same-namespace `replaced_by` that also carries an `alt_id`; an
obsolete term whose single `replaced_by` is in the other namespace; an obsolete term with
two `consider` terms in its own namespace; and an obsolete term with neither. A ten-row GAF
with one `NOT` row and one pair of rows differing only in column 15 (`UniProt`, `MGI`); an
ECO mapping of four codes. Two ed25519 test keypairs, A and B, kept under `keys/` and
trusted by nothing outside these fixtures; `init` refuses their digests. Four `ssh-keygen
-Y sign` signatures (over a known message, over a second message, in the wrong namespace,
with key B). A pre-signed ledger `signed/` (an `allowed_signers` listing A and B,
`base.json` and `ledger.json` for the fixture base, three chained `axiom` entries by A, one
`axiom` entry by B, one `derived` entry by A); a fork file (A's three entries plus a fourth,
on line 4, whose `prev` is entry 1's hash); a hand-signed line whose column 15 names B's
key16, one with a made-up `base`, one with `\ud800` in column 17, and one whose `sig`
carries S+L of a real signature; and one armored signature over the exact canonical bytes
of each entry a test expects `append` to write. Plus the RFC 8032 §7.1 vectors as data.
`make_fixtures.py` makes all of them by driving the real `append` with the real `runner`
and a fixed `ts`. The suite never runs it, and its name is not `test_*`. Ed25519 and sshsig
signing carry no randomness, so re-running it on unchanged inputs gives byte-identical
fixtures. After any change to the envelope, the kernel version or the fixture base, the
fix is to re-run it and commit the result. Integrity and load tests mutate copies of
`signed/` and never need a new signature.

**`ed25519.py`**
- `test_rfc8032_vectors_verify`: every §7.1 Ed25519 vector verifies.
- `test_rfc8032_vector_with_one_bit_flipped_fails`: flip one bit of each signature, all fail.
- `test_non_canonical_s_rejected`: `S + L` fails even though it is the same scalar mod `L`.
- `test_non_canonical_point_rejected`: a public key or `R` whose low 255 bits encode y >= p
  (for example p + 1) fails, and the encoding of y = 1 with bit 255 set (x = 0, x_0 = 1)
  fails. Bit 255 is the sign of x (RFC 8032 §5.1.3), not an unused bit; setting it on a
  valid encoding gives a different valid point.

**sshsig**
- `test_real_ssh_keygen_signature_verifies`: fixture signature over the fixture message passes.
- `test_wrong_namespace_fails`, `test_wrong_message_fails`.
- `test_second_key_signature_is_signer_mismatch_or_unknown`: key B's real signature on an
  entry whose `by` names A is `LEDGER_SIGNER_MISMATCH`; with `by` naming B and B absent from
  `allowed_signers` it is `LEDGER_UNKNOWN_SIGNER`. A real signature by another key verifies
  cryptographically against the key it embeds, so no other failure is possible.
- `test_sshsig_fields_are_enforced`: version 2, a non-ed25519 key, a 63-byte signature,
  `hash_algorithm` `sha256`, a non-empty `reserved`, trailing bytes, and a `sig` that still
  contains armor or whitespace are each `LEDGER_BAD_SIGNATURE` with the reason.
- `test_small_order_keys_refused_in_allowed_signers`: all eight encodings; plus a fixture
  showing that the identity key with R = identity, S = 0 would otherwise verify two
  different messages.
- `test_negated_namespace_is_refused_not_permitted`,
  `test_signer_without_namespaces_option_is_allowed`,
  `test_signer_with_other_namespace_is_unknown`,
  `test_unsupported_key_type_refused_before_signing`.

**Integrity**
- `test_one_byte_change_in_a_signed_entry_fails`: any single byte of any field, `sig`
  included (a padding-bit change in `sig` is `LEDGER_BAD_SIGNATURE` through the canonical
  base64 rule).
- `test_reordered_keys_are_malformed`: same JSON, different key order, `LEDGER_MALFORMED`.
- `test_missing_middle_entry_breaks_chain`: delete line 2 of 3.
- `test_fork_is_a_chain_break`: two entries with the same `prev`.
- `test_unlisted_key_is_unknown_signer`, `test_by_must_match_embedded_key_and_filename`,
  `test_all_entries_in_a_file_share_by`.
- `test_unsupported_allowed_signers_option_refuses_to_load`: `valid-before` present.
- `test_removed_key_fails_whole_ledger_until_its_file_is_deleted`: two contributor files.
  Removing one key gives exit 2 with `LEDGER_UNKNOWN_SIGNER`, and none of the other file's
  facts load. Deleting the removed key's file makes the other file load. Catches an
  implementation that skips the unlisted file and loads the rest.
- `test_signers_pin_mismatch_fails_before_any_entry_is_read`: an added key plus a validly
  signed file passes unpinned and fails pinned. Mutation: skip the pin check, or run it
  after the entries are read.
- `test_truncated_tail_passes_integrity_and_fails_extends`: drop the last line of 3. Plain
  `verify` passes; `--extends` against the 3-line directory and against its heads map both
  fail.
- `test_deleted_file_fails_extends`: the key is still listed.
- `test_revoked_key_file_deletion_passes_extends`: the key and its file are both removed.
- `test_divergent_chain_substituted_fails_extends`: same key and at least as many entries
  as the older head, but a different entry at that position. Catches a count-only check.
- `test_signed_entry_with_bad_character_fails_integrity_not_crash`: the `\ud800` fixture
  line gives `LEDGER_MALFORMED` and exit 2, no exception; removing the load-side check raises
  `UnicodeEncodeError`.
- `test_check_annotation_id_recomputed`: a signed entry whose `check.annotation_id` does not
  match `fact` is `LEDGER_INVALID_ENTRY` from plain `verify`.
- `test_chain_from_another_ledger_is_wrong_ledger`, `test_key16_collision_refused`,
  `test_version_true_or_float_is_ledger_version`,
  `test_cache_hit_does_not_cover_a_renamed_copy`.

**Append check**
- `test_obsolete_term_rejected_with_replaced_by_fix`, `test_alt_id_rejected_with_primary_fix`,
  `test_alt_id_with_obsolete_primary_fixes_to_the_replacement` (break: `fix` is the obsolete
  primary), `test_obsolete_without_single_replaced_by_uses_consider_options`,
  `test_unknown_term_rejected`.
- `test_qualifier_illegal_for_aspect_rejected_with_legal_options`,
  `test_aspect_must_match_term_namespace`,
  `test_unknown_qualifier_options_match_aspect_and_keep_not` (break: offer all 13, or strip
  `NOT|`).
- `test_qualifier_fix_preserves_not`: two rejected rows, `NOT|involved in`
  (`UNKNOWN_QUALIFIER`) and `NOT|enables` on the fixture's process term
  (`QUALIFIER_ASPECT_MISMATCH`). Every option starts with `NOT|`. Substituting any one gives
  a row that is admitted and parses to `negated == True`. Mutation: emit the kernel's bare
  `expected` list.
- `test_reference_must_carry_doi_pmid_or_go_ref`, `test_bad_reference_syntax_rejected`,
  `test_unmapped_evidence_code_rejected`, `test_bad_subject_rejected_and_new_subject_counted`,
  `test_bad_columns_rejected_with_column_names_in_context`,
  `test_bad_taxon_date_and_empty_object_type_rejected`,
  `test_bad_taxon_spelling_gets_rewritten_fix`.
- `test_lone_surrogate_is_bad_character_not_a_crash`,
  `test_trailing_cr_in_column_17_rejected` (asserts `LEDGER_BAD_CHARACTER`, not only
  rejection), `test_empty_columns_15_16_17_pass_character_check` (the §1 example fact is
  admitted).
- `test_base_row_resubmitted_with_own_assigned_by_is_duplicate`: a fixture base row
  (assigned_by `UniProt`) resubmitted with a new date, empty columns 10 and 11, reordered
  references, `NCBITaxon:` corrected to `taxon:` and the signer's column 15 is
  `LEDGER_DUPLICATE` with both base ids in `context.existing`. Mutations: compare annotation
  ids; use a raw-column key. Each must fail.
- `test_duplicate_of_ledger_row_rejected`: the existing row is in a second signer's file.
  With one signer the test passes against the bug.
- `test_same_prop_different_reference_is_a_new_row`: admitted, distinct id.
- `test_positive_fact_against_base_not_row_is_admitted_and_contested`: the fixture GAF's
  NOT row sits at (s, q, t). Appending the positive row at (s, q, t) is admitted with
  `check.contested_by == [<NOT row id>]`, and `check()` of `prove`'s derivation for (s, q, t)
  lists that id under `conflicts`.
- `test_assigned_by_empty_is_filled_and_wrong_value_rejected`,
  `test_base_mismatch_refuses_append`,
  `test_append_self_verify_refuses_and_writes_nothing` (the fake runner returns the
  known-message signature).
- `test_independent_faults_reported_in_one_response`: faults in steps 2, 5 and 6 all appear
  in one response. Break: stop at the first failing step.
- `test_cross_namespace_replacement_reports_aspect_errors_together`: one response carries
  `OBSOLETE_TERM`, `LEDGER_ASPECT_MISMATCH` and `QUALIFIER_ASPECT_MISMATCH`. After every
  non-null `fix` is applied, only `QUALIFIER_ASPECT_MISMATCH` remains, and any one of its
  options gives ACCEPTED. Break: evaluate step 4 against the submitted term.
- `test_fix_that_creates_duplicate_is_reported_first_try`. Break: run step 8 on the
  unfixed row.
- `test_derived_with_used_sorry_refused` and `test_derived_with_unused_sorry_refused`: the
  kernel verdict is ACCEPTED with `errors: []`, and the ledger still returns
  `LEDGER_SORRY_USED` / `LEDGER_SORRY_UNUSED` with a step pointer.
  `test_derived_conclusion_must_equal_goal`: `fix` is the elaborated goal.
  `test_derived_stores_elaborated_derivation`: a derivation with a symbol and a `taxon:`
  spelling is admitted, and the stored `derivation` is canonical.
- `test_computed_schema_checked_then_refused`: `graph_hash` without the `sha256:` prefix, an
  uppercase `method`, and `run.exit_code: true` each get `LEDGER_BAD_COMPUTED` first. A valid
  body, using the lock's `sha256:<64 hex>` form and `method` `m:bcftools plugin fill-tags`,
  gets `NOT_YET_DISCHARGEABLE`.
- `test_rejection_shape_is_ledger_not_kernel`: every append rejection, including those from
  the reused kernel checks, `derived` and `computed`, has exactly the §7 key set and no list
  in `fix`. Break: pass a kernel `Error.to_dict()` through.
- `test_rejection_fix_is_substitutable`: every code in the §7 table is triggered by a
  fixture row that triggers only that code and matches no base row, and its `fix`/`options`
  have the table's category. For a value `fix`, an RFC 6901 replace at `field` followed by a
  re-check gives ACCEPTED, and the accepted row's `negated` equals the submitted row's. For
  `options`, each option in turn does the same. Codes in the `null` rows return `fix: null`.
  It must fail under: `LEDGER_BAD_COLUMNS` returning the names as `fix`; a column 4 option
  without `NOT|` (caught by the `negated` assertion, not by ACCEPTED); `UNKNOWN_QUALIFIER`
  returning all 13 for an F term; a non-live id in `OBSOLETE_TERM` options. This is the
  north-star test.

**Load**
- `test_ledger_facts_enter_store_through_parse_gaf`: a ledger row's counters show in
  `report["ledger_gaf"]`; its annotation id is the GAF id.
- `test_prove_cites_ledger_fact_and_carries_doi`.
- `test_different_base_recheck_counts_stale_and_lists_ids`: a tmp copy of the ledger
  ontology with the term obsoleted.
- `test_superseded_by_base_is_excluded_and_counted`: the new base gains the entry's content
  under `assigned_by = UniProt`, a different date and filled names; the test asserts
  `superseded_entries`. No synthetic `biolean:` base row. Mutation: compare annotation ids.
- `test_base_row_differing_only_in_reference_never_supersedes`: an entry admitted beside a
  base row with the same Prop and code but a different reference still loads after a base
  change. Fails against any superseded key looser than step 8's.
- `test_same_fact_from_two_signers_loads_both_and_is_counted`: `duplicate_content` names
  both ids.
- `test_hand_signed_entry_skipping_append_is_invalid_on_matching_base`: column 15 names
  another key16. Break: skip the re-run when the digests match.
- `test_forged_base_does_not_downgrade_invalid_to_stale`: the same fact with a made-up
  `base`. Break: send every failure on a non-matching base to `stale`.
- `test_line_separator_in_column_cannot_inject_a_row`: calls the loader's fact-feeding
  helper directly with U+2028 in column 17, since integrity would otherwise hide the
  mutation. Exactly one annotation per fact, and every `assigned_by` is `biolean:<key16>`.
- `test_load_report_contested_is_recomputed`: an earlier entry's `check.contested_by` is
  `[]`, a later NOT entry lands, and `contested` counts both.
- `test_same_base_recheck_counts_ok`, `test_verify_recheck_counts_derived`,
  `test_verify_from_cache_is_reported_and_bypassable` (with `cache_dir=tmp_path`),
  `test_cache_path_outside_ledger_dir`, `test_bench_has_no_ledger_flag`,
  `test_show_filters_and_store_requirement`,
  `test_init_writes_allowed_signers_base_json_ledger_json_and_ledger_dir`.

**No subprocess.** Signing in tests goes through a fake `runner`. It asserts that its argv
is exactly `["ssh-keygen", "-Y", "sign", "-f", <key>, "-n", "biolean-ledger"]` (no file
argument) and that `input` is the entry's canonical bytes. It returns, on `stdout`, armor
that real `ssh-keygen` made once over exactly those bytes. `append` self-verifies, so armor
over any other message must fail. The entries these tests append are therefore
byte-deterministic (injected `ts`), and their signatures are fixtures. Mutation check: pass
the bytes as a file argument and the fake's argv assertion fails. Verification runs
in-process on real signatures. No test spawns `ssh-keygen`.

## Risks

- **Crypto in the repo.** Mitigated by verify-only scope, RFC vectors, real-signature
  fixtures, small-order key refusal, and a mutation test per property. Not mitigated: an
  implementation error the vectors do not exercise. Any change to `ed25519.py` needs review
  against RFC 8032 §5.1.3 and §5.1.7. If a maintained ed25519 dependency ever becomes
  acceptable, the module is replaced behind the same function.
- **The base cannot be re-fetched** (O-02). Local use is unaffected. Federated CI is
  blocked until the pair is reproducible or published with the ledger.
- **Contested facts and exit 0.** A derivation citing a contested ledger fact is ACCEPTED
  with `conflicts` non-empty, exactly as today (K1, decision O-08). The ledger makes that
  more visible, not worse. Consumers that gate on exit 0 alone are wrong today and remain so.
- **A weak model in a loop** can append many syntactically valid, biologically empty rows
  with real DOIs that do not support them. v1's answer is provenance and the trusted list:
  every row names who signed it. Resolution and a cost gate are the later answers.
- **`key16` collision.** A 64-bit prefix is expensive but not impossible to grind for a
  targeted victim. `init` and `append` refuse it (`LEDGER_KEY16_COLLISION`, exit 2, when
  `ledger/<key16>.jsonl` exists with a different `by`), `verify` refuses two listed keys
  sharing a key16 and a file whose entries do not all share one `by` (§3 steps 1 and 3), and
  the full digest in `by` disambiguates. `verify` enforces it, not only `init`.
- **One signer can halt the ledger** with a fork or an invalid line, and revocation halts
  it until the file is deleted. Accepted for a permissioned v1; recovery is one owner commit.
- **Chain forks from one key on two machines** are an integrity failure by design. The
  README of the ledger repo must say "one machine per key, or pull before you append".
- **The trusted list is unsigned.** Its integrity is the git host's review controls plus
  the consumer's `--signers-sha256` pin. A consumer that neither pins nor trusts the host's
  history has no guarantee about who is on the list.
