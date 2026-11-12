# Biolean ledger

**What this is:** the ledger as built: an append-only set of signed, hash-chained JSONL
records, each checked by the kernel before it is written, that extends the frozen GO/GOA
release with facts from literature. The design is
[`docs/superpowers/specs/2026-09-25-biolean-ledger-design.md`](../superpowers/specs/2026-09-25-biolean-ledger-design.md);
the plan is [`docs/superpowers/plans/2026-09-25-biolean-ledger.md`](../superpowers/plans/2026-09-25-biolean-ledger.md).
The kernel itself is described in [README.md](README.md).
**Status:** implemented per the plan; see the plan banner for the commit.
**Read next:** the spec's §0 (what the owner fixed) and §7 (the CLI contract).

## 1. What a ledger is

```
<ledger>/
  allowed_signers          # OpenSSH allowed-signers: the trusted list (unsigned; git is its trust root)
  base.json                # the base every entry is checked against: three content digests + release
  ledger.json              # {"ledger": "<32 hex>"}: the ledger's identity, inside every signed entry
  ledger/<key16>.jsonl     # one file per contributor key; append-only; one hash chain per file
```

An `axiom` entry is a GAF 2.2 row (`fact`) plus an envelope (`v, kind, ledger, base, check, prev,
by, ts, sig`); a `derived` entry carries `derivation` and `conclusion` in place of `fact`. An
axiom's `check.counters.new_subject` is 1 when no row in the store `append` checked it against
(base plus admitted ledger facts, not the base alone: plan refinement 26) annotates its subject. Any
entry may also carry the optional `admission` field: an object, reserved for later policy, that v1
treats as opaque (covered by the hash and signature) and that `append` never writes.
Each line is `canon(entry) + "\n"` with `canon = json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=True, allow_nan=False)`. The entry hash is sha256 over the canonical bytes without
`sig`; the signature (`ssh-keygen -Y sign`, namespace `biolean-ledger`) covers the same bytes.
`key16` is the first 16 hex of the sha256 of the signer's raw public-key blob; `by` is the full
digest with a `sha256:` prefix. Contributors read their key as `ssh-keygen -lf key.pub`
(`SHA256:<base64>`); the errors that name an entry's signing key (`LEDGER_SIGNER_MISMATCH`,
`LEDGER_UNKNOWN_SIGNER`) print both forms.

## 2. Commands

```bash
alias mg='.venv/bin/python -m methods_graph.cli'
mg biolean ledger init    --ledger DIR --store snapshots/go --key ~/.ssh/id_ed25519.pub [--principal NAME]
mg biolean ledger append  --ledger DIR --store snapshots/go --key ~/.ssh/id_ed25519 --fact '<json>'      # or @file
mg biolean ledger append  ... --derivation '{"derivation": {...}, "conclusion": {...}}'
mg biolean ledger append  ... --computed '<json>'                                                        # schema-checked, then refused (Phase B)
mg biolean ledger append  ... [--no-cache] [--cache-dir DIR]
mg biolean ledger verify  --ledger DIR [--store DIR] [--recheck] [--extends OLDER_DIR|heads.json] [--signers-sha256 HEX] [--no-cache] [--cache-dir DIR]
mg biolean ledger show    --ledger DIR [--store DIR] [--by KEY16] [--kind axiom|derived|computed] [--contested] [--stale] [--recheck]
                          [--signers-sha256 HEX] [--no-cache] [--cache-dir DIR]
mg biolean prove|check|goals ... --ledger DIR [--signers-sha256 HEX] [--no-cache] [--cache-dir DIR]
```

- `--key` for `append` is an unencrypted ed25519 private key, or its `.pub` when the private half is
  loaded in `ssh-agent`. A passphrase-protected private key file cannot be used directly: the entry
  goes to `ssh-keygen` on stdin, so it would read the passphrase from the entry and fail.
- `init` refuses a key that is not `ssh-ed25519` (`sk-` and certificate types included) and the
  two test fixture keys.
- `bench` never takes `--ledger`: items and scores are over the frozen base only.
- Every ledger call that reads a store re-parses the base (about 13 s on `snapshots/go`) and
  verifies every signature (4.2 ms each in a 100-signature run of the pure-Python verifier on
  Python 3.14.6, 2026-09-25). Only `--recheck` re-proves `derived` entries (§5).
  `load_store` caches "integrity passed for these bytes" per file under
  `~/.cache/biolean-ledger/`, keyed by ledger id, file name, file digest, `allowed_signers` digest
  and the verifier version. `ledger verify` never reads the cache; CI passes `--no-cache`.

`--help` for the group and for `append`, captured 2026-09-25:

```
$ mg biolean ledger --help
usage: methods-graph biolean ledger [-h] {init,append,verify,show} ...

positional arguments:
  {init,append,verify,show}
    init                create a ledger: allowed_signers, base.json, ledger.json, ledger/
    append              check, sign and append one entry
    verify              integrity; with --store also staleness and supersession
    show                print entries as JSON lines

options:
  -h, --help            show this help message and exit
```

```
$ mg biolean ledger append --help
usage: methods-graph biolean ledger append [-h] --ledger LEDGER [--store STORE] --key KEY
                                           (--fact JSON|@FILE | --derivation JSON|@FILE |
                                           --computed JSON|@FILE) [--no-cache]
                                           [--cache-dir CACHE_DIR]

options:
  -h, --help            show this help message and exit
  --ledger LEDGER
  --store STORE
  --key KEY             an unencrypted ssh-ed25519 private key, or its .pub when the key is in
                        ssh-agent
  --fact JSON|@FILE     a 17-column GAF row (list, or object keyed by column name)
  --derivation JSON|@FILE
                        {"derivation": ..., "conclusion"?: ...}
  --computed JSON|@FILE
                        a Phase B computed body (schema-checked, then refused)
  --no-cache
  --cache-dir CACHE_DIR
```

## 3. Exit codes and output

| Exit | Meaning | Output |
|---|---|---|
| 0 | accepted / ok | `append`: `{"verdict": "ACCEPTED", "entry", "hash", "file", "line"}`; `verify`: `{"ok": true, "ledger": <report block>}` |
| 3 | rejected: the body is wrong and fixable | `{"verdict": "REJECTED", "errors": [...], "deferred": [...]}`; nothing written |
| 2 | usage error, including a `--store` missing one of its three base files | argparse text on stderr |
| 2 | unreadable (present but unparseable) store or ledger, integrity failure (`LEDGER_INVALID_ENTRY` from axiom binding included, §5), base mismatch, signers mismatch, rollback, signing failure, another append under the same key landing first (§7) | `{"errors": [...]}` on stdout; nothing loads, nothing is written |
| 2 | `verify\|show --recheck` found a `derived` entry that fails on the base its `base` names (§5) | `verify`: `{"ok": false, "ledger": <report block>}`; `show`: its rows, and one line on stderr |

Exit 2 never means the body is wrong.

## 4. The rejection payload

Every error is `{"code", "message", "field", "got", "fix", "options", "context"}`, all seven keys.
`field` is an RFC 6901 pointer into the entry (`/fact/3` is GAF column 4). `fix` is `null` or one
value that clears the error when written at `field`; `options` are complete alternatives, sorted;
`context` is never substituted. Terminal codes, which no body change clears: `LEDGER_DUPLICATE`,
`NOT_YET_DISCHARGEABLE`, `LEDGER_BASE_MISMATCH`. `deferred` lists `{"step": 4|8, "waits_on":
[<column numbers>]}` for steps that could not run because a column has an error with no fix.
The loop a small model runs: write `fix` at `field` when non-null, else pick from `options`, retry;
stop on a terminal code. `tests/test_biolean_ledger_check.py::test_rejection_fix_is_substitutable`
pins this for every append-rejection code plus `LEDGER_BASE_MISMATCH` and `LEDGER_MALFORMED`; the other
integrity codes are exit 2, outside the retry loop, and are pinned by the integrity tests.

| Code | Fires when | `fix` / `options` |
|---|---|---|
| `LEDGER_BAD_BODY` | the body is not JSON of the expected type | null |
| `LEDGER_BAD_COLUMNS` | not 17 string columns, or an unknown key in the object form | null; `context.columns` |
| `LEDGER_BAD_CHARACTER` | a surrogate, control, format or separator character, non-NFC text, or non-ASCII in an identifier column | the cleaned value; null for a bad key in a `derived` or `computed` body |
| `LEDGER_BAD_SUBJECT` | column 1 not `^[A-Za-z][A-Za-z0-9_.-]*$`, or column 2 empty / whitespace / `\|` | null |
| `UNKNOWN_TERM`, `LEDGER_ALT_ID`, `OBSOLETE_TERM` | column 5 is unknown, an alt id, or obsolete | `UNKNOWN_TERM`: always null, no options. `LEDGER_ALT_ID` whose primary is live: fix the primary. `OBSOLETE_TERM`, and `LEDGER_ALT_ID` whose primary is obsolete: fix the single live `replaced_by`; with several live `replaced_by`, fix null and options those; with none, fix null and options the live `consider` terms (even one); with neither, fix null and no options. Live means a known, non-obsolete term; in the obsolete cases `context` lists the raw `replaced_by` and `consider` |
| `LEDGER_ASPECT_MISMATCH` | column 9 differs from the term's namespace aspect | the letter |
| `UNKNOWN_QUALIFIER`, `QUALIFIER_ASPECT_MISMATCH` | column 4 is not `q` or `NOT\|q` for one of the 13 qualifiers, or `q` is illegal for the term's aspect | fix null. Options: the qualifiers legal for the term's aspect, each with `NOT\|` when the row had it; for `UNKNOWN_QUALIFIER`, all 13 when column 5 does not resolve to a live term (directly or through its fix), and none when column 4 holds a `\|` beyond a leading `NOT\|` |
| `LEDGER_ECO_UNMAPPED` | column 7 has no ECO mapping in the base | options: the mapped codes |
| `LEDGER_BAD_REFERENCE`, `LEDGER_REFERENCE_REQUIRED` | a `DOI:`/`PMID:`/`GO_REF:` value is malformed; none is present | null |
| `LEDGER_BAD_TAXON`, `LEDGER_BAD_DATE`, `LEDGER_BAD_OBJECT_TYPE` | column 13 is not one or two `\|`-separated `taxon:<digits>` values, each with no leading zero (`taxon:0` excepted); column 14 is not `YYYYMMDD` or is not a real date (`20261301`); column 12 is empty | taxon: the canonical spelling when there are one or two values and each reads as ASCII digits (`NCBITaxon:9606`, `9606`, `taxon:09606`), else null with `context.form`; date: `YYYYMMDD` from a real `YYYY-MM-DD`, else null with `context.form`; object type: the `object_type` of the subject's annotation with the smallest id in the loaded store, else null |
| `LEDGER_ASSIGNED_BY` | column 15 is neither empty nor `biolean:<your key16>` | `biolean:<key16>` |
| `LEDGER_DUPLICATE` | the content key equals a base row's or another entry's | null; `context.existing` |
| `LEDGER_DERIVATION_REJECTED`, `LEDGER_SORRY_USED`, `LEDGER_SORRY_UNUSED`, `LEDGER_CONCLUSION_MISMATCH` | derived bodies | null, except the conclusion fix (the elaborated goal) |
| `LEDGER_BAD_COMPUTED`, `NOT_YET_DISCHARGEABLE` | computed bodies | null, except `/conclusion/taxon` (fix: the `NCBITaxon:<digits>` form when derivable, else `context.form`) and `/preconditions/<i>/status` (options: `met`, `unknown`, `unmet`) |
| `LEDGER_BAD_KIND` | `kind` is not `axiom`, `derived` or `computed` | null; options: the three kinds |
| `LEDGER_BASE_MISMATCH` | `append` only: `--store` is not the base `base.json` declares. `verify\|show --store` and `prove\|check\|goals --ledger` against another store never raise it; they bind each entry to that store instead (an axiom is admitted, counted in `rechecked_ok`, or stale, superseded, or `LEDGER_INVALID_ENTRY`; a derived entry is `recorded`: §5) | null; `context` the declared `obo`, `gaf`, `eco` digests |
| `LEDGER_VERSION` | `v` is not the JSON integer 1 | `1` |
| `LEDGER_MALFORMED`, `LEDGER_WRONG_LEDGER`, `LEDGER_SIGNER_MISMATCH`, `LEDGER_UNKNOWN_SIGNER`, `LEDGER_BAD_SIGNATURE`, `LEDGER_CHAIN_BROKEN`, `LEDGER_INVALID_ENTRY`, `LEDGER_ROLLBACK`, `LEDGER_SIGNERS_MISMATCH`, `LEDGER_UNSUPPORTED_KEY`, `LEDGER_KEY16_COLLISION`, `LEDGER_SIGNING_FAILED` | integrity and environment (exit 2) | null. `context` carries `file` and `line` (`line` null for a fault not on one line) when a ledger file or the store is at fault (for `LEDGER_UNKNOWN_SIGNER` at append, the file is `allowed_signers`). It is null where neither is: every `LEDGER_UNSUPPORTED_KEY` (a refused `--key`, fixture key or `--principal`), every `LEDGER_SIGNING_FAILED`, and `init`'s "already holds a ledger" `LEDGER_MALFORMED`. A `LEDGER_MALFORMED` for an unknown `kind` keeps the three kinds as options. A binding `LEDGER_INVALID_ENTRY` (§5; axioms only) also names the failing §2 check in `context.code` and whether the entry names this base in `context.same_base`. `append`'s `LEDGER_CHAIN_BROKEN` ("the file changed since it was verified; retry", §7) has `field` `/prev` |

A `LEDGER_MALFORMED` inside an exit-3 `append` result (step 7a: the row does not round-trip
through `parse_gaf` as exactly one annotation) is a defect guard: a row reaches step 7a only
after every earlier error had a fix, and none of 20,000 fuzzed rows in the final review reached
it, so it is unreachable in append mode as far as anyone has found.

## 5. What verify proves, and what it does not

`verify` proves every entry present was signed by a key on `allowed_signers` with the namespace
permitted, that each file is one unbroken chain, that each `check.annotation_id` matches its
row, and that no fact repeats within a file. It does not prove completeness: a truncated file, a deleted file and an older version all
verify. `--extends <older dir | heads.json>` adds that check (`LEDGER_ROLLBACK`). Without
`--signers-sha256`, the trusted list is whatever was last pushed. Removing a key from
`allowed_signers` makes the whole ledger fail until that key's file is deleted too: revocation is
one commit that does both, and it is loud by design.

With `--store`, `verify` re-runs the append check (steps 1-7a, on the row as signed) on every
`axiom` entry against that base. An entry that fails a base-independent check, or fails on the base it names, is `LEDGER_INVALID_ENTRY` (exit 2).
One that fails only because the base moved is `stale` (excluded, counted, listed). One whose
content the base now carries is `superseded_by_base` (excluded, counted, listed).

A `derived` entry is not bound (plan refinement 24). It adds nothing to the store (it is
recorded, not admitted), so no load re-proves it and none fails a load: `append`,
`prove|check|goals --ledger` and `verify|show --store` without `--recheck` never run the §2
`derived` rule. A revoked key's deleted file must not fail every load through another signer's
derived entry that cited one of its facts. `verify|show --recheck` re-run the rule, conclusion
comparison included, over the loaded store (base plus admitted ledger facts). Every failure is
counted in `derived_failed` and listed in `derived_failed_entries` with its `errors`,
`kernel_codes` (the kernel's error codes) and `same_base` (true when the entry's `base` names
this base). A failure with `same_base` true makes `ok` false and the exit code 2, with the report
(for `show`, the rows) still printed. A failure on another base is counted and listed the same
way, but `ok` stays true and the exit code 0. No derived entry is ever `LEDGER_INVALID_ENTRY`.

The exit code is the verdict. 0 means every file is intact, no axiom is `LEDGER_INVALID_ENTRY`
(none fails a base-independent check, none fails on the base it names), with `--extends` nothing
rolled back, and with `--recheck` no derived entry fails on the base it names. `ok` is `false`
exactly in that last case; every other counter says what moved with the base and never changes the exit
code. The report block:

```json
"ledger": {"files", "entries", "axioms", "derived", "computed", "admitted", "rechecked_ok",
           "stale", "stale_entries", "superseded_by_base", "superseded_entries",
           "duplicate_content", "duplicate_content_entries", "contested", "contested_entries",
           "heads", "allowed_signers_sha256", "files_verified_from_cache", "cache_mark_failures",
           "derived_rechecked", "derived_failed", "derived_failed_entries"}
```

Base-dependent counters are `null` without `--store`; the `derived_*` keys are `null` unless
`--recheck` ran. `contested` is recomputed over the loaded store, never read from an entry's
`check.contested_by`. A derived entry adds nothing to the store; it is a citable record.

## 6. Trust boundary

`biolean/ed25519.py` (RFC 8032 §5.1.7, verify-only, stricter than OpenSSH: `S < L`),
`biolean/sshsig.py` (the `sshsig` blob, `allowed_signers`, key digests) and `biolean/ledger/`
sit beside the kernel. `test_ledger_and_verifier_modules_import_no_network_or_bench_module` walks
every import statement in them, in `kernel.py` and in the modules its verdict depends on
(`props`, `errors`, `store`, `obo`, `gaf`, `eco`) and refuses `fetch`, `bench`, `subprocess`, `urllib`,
`socket`, `http` and `requests`, relative or absolute.
Signing is the contributor's `ssh-keygen`; the repo has no signing code. Any change to
`ed25519.py` needs review against RFC 8032 §5.1.3 and §5.1.7; the vectors do not exercise every
path.

## 7. Contributing to a ledger repo

Clone, `append` locally, push, open a PR. Use one machine per key, or pull before you append:
two clones appending under one key diverge, and the merged file is a fork, an integrity failure
(`LEDGER_CHAIN_BROKEN`). On one machine two concurrent appends under one key cannot fork the
file (plan refinement 25): `append` takes an exclusive `flock` on `ledger/<key16>.jsonl`,
re-hashes it, and writes only while it still hashes to what integrity verified at load;
otherwise it refuses with `LEDGER_CHAIN_BROKEN`, "the file changed since it was verified;
retry" (exit 2, nothing written), and a retry appends on the new head. Where `fcntl` is missing
the lock is a no-op and the re-hash still refuses a line that landed before it.

`init` writes an empty `ledger/<key16>.jsonl` for its key (plan refinement 27), so a fresh ledger survives a clone
(git keeps no empty directory); an empty file is an intact chain with no entries. `ledger/` may
hold only `<key16>.jsonl` files: anything else, Finder's `.DS_Store` included, fails `verify`
(`LEDGER_MALFORMED`).

CI runs
`verify --ledger . --store <base> --signers-sha256 <target branch's digest> --recheck --extends
<merge base> --no-cache` and gates on its exit code (§5): exit 2 fails the job, including a
derived entry that fails on the base it names (`"ok": false`, the report still printed). A
derived entry failing only on another base, like every other counter, leaves exit 0 and `ok`
true, and is for the reviewer. Changes to `allowed_signers`, `base.json` and `ledger.json` need owner
review on the host. The base pair must be available on the runner; today it cannot be re-fetched
(decision O-02), which blocks a federated ledger until the pair is published beside it.

To add a contributor, the owner appends one line to `allowed_signers` in the form `init` writes:

```
<principal> namespaces="biolean-ledger" ssh-ed25519 <base64 key> [comment]
```

that is, a principal and the `namespaces` option in front of the contributor's `.pub` line
(check its `ssh-keygen -lf` fingerprint with them). The principal is one token, with no
whitespace, `,` or `"` and no leading `#`; drop a comment that holds a `"`. Keep
`biolean-ledger` in the `namespaces` list: a list without it makes that key's entries
`LEDGER_UNKNOWN_SIGNER`. The change alters the `allowed_signers` digest, so every
`--signers-sha256` pin moves with it.

Step 1a's NFC and character-category checks use the interpreter's Unicode database, so a string
can pass `append` under one Python and fail `verify` under another: `unicodedata.unidata_version`
is 15.0.0 on Python 3.12 (CI's version) and 16.0.0 on 3.14. The committed fixtures reproduce
byte for byte under Python 3.14.6 (16.0.0). Which version a ledger repo pins is an owner decision.

## 8. Fixtures and tests

`tests/fixtures/biolean/ledger/`: a two-namespace ontology, a ten-row GAF, a four-code ECO
mapping, two ed25519 test keys (`keys/`, trusted by nothing, refused by `init`), four real
`ssh-keygen` signatures over known messages (`known/`), the RFC 8032 vectors, a signed fixture
ledger (`signed/`), hand-signed lines that must fail in specific ways (`signed-variants/`), and
one real signature per append a test makes (`sigs/`, content-addressed by the bytes signed).
`make_fixtures.py` makes `signed/`, `signed-variants/` and `sigs/` with the real `ssh-keygen`
(`keys/` and `known/` were made once by hand with it and are never regenerated); the suite never
spawns it. Re-run it after any change to the envelope, the kernel version, the fixture base or a
scenario.
