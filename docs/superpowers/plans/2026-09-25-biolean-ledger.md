# Biolean Ledger Implementation Plan

> **Status as of 2026-09-25: written against the spec as revised on 2026-09-25; reviewed; implemented on branch `worktree-biolean-ledger` (implementing commits `6730da3..edd9d4c` plus the Task 10 docs commits and the final-review fix wave, refinements 24–27; merge commit to be recorded by the owner at merge); 1218 passed / 33 skipped in a CI-like checkout; the main checkout with `data/methods.kuzu` and `snapshots/go/` present skips 1.** Before handoff the planner ran every code block of Tasks 1–10 in a scratch copy of the repo (`make_fixtures.py` with the real `ssh-keygen` included), then put the plan through a nine-lens adversarial review (spec fidelity by section, code correctness by task range, test validity) with three independent refuters per finding: 32 findings, 26 unique, 19 upheld and applied in the text below (among them: `got` is the value as submitted; step 6 emits by column; a repeated row within one file fails integrity; a non-JSON body is `LEDGER_BAD_BODY`, exit 3; an unreadable store is `LEDGER_MALFORMED`, exit 2; `show` prints the fingerprint; refinements 16–19; six tests rewritten so the mutation they name actually fails them), 7 refuted; a second review of those fixes (three lenses, two refuters per finding) upheld 9 of 16 findings, all applied (refinement 19, integrity errors carry no value fix, the cache test observes both cache locations, `got` at integrity step 7). After those fixes the whole suite gave 1,148 passed / 33 skipped without `OPENAI_API_KEY`, fixture regeneration was byte-identical to the planner's untracked fixtures, and 28 named mutation checks failed as required.
> Where a task refines the spec (a detail the spec leaves open, or a rule the plan tightens so a
> stated invariant holds), it says so in the task and the list under "Plan refinements" below.
> Task 10 copies that list into the spec's status banner so spec and code agree.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An append-only, signed, hash-chained ledger of kernel-checked GO facts (`mg biolean ledger init|append|verify|show`) that `load_store` and `prove|check|goals --ledger` read as an extension of the frozen release, with a rejection payload a weak model can iterate against.

**Architecture:** Verification is in-repo and stdlib-only: `biolean/ed25519.py` (RFC 8032 §5.1.7, verify-only) under `biolean/sshsig.py` (OpenSSH `sshsig` blob, `allowed_signers`, key digests). The ledger itself is the `biolean/ledger/` package: `errors.py` (the seven-key error shape and every code), `format.py` (canonical bytes, entry hash, field schema, the character rules), `check.py` (the §2 append check for `axiom`, `derived`, `computed`, with fix application), `integrity.py` (§3 per-file verification, `--extends`, the verification cache), `load.py` (base binding, staleness, supersession, the store assembly and the `ledger` report block) and `append.py` (`init`, signing through the injectable `runner`, self-verify, write). `store.load_store` gains `ledger_dir=`, delegating through a function-level import so the kernel↔store import graph stays acyclic. `cli.py` adds the nested `ledger` subparser and `--ledger` on `prove|check|goals`. Signing in tests goes through a fake `runner` that returns real `ssh-keygen` armor made once by `tests/fixtures/biolean/ledger/make_fixtures.py`, content-addressed by the sha256 of the bytes signed.

**Tech Stack:** Python 3.12+ stdlib only (`hashlib`, `base64`, `struct`, `json`, `unicodedata`, `datetime`, `secrets`, `pathlib`, `dataclasses`, `re`). No new runtime dependencies. pytest. `ssh-keygen` (OpenSSH 10.3 locally) only in `make_fixtures.py`, never in the suite.

**Spec:** `docs/superpowers/specs/2026-09-25-biolean-ledger-design.md`. Phase A as built: `docs/biolean/README.md`. Plan 1 and Plan 2 are merged (`7bc79ef`, `b0f80c4`); this plan edits `kernel.py` only in Task 2, which is guarded by the existing kernel tests and the committed golden verdict.

## Global Constraints

- **No new runtime dependencies.** `pyproject.toml` stays `kuzu==0.11.3`, `polars`, `pyyaml`, `networkx`. Everything here is stdlib. `urllib.request` over `requests`, never needed here anyway: the checker forbids network.
- **The trusted base stays one thing** (spec §0.1). Nothing under `biolean/ledger/`, `biolean/sshsig.py`, `biolean/ed25519.py` or `biolean/store.py` imports `methods_graph.fetch`, `methods_graph.bench` or `methods_graph.biolean.bench`. Task 5 pins this with a source scan.
- **Verify-only crypto** (spec §0.6). There is no signing code in the repo. Signing is `ssh-keygen -Y sign` through `runner=subprocess.run`, the seam `fetch.py` uses. The argv is exactly `["ssh-keygen", "-Y", "sign", "-f", <key>, "-n", "biolean-ledger"]`, the message on stdin, `capture_output=True, check=True`, no `text=True`, no file argument.
- **Canonical bytes** (spec §1): `canon(obj) = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")`. Entry hash = `sha256(canon(entry without "sig")).hexdigest()`, 64 lowercase hex, no prefix. The signature is over the same bytes.
- **The error shape** (spec §7): every ledger error is `{"code", "message", "field", "got", "fix", "options", "context"}`, all seven keys, always. No kernel `Error` is ever passed through. `fix` is `null` or exactly one JSON value that clears the error when written at `field`; `options` is a sorted, duplicate-free list of complete candidate values, `[]` when none; `context` is `null` or an object that is never substituted.
- **Exit codes** (spec §7): 0 accepted; 3 rejected (the body is wrong and fixable); 2 usage error (argparse, text on stderr; a `--store` missing one of its three base files is one, as in Phase A), unreadable (present but unparseable) store or ledger, integrity failure, base mismatch, signers mismatch, rollback, or signing failure (JSON `{"errors": [...]}` on stdout, never through `parser.error`). Exit 2 never means the body is wrong.
- **Integrity is not a counter** (spec §3): any integrity failure raises `LedgerIntegrityError` and nothing loads.
- **Nothing is dropped silently.** Every excluded entry is counted and listed with an id; every counter ships even when zero; undefined is `None`, never `0`.
- **Determinism.** Sort every set iteration; JSON is written `sort_keys=True`; every list in a report is sorted by the key the task names; `ts` is injected by the caller, so an entry's canonical bytes are stable and its signature is a fixture.
- **Identifier discipline.** GAF column N is JSON pointer `/fact/<N-1>`. `key16` is the first 16 hex of the sha256 of the raw public-key blob; `by` is `sha256:` + the full 64 hex. Annotation ids are `gaf.annotation_id` over the 17 columns as signed, never recomputed from a re-split line.
- **No test hits the network, spawns a process, or touches the real home directory.** Signing in tests is the fake runner in `tests/biolean_ledger_fixture.py`; `cache_dir` is always `tmp_path` or `use_cache=False`; `tests/conftest.py` (Task 7) points `HOME` at `tmp_path` for every `test_biolean_ledger_*` module. The suite passes with `OPENAI_API_KEY` unset: `env -u OPENAI_API_KEY $PYTEST -q`.
- **Test discipline (the mutation rule).** Before accepting a test, apply the mutation its step names and confirm the test fails; write "mutation checked: <what>" in the commit body. A rejection assertion names the code and the `field`, never the verdict string alone.
- **Fixtures are made once, by `make_fixtures.py`, never by the suite.** After any change to the envelope, `methods_graph.__version__`, the fixture base or a scenario body, re-run it (Task 8 step 9) and commit the result. The fake runner fails loudly, naming the missing file, when a signature is stale.
- Run tests as `$PYTEST` where, in the main checkout, `PYTEST=".venv/bin/python -m pytest"` and, in a worktree without its own venv, `PYTEST="env PYTHONPATH=src <main-checkout>/.venv/bin/python -m pytest"` (the editable install points at the main checkout's `src`; verify with `python -c "import methods_graph; print(methods_graph.__file__)"`). There is no `python` on PATH.
- The worktree guard rejects compound Bash commands (`&&`, `;`, heredocs) and commands whose text names `git`/`github`; run one plain command per call and write helper scripts with the Write tool.
- Commit after every task with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Nothing lands on `main` without the owner.

### Plan refinements (recorded in the spec banner by Task 10)

1. **Step 1a runs first and its fixes feed every later step.** Steps 2–7 evaluate the row after step 1a's character fixes are applied; steps 4 (aspect half), 7a and 8 evaluate the row after every non-null fix is applied. Otherwise a control character hiding a valid term id would yield `UNKNOWN_TERM` (fix `null`) that vanishes once the character fix is applied, breaking the spec's invariant.
2. **Step 4 has two halves.** Qualifier membership (`UNKNOWN_QUALIFIER`) always runs; when column 5 does not resolve its `options` are all 13. The aspect half (`LEDGER_ASPECT_MISMATCH`, `QUALIFIER_ASPECT_MISMATCH`) waits on column 5 and is what `deferred: [{"step": 4, "waits_on": [5]}]` names. `deferred` lists steps 4 and 8 only; step 7a runs with step 8 because they share the final row.
3. `--fact`, `--derivation` and `--computed` take inline JSON text, or `@<path>` to read a file.
4. A `derived` body is `{"derivation": <derivation>, "conclusion"?: <Prop>}`. A missing `conclusion` is filled from the verdict's elaborated goal (as column 15 is filled); a present one that differs is `LEDGER_CONCLUSION_MISMATCH`.
5. `show` also accepts `--recheck` (with `--store`), so "unless `--recheck` ran" is reachable. A `show` line is `{"file", "line", "hash", "entry", "fingerprint", "status", "contested", "rechecked", "recheck_errors"}`, `fingerprint` being the `SHA256:<unpadded base64>` form of the entry's signing key (spec §1); `status` is `admitted | stale | superseded_by_base` for `axiom` and `recorded` for `derived`, `null` without `--store`; `contested` is a bool or `null` without `--store`; `rechecked` is a bool and `recheck_errors` a list or `null`.
6. `verify` prints `{"ok": true, "ledger": <block>}` on success. Without `--store`, the base-dependent counters (`admitted`, `rechecked_ok`, `stale`, `stale_entries`, `superseded_by_base`, `superseded_entries`, `duplicate_content`, `duplicate_content_entries`, `contested`, `contested_entries`) are `null`, never `0`. `derived_rechecked`, `derived_failed` and `derived_failed_entries` are `null` unless `--recheck` ran.
7. A verification-cache hit skips only integrity step 5 (the signature check); steps 1–4, 6 and 7 always run, because they are cheap and the parsed entries are needed anyway.
8. The `LEDGER_BAD_OBJECT_TYPE` fix is the `object_type` of the subject's base annotation with the smallest annotation id.
9. In a `computed` body, a `conclusion.taxon` not matching `^NCBITaxon:\d+$` is `LEDGER_BAD_COMPUTED` at `/conclusion/taxon` with `fix` the `normalize_taxon` form when there is one, else `null` with `context: {"form": "NCBITaxon:<digits>"}`.
10. `init --principal` defaults to the key's comment, or `key16` when the `.pub` has none.
11. `load_store` is factored as `load_base` (the three files, their digests, the parser callables) plus store assembly; `ledger/load.py` holds `load_with_ledger`, which `load_store(ledger_dir=…)` calls through a function-level import (`kernel` → `store` at module level, and `ledger.check` → `kernel`, so `store` cannot import `ledger` at module level).
12. `init` refuses the two fixture keys through `sshsig.FIXTURE_KEY_DIGESTS`, with `LEDGER_UNSUPPORTED_KEY`.
13. The fork fixture's `LEDGER_CHAIN_BROKEN` also carries `context.fork_of_line` when the bad `prev` equals an earlier entry's hash in the same file.
14. At integrity, every shape or character failure is `LEDGER_MALFORMED` (with the specific message) except `LEDGER_VERSION` and `LEDGER_WRONG_LEDGER`, which keep their codes; at append, the same body faults use the §2 codes (`LEDGER_BAD_COLUMNS`, `LEDGER_BAD_CHARACTER`, …). At integrity every `LEDGER_MALFORMED` carries `fix: null` (§7, "every §3 integrity code"); `LEDGER_VERSION` keeps `fix: 1`, the §7 value row, which `append` never reports because it builds `v` itself.
15. `LEDGER_BAD_REFERENCE` is one error per bad value, each with `field: "/fact/5"` and `got` the whole column.
16. `LEDGER_BAD_KIND` carries `fix: null` and `options: ["axiom", "computed", "derived"]` (the §7 table lists it under `options: []`), because each clears the error when written at `/kind`. At integrity the same fault is `LEDGER_MALFORMED` (refinement 14) with `fix: null` and keeps those options.
17. In a `computed` body, a precondition `status` outside `met|unmet|unknown` is `LEDGER_BAD_COMPUTED` at `/preconditions/<i>/status` with `fix: null` and `options: ["met", "unknown", "unmet"]`; every other `LEDGER_BAD_COMPUTED` pointer carries `fix: null`, `options: []`, except `/conclusion/taxon` (refinement 9).
18. A `--store` lacking one of its three base files is an argparse usage error (text on stderr), as in Phase A. A base file that is present but cannot be read, gunzipped or decoded as UTF-8 is `LEDGER_MALFORMED` with `context.file` the store directory, exit 2, JSON on stdout, from every command that reads the store beside a ledger (`init`, `append`, `verify|show --store`, `prove|check|goals --ledger`); base-only `prove|check|goals` keep their Phase A behaviour.
19. Integrity step 7 also refuses an `axiom` whose recomputed annotation id repeats an earlier line of the same file: `LEDGER_INVALID_ENTRY`, `field: "/fact"`, `got` the row, `context.first_line` and `context.annotation_id`. It needs no base, so plain `verify` runs it too. Step 7a is a one-row check (`parse_gaf` over a single row always reports `duplicate_row: 0`) and cannot see a repeat, so the spec's §3 Load sentence crediting that refusal to 7a is corrected here; without this check a hand-signed repeat passes integrity and `StaticFactStore` raises a bare `ValueError` at load.
20. Nesting is bounded: `MAX_DEPTH = 64` (`format.py`). `canon` refuses a deeper object with `ValueError`, as it refuses NaN, so nothing deeper is ever hashed or written; `parse_line` returns `(None, "nesting deeper than 64 levels")` on a `RecursionError` from `json.loads` or on that refusal; the append body parser applies `nesting_depth` before any other check. Without the bound a hostile line crashed `verify` with a traceback instead of exit 2: a ~1,500-deep line passed `parse_line` and `shape_errors` and overflowed `character_errors`.
21. §2 step 1a applies to dict keys, not only to string values: a key that is not NFC or holds a lone surrogate is `LEDGER_BAD_CHARACTER` at the containing object's pointer (`""` at the top level), `got` the code point, `fix` null (renaming a key is not a value substitution `pointer_set` can apply). Keys the schema fixes are ASCII already; this reaches the free-form objects.
22. Column 13 is canonical: `taxon:<digits>` with no leading zeros (and the same for the second `|` value). Step 6 reports every other spelling, `taxon:09606` included, with the canonical fix, so a resubmission under a non-canonical spelling is caught by the step 8 duplicate check instead of being admitted as a distinct row. Step 6 never calls `int()` (Python's 4300-digit limit made a long taxon raise), and in recheck mode a row with a column that is not UTF-8-encodable (a lone surrogate) skips the hashing steps 7a/8 with `annotation` None: the step-1a error already names the fault and `annotation_id` would raise. Other step-1a faults still hash, so a line separator inside a column cannot become a second row.
23. The verifier's exception contract is explicit: `verify_ledger` raises `LedgerIntegrityError` and nothing else on any input (a deeply nested `ledger.json`, an unreadable or unstattable file or directory are `LEDGER_MALFORMED` with `context.file`), `check_extends` raises `ValueError` and nothing else (and validates a heads map: key16 keys, non-negative integer `entries`, `head` "" exactly when `entries` is 0, else 64 hex), and the cache is an optimisation that never fails a ledger: a mark that cannot be written is counted in `LedgerState.cache_mark_failures` and reported as `ledger.cache_mark_failures` (spec §3 report block gains that key); a cache that cannot be read is a miss. Stat-style checks treat `OSError` as "not that kind of file" so the contract holds on Python 3.10–3.14 (before 3.13 `pathlib` raises on EACCES).
24. **A derived entry is re-proved only by `--recheck`, and only a failure on its own base fails the run.** Derived entries add nothing to the store (they are recorded, not admitted), so no load re-proves one and none fails a load: `append`, `prove|check|goals --ledger` and `verify|show --store` without `--recheck` never run the §2 `derived` rule, and no derived entry is ever `LEDGER_INVALID_ENTRY`. A revoked key's deleted file must not make every load fail through another signer's derived entry that cited one of its facts. `verify|show --recheck` re-run the rule, conclusion comparison included, over the loaded store (base plus admitted ledger facts). Every failure is counted in `derived_failed` and listed in `derived_failed_entries` with its `errors`, `kernel_codes` (the kernel's error codes) and `same_base` (true when the entry's `base` digests are the loaded base's). A failure with `same_base` true makes the report's `ok` false and the exit code 2 (the CI gate), with the report still printed (`show` prints its rows and one line on stderr); a failure on another base is counted and listed the same way, but `ok` stays true and the exit code 0. This amends refinement 6 (`ok` can be false) and the §7 exit-2 output (a `--recheck` exit 2 prints the report, not `{"errors": [...]}`).
25. **`append` writes only onto the file it verified.** `LedgerState.file_sha256` keeps the sha256 of each file integrity verified. `append` opens `ledger/<key16>.jsonl` with mode `"ab"`, takes `fcntl.flock(LOCK_EX)` (a no-op where `fcntl` is missing), re-reads the file under the lock through a second descriptor that must be the same open file, and writes its line only when the file still hashes to the verified digest (an absent file counts as empty). Otherwise it raises `LEDGER_CHAIN_BROKEN` ("the file changed since it was verified; retry", `field: "/prev"`, `context.file` and `context.line`) and writes nothing. Two concurrent appends under one key on one machine give one entry and one exit-2 retry instead of a fork; two clones appending under one key still diverge, and `verify` refuses the merged file as a fork.
26. **`new_subject` and the `LEDGER_BAD_OBJECT_TYPE` fix read the store `append` checks against.** Step 2's `counters.new_subject` and step 6's object-type fix (refinement 8) consult the loaded store, base plus admitted ledger rows, where spec §2 step 2 and refinement 8 say the base only: a subject an admitted ledger entry introduced is not counted new again, and the fix is the `object_type` of the subject's annotation with the smallest id in that store, which can be a ledger row. `docs/biolean/ledger.md` describes this behaviour.
27. **`init` also writes an empty `ledger/<key16>.jsonl` for its key.** Spec §7 says only that `init` creates `ledger/`; git tracks no empty directory, so a clone of a fresh ledger had no `ledger/` and failed `verify`. The empty file (spec §1: an intact chain with no entries; `heads()` gives `{"entries": 0, "head": ""}`) keeps the directory in a clone, and `append` treats it exactly as an absent file (`prev` "", line 1). `init` creates it only when no file is there and never writes to an existing one; an empty key16 file it finds holds no signer, so it is not a key16 collision.

## File structure

| File | Responsibility |
|---|---|
| `src/methods_graph/biolean/store.py` (modify, Tasks 1 and 7) | `gaf_header`, `read_release` (moved here from `fetch.py` / `bench/items.py`), `_read_bytes`, `base_digests`, `BaseLoad`, `load_base`; `load_store(…, ledger_dir=, expected_signers_sha256=, cache_dir=, use_cache=)` |
| `src/methods_graph/fetch.py`, `src/methods_graph/biolean/bench/items.py`, `src/methods_graph/cli.py` (modify, Task 1) | import `gaf_header` / `read_release` from `store` |
| `src/methods_graph/biolean/gaf.py` (modify, Task 2) | `GAF_COLUMNS` |
| `src/methods_graph/biolean/kernel.py` (modify, Task 2) | `check_term` (public), `check_qualifier_aspect` (extracted from `_check_prop`) |
| `src/methods_graph/biolean/ed25519.py` (Task 3) | `verify`, `is_small_order`, the field and point arithmetic |
| `src/methods_graph/biolean/sshsig.py` (Task 4) | `parse_sshsig`, `verify_sshsig`, `signed_data`, `dearmor`, `armor`, `parse_public_key_line`, `parse_key_blob`, `key_digest`, `key16`, `fingerprint`, `Signer`, `parse_allowed_signers`, `find_signer`, `allowed_signers_line`, `FIXTURE_KEY_DIGESTS`, `NAMESPACE`, `KEY_TYPE`, `SshsigError`, `AllowedSignersError` |
| `src/methods_graph/biolean/ledger/__init__.py` (Task 5) | package marker |
| `src/methods_graph/biolean/ledger/errors.py` (Task 5) | `LedgerCode`, `ALL_LEDGER_CODES`, `TERMINAL_CODES`, `INTEGRITY_CODES`, `BASE_INDEPENDENT_CODES`, `LedgerError`, `LedgerIntegrityError` |
| `src/methods_graph/biolean/ledger/format.py` (Task 5) | `canon`, `entry_hash`, `unsigned`, `parse_line`, `shape_errors`, `character_errors`, `column_character_error`, `clean_string`, `pointer_get`, `pointer_set`, field constants and regexes |
| `src/methods_graph/biolean/ledger/check.py` (Task 6) | `CheckContext`, `AxiomResult`, `DerivedResult`, `fact_from_body`, `check_axiom`, `check_derived`, `check_computed`, `content_key`, `term_errors`, `qualifier_options` |
| `src/methods_graph/biolean/ledger/integrity.py` (Task 7) | `LEDGER_VERIFIER_VERSION`, `LedgerEntry`, `LedgerState`, `read_ledger_id`, `verify_ledger`, `check_extends`, `integrity_report`, the cache helpers |
| `src/methods_graph/biolean/ledger/load.py` (Task 7) | `BoundEntry`, `LoadedLedger`, `bind_entries`, `superseded_by`, `ledger_report`, `load_with_ledger`, `recheck_derived`, `contested_ids` |
| `src/methods_graph/biolean/ledger/append.py` (Task 8) | `SignerKey`, `read_signer`, `base_object`, `init_ledger`, `sign`, `AppendResult`, `append_entry` |
| `src/methods_graph/cli.py` (modify, Task 9) | `mg biolean ledger init|append|verify|show`; `--ledger`, `--signers-sha256`, `--no-cache`, `--cache-dir` on `check|prove|goals`; `prove --ledger` reference post-processing |
| `.gitignore` (modify, Task 9) | `/biolean-ledger/` |
| `tests/conftest.py` (Task 7) | `HOME` → `tmp_path` for ledger test modules |
| `tests/biolean_ledger_fixture.py` (Task 6, extended Task 8) | fixture paths, `ledger_store`, `copy_ledger_store`, `copy_signed`, `fake_runner`, `new_fact`, `SCENARIOS`, `run_scenario`, `SIGNED_SEQUENCE` |
| `tests/fixtures/biolean/ledger/` | `ledger.obo`, `ledger.gaf`, `ledger-eco.txt` (Task 6); `rfc8032-ed25519.json` (Task 3); `keys/`, `known/` (Task 4); `make_fixtures.py`, `signed/`, `signed-variants/`, `sigs/` (Task 8) |
| `tests/test_biolean_ed25519.py`, `test_biolean_sshsig.py`, `test_biolean_ledger_format.py`, `test_biolean_ledger_check.py`, `test_biolean_ledger_integrity.py`, `test_biolean_ledger_append.py`, `test_biolean_ledger_load.py`, `test_biolean_ledger_cli.py` | one test module per source module; the north-star test lives in `test_biolean_ledger_check.py` (Task 10) |
| `docs/biolean/ledger.md` (Task 10) plus edits to `docs/biolean/README.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md`, `docs/README.md`, `CLAUDE.md`, the spec banner | as-built reference |

## Review Focus

Inputs the spec implies but names no test for, most likely to bite first. Each line's test is added to the task named.

1. **A `.jsonl` with a UTF-8 BOM, `\r\n` endings, or a final line without `\n`** must be `LEDGER_MALFORMED` at that line, never a traceback. → Task 7, `test_bom_crlf_and_missing_final_newline_are_malformed`.
2. **A `--fact` object whose value is a JSON number or `null` where a string is expected** (`"date": 20260925`) must be `LEDGER_BAD_COLUMNS` with the column named, never a `TypeError`. → Task 6, `test_non_string_column_value_is_bad_columns`.
3. **A ledger directory missing `ledger.json`, `allowed_signers` or the `ledger/` directory**, or with an unreadable `ledger.json`, must be `LEDGER_MALFORMED` naming the file, exit 2 with JSON, never `FileNotFoundError`. → Task 7, `test_missing_ledger_files_are_malformed_not_a_crash`.
4. **`sig` in URL-safe base64, or with whitespace, or empty** must be `LEDGER_BAD_SIGNATURE`, and the `ts` `2026-02-30T00:00:00Z` (well-formed, not an instant) must be `LEDGER_MALFORMED`. → Task 4 `test_sshsig_fields_are_enforced` and Task 7 `test_unparseable_sig_is_bad_signature_with_file_and_line` for `sig`; Task 5 `test_impossible_ts_is_malformed_by_shape` for `ts`.
5. **`verify --extends` given a path that is neither a directory nor a JSON heads map** must be a usage error (exit 2, text on stderr), never `LEDGER_ROLLBACK` and never a `JSONDecodeError`. → Task 9, `test_extends_with_a_bad_path_is_a_usage_error`.

---

### Task 1: Move `read_release` and `gaf_header` into `store.py`; add `base_digests` and `load_base`

**Files:**
- Modify: `src/methods_graph/biolean/store.py`
- Modify: `src/methods_graph/fetch.py:738-777` (remove `_GO_RELEASE_RE`, `gaf_header`; import it)
- Modify: `src/methods_graph/biolean/bench/items.py:19, 134-154` (remove `read_release`; import it)
- Modify: `src/methods_graph/cli.py:1329, 1355`
- Test: `tests/test_biolean_store.py`, `tests/test_biolean_bench_items.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (in `methods_graph.biolean.store`):
  - `gaf_header(body: bytes) -> dict[str, str]` — unchanged behaviour, keys `date_generated`, `go_version`, `go_release`.
  - `read_release(store_dir: Path, *, obo="go-basic.obo", gaf="goa_human.gaf.gz") -> dict[str, str]` — unchanged behaviour.
  - `_read_bytes(path: Path) -> bytes` — file bytes, gunzipped when the suffix is `.gz`.
  - `base_digests(snapshot_dir: Path, *, obo=..., gaf=..., eco=...) -> dict[str, str]` — `{"obo", "gaf", "eco"}` → sha256 hex of `_read_bytes`.
  - `BaseLoad` dataclass: `terms: list[Term]`, `edges: list[Edge]`, `annotations: list[Annotation]`, `eco_map: dict[str, str]`, `primary_id: Callable[[str], str | None]`, `term: Callable[[str], Term | None]`, `digests: dict[str, str]`, `report: dict[str, dict[str, int]]`.
  - `load_base(snapshot_dir, *, obo, gaf, eco) -> BaseLoad`.
  - `load_store(snapshot_dir, *, obo, gaf, eco) -> tuple[StaticFactStore, dict[str, dict[str, Any]]]` — same behaviour as today; Task 7 adds the ledger keywords.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_biolean_store.py`:

```python
import hashlib
import gzip

from methods_graph.biolean import store as store_mod
from tests.biolean_fixture import FIX, RELEASE, copy_store


def test_read_release_and_gaf_header_live_in_store(tmp_path):
    store_dir = copy_store(tmp_path)
    assert store_mod.read_release(store_dir, gaf="goa_human.gaf") == RELEASE
    gaf = (FIX / "goa-mini.gaf").read_bytes()
    assert store_mod.gaf_header(gzip.compress(gaf)) == store_mod.gaf_header(gaf)
    assert store_mod.gaf_header(gaf)["date_generated"] == "2026-01-01"


def test_base_digests_hash_decompressed_content_so_gz_and_plain_agree(tmp_path):
    plain = copy_store(tmp_path / "plain")
    gz = copy_store(tmp_path / "gz")
    body = (gz / "goa_human.gaf").read_bytes()
    (gz / "goa_human.gaf.gz").write_bytes(gzip.compress(body, mtime=12345))
    (gz / "goa_human.gaf").unlink()
    a = store_mod.base_digests(plain, gaf="goa_human.gaf")
    b = store_mod.base_digests(gz, gaf="goa_human.gaf.gz")
    assert a == b
    assert a["gaf"] == hashlib.sha256(body).hexdigest()
    assert set(a) == {"obo", "gaf", "eco"} and all(len(v) == 64 for v in a.values())


def test_load_base_carries_digests_callables_and_the_same_report_as_load_store(tmp_path):
    store_dir = copy_store(tmp_path)
    base = store_mod.load_base(store_dir, obo="go-basic.obo", gaf="goa_human.gaf", eco="gaf-eco-mapping.txt")
    _, report = store_mod.load_store(store_dir, gaf="goa_human.gaf")
    assert base.report == report
    assert base.digests == store_mod.base_digests(store_dir, gaf="goa_human.gaf")
    assert base.primary_id("GO:0000011") == "GO:0000010" and base.primary_id("GO:0009999") is None
    assert base.term("GO:0000010").name == "C" and base.term("GO:0000011") is None
    assert base.eco_map["IDA"] == "ECO:0000314"
    assert len(base.annotations) == 24
```

Append to `tests/test_biolean_bench_items.py`:

```python
def test_bench_items_imports_release_identity_from_store_not_fetch():
    import inspect
    from methods_graph.biolean.bench import items as items_mod
    src = inspect.getsource(items_mod)
    assert "methods_graph.fetch" not in src
    assert items_mod.read_release is store_mod.read_release
```

with `from methods_graph.biolean import store as store_mod` added to that file's imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_store.py tests/test_biolean_bench_items.py -q`
Expected: FAIL with `AttributeError: module 'methods_graph.biolean.store' has no attribute 'read_release'` and the source-scan assertion.

- [ ] **Step 3: Move the code**

In `src/methods_graph/biolean/store.py`, replace the imports and `_read_text`/`load_store` with:

```python
from __future__ import annotations

import gzip
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from methods_graph.biolean.eco import parse_eco_mapping
from methods_graph.biolean.gaf import parse_gaf
from methods_graph.biolean.obo import parse_go_basic
from methods_graph.biolean.props import Annotation, Edge, Prop, Term
```

(keep `FactStore`, `_key`, `StaticFactStore`, `MaskedFactStore` exactly as they are) and after `MaskedFactStore`:

```python
# ---------------------------------------------------------------------------
# release identity and base identity
# ---------------------------------------------------------------------------

_GO_RELEASE_RE = re.compile(r"releases/(\d{4}-\d{2}-\d{2})")


def gaf_header(body: bytes) -> dict[str, str]:
    """``date-generated``, ``go-version`` and the release date inside it, from a GAF's ``!`` header.

    Accepts gzipped or plain bytes and reads only the header lines. Missing fields are ``""``.
    """
    fields = {"date_generated": "", "go_version": "", "go_release": ""}
    stream = gzip.GzipFile(fileobj=io.BytesIO(body)) if body[:2] == b"\x1f\x8b" else io.BytesIO(body)
    for raw in stream:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line.startswith("!"):
            break
        key, _, value = line[1:].partition(":")
        key, value = key.strip(), value.strip()
        if key == "date-generated" and not fields["date_generated"]:
            fields["date_generated"] = value
        elif key == "go-version" and not fields["go_version"]:
            fields["go_version"] = value
            match = _GO_RELEASE_RE.search(value)
            fields["go_release"] = match.group(1) if match else ""
    return fields


def read_release(store_dir: Path, *, obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz") -> dict[str, str]:
    """The pair's identity from the file headers: OBO ``data-version``, GAF ``date-generated``
    and ``go-version``. Read from the files, not ``snapshot.json``, which a hand-fetched
    snapshot lacks and which copies these same lines."""
    store_dir = Path(store_dir)
    data_version = ""
    with (store_dir / obo).open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("[Term]"):
                break
            if line.startswith("data-version:"):
                data_version = line.partition(":")[2].strip()
                break
    header = gaf_header((store_dir / gaf).read_bytes())
    return {"go_basic_data_version": data_version,
            "goa_date_generated": header["date_generated"],
            "goa_go_version": header["go_version"]}


def _read_bytes(path: Path) -> bytes:
    """The bytes ``load_base`` parses: gunzipped for ``.gz``. A gzip header carries an mtime and a
    name, so a base digest over the compressed file would change on recompression."""
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def base_digests(
    snapshot_dir: Path, *, obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz",
    eco: str = "gaf-eco-mapping.txt",
) -> dict[str, str]:
    """sha256 hex of each file's parsed content. Base identity for the ledger (spec §1)."""
    snapshot_dir = Path(snapshot_dir)
    return {name: hashlib.sha256(_read_bytes(snapshot_dir / fname)).hexdigest()
            for name, fname in (("obo", obo), ("gaf", gaf), ("eco", eco))}


@dataclass
class BaseLoad:
    """The three parsed files plus what the ledger needs to check a row against them."""
    terms: list[Term]
    edges: list[Edge]
    annotations: list[Annotation]
    eco_map: dict[str, str]
    primary_id: Callable[[str], str | None]
    term: Callable[[str], Term | None]
    digests: dict[str, str]
    report: dict[str, dict[str, int]]


def load_base(
    snapshot_dir: Path, *, obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz",
    eco: str = "gaf-eco-mapping.txt",
) -> BaseLoad:
    """Read the three files once, hashing the bytes that are parsed. Raises FileNotFoundError."""
    snapshot_dir = Path(snapshot_dir)
    raw = {name: _read_bytes(snapshot_dir / fname) for name, fname in (("obo", obo), ("gaf", gaf), ("eco", eco))}
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()}
    terms, edges, obo_report = parse_go_basic(raw["obo"].decode("utf-8"))
    eco_map, eco_report = parse_eco_mapping(raw["eco"].decode("utf-8"))
    by_id = {t.id: t for t in terms}
    alt = {a: t.id for t in terms for a in t.alt_ids}

    def primary_id(go_id: str) -> str | None:
        return go_id if go_id in by_id else alt.get(go_id)

    annotations, gaf_report = parse_gaf(raw["gaf"].decode("utf-8").splitlines(), eco_map, primary_id, by_id.get)
    return BaseLoad(terms, edges, annotations, eco_map, primary_id, by_id.get, digests,
                    {"obo": obo_report, "eco": eco_report, "gaf": gaf_report})


def load_store(
    snapshot_dir: Path,
    *,
    obo: str = "go-basic.obo",
    gaf: str = "goa_human.gaf.gz",
    eco: str = "gaf-eco-mapping.txt",
) -> tuple[StaticFactStore, dict[str, dict[str, Any]]]:
    """Read the three files and build the store. Raises FileNotFoundError for a missing file."""
    base = load_base(snapshot_dir, obo=obo, gaf=gaf, eco=eco)
    return StaticFactStore(base.terms, base.edges, base.annotations), base.report
```

In `src/methods_graph/fetch.py`: delete `_GO_RELEASE_RE` (line 741) and the whole `gaf_header` function (lines 752–773); add `from methods_graph.biolean.store import gaf_header` after the `yaml` import (keep the name importable as `fetch.gaf_header`, which `tests/test_biolean_fetch.py` and `fetch_goa_human` use). Delete the now-unused `import io` only if nothing else in `fetch.py` uses `io` (`grep -n "io\." src/methods_graph/fetch.py`).

In `src/methods_graph/biolean/bench/items.py`: delete `from methods_graph.fetch import gaf_header` (line 19), delete the `read_release` function and its section comment (lines 134–154), and change the store import to `from methods_graph.biolean.store import FactStore, MaskedFactStore, read_release` (the re-export keeps `from methods_graph.biolean.bench.items import read_release` working for the existing tests and scale test).

In `src/methods_graph/cli.py:1329`: `from methods_graph.biolean.bench.items import build_items, load_items` and add `from methods_graph.biolean.store import read_release` beside it (line 1355 is unchanged).

- [ ] **Step 4: Run the whole suite**

Run: `$PYTEST -q`
Expected: everything passes (1013 passed, 1 skipped locally; the new tests included). `tests/test_biolean_fetch.py::test_gaf_header_reads_gzipped_and_plain_and_extracts_the_release` still passes through the re-export.

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/biolean/store.py src/methods_graph/fetch.py src/methods_graph/biolean/bench/items.py src/methods_graph/cli.py tests/test_biolean_store.py tests/test_biolean_bench_items.py
git commit -m "refactor(biolean): release identity and base digests live in store.py

read_release and gaf_header move out of fetch.py and bench/items.py so the
ledger verifier (spec §0.1) imports no network or bench module. load_base
factors the file reads out of load_store and hashes the parsed bytes.

mutation checked: hashing the .gz bytes instead of the decompressed bytes
fails test_base_digests_hash_decompressed_content_so_gz_and_plain_agree."
```

---

### Task 2: `GAF_COLUMNS`, public `check_term`, extracted `check_qualifier_aspect`

**Files:**
- Modify: `src/methods_graph/biolean/gaf.py:14-15`
- Modify: `src/methods_graph/biolean/kernel.py:227-268` (`_check_term`, `_check_prop`) and its two other callers (`kernel.py:400`, `:436`)
- Test: `tests/test_biolean_gaf.py`, `tests/test_biolean_kernel.py`

**Interfaces:**
- Produces:
  - `gaf.GAF_COLUMNS: tuple[str, ...]` — the 17 GAF 2.2 column names, in order: `db, db_object_id, db_object_symbol, qualifier, go_id, db_reference, evidence_code, with_from, aspect, db_object_name, db_object_synonym, db_object_type, taxon, date, assigned_by, annotation_extension, gene_product_form_id`.
  - `kernel.check_term(term_id: str, store: FactStore, step: str | None, position: int = -1) -> list[Error]` — today's `_check_term`, unchanged: `[]` for a live primary id; one `ALT_ID_IN_KERNEL` (`expected` = the primary), `UNKNOWN_TERM`, or `OBSOLETE_TERM` (`expected = {"replaced_by": [...], "consider": [...]}`).
  - `kernel.check_qualifier_aspect(qualifier: str, term_id: str, store: FactStore, step: str | None = None, position: int = -1) -> list[Error]` — `UNKNOWN_QUALIFIER` (`expected` the 13 sorted, `actual` the qualifier), or `QUALIFIER_ASPECT_MISMATCH` (`expected` the qualifier's aspect letter, `actual` the term's) when the term is live and its namespace's aspect differs; `[]` when the term is unknown or obsolete.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_biolean_gaf.py`:

```python
from methods_graph.biolean.gaf import GAF_COLUMNS, _COLUMNS


def test_gaf_columns_are_the_seventeen_gaf22_names_in_order():
    assert GAF_COLUMNS == (
        "db", "db_object_id", "db_object_symbol", "qualifier", "go_id", "db_reference",
        "evidence_code", "with_from", "aspect", "db_object_name", "db_object_synonym",
        "db_object_type", "taxon", "date", "assigned_by", "annotation_extension",
        "gene_product_form_id")
    assert _COLUMNS == len(GAF_COLUMNS) == 17
```

Append to `tests/test_biolean_kernel.py`:

```python
from methods_graph.biolean import kernel as kernel_mod
from methods_graph.biolean.kernel import check_qualifier_aspect, check_term


def test_check_term_is_public_and_the_private_name_is_gone():
    assert not hasattr(kernel_mod, "_check_term")
    assert check_term(C, STORE, None) == []
    assert [e.code for e in check_term(ALT, STORE, None)] == [Code.ALT_ID_IN_KERNEL]
    assert [e.code for e in check_term(OBS, STORE, None)] == [Code.OBSOLETE_TERM]
    assert check_term(OBS, STORE, None)[0].expected == {"replaced_by": [C], "consider": [D]}
    assert [e.code for e in check_term("GO:0009999", STORE, None)] == [Code.UNKNOWN_TERM]


def test_check_qualifier_aspect_is_the_prop_check_minus_subject_and_taxon():
    # Legal pair: nothing. Unknown qualifier: the 13. Mismatch: aspect letters.
    assert check_qualifier_aspect("involved_in", C, STORE) == []
    [e] = check_qualifier_aspect("binds", C, STORE)
    assert e.code == Code.UNKNOWN_QUALIFIER and e.expected == sorted(kernel_mod.QUALIFIER_ASPECT) and e.actual == "binds"
    [e] = check_qualifier_aspect("enables", C, STORE)
    assert e.code == Code.QUALIFIER_ASPECT_MISMATCH and (e.expected, e.actual) == ("F", "P")
    # Unknown or obsolete term: the qualifier is still checked, the aspect is not.
    assert check_qualifier_aspect("enables", "GO:0009999", STORE) == []
    assert check_qualifier_aspect("enables", OBS, STORE) == []
    assert [e.code for e in check_qualifier_aspect("binds", OBS, STORE)] == [Code.UNKNOWN_QUALIFIER]
    # It is what _check_prop emits for these two codes, so the extraction changed nothing.
    for q, t in (("binds", C), ("enables", C), ("involved_in", C), ("enables", OBS)):
        via_prop = [e.code for e in kernel_mod._check_prop(Prop(P1, q, t, TAX, False), STORE, "s", 0)
                    if e.code in (Code.UNKNOWN_QUALIFIER, Code.QUALIFIER_ASPECT_MISMATCH)]
        assert via_prop == [e.code for e in check_qualifier_aspect(q, t, STORE, "s", 0)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_gaf.py tests/test_biolean_kernel.py -q`
Expected: FAIL with `ImportError: cannot import name 'GAF_COLUMNS'` and `cannot import name 'check_qualifier_aspect'`.

- [ ] **Step 3: Implement**

In `src/methods_graph/biolean/gaf.py` replace `_COLUMNS = 17` with:

```python
# GAF 2.2 column names, in order. The ledger's object-form `--fact` uses them as keys and
# `LEDGER_BAD_COLUMNS` lists them (spec §2 step 1, §7).
GAF_COLUMNS: tuple[str, ...] = (
    "db", "db_object_id", "db_object_symbol", "qualifier", "go_id", "db_reference",
    "evidence_code", "with_from", "aspect", "db_object_name", "db_object_synonym",
    "db_object_type", "taxon", "date", "assigned_by", "annotation_extension",
    "gene_product_form_id",
)
_COLUMNS = len(GAF_COLUMNS)
```

In `src/methods_graph/biolean/kernel.py`, rename `_check_term` to `check_term` (definition and the three call sites: inside `_check_prop`, and the two in `check()` at the edge-endpoint loop), and replace the qualifier block of `_check_prop` with a call to the new function:

```python
def check_term(term_id: str, store: FactStore, step: str | None, position: int = -1) -> list[Error]:
    """Live primary id: []. Otherwise exactly one of ALT_ID_IN_KERNEL, UNKNOWN_TERM, OBSOLETE_TERM.
    Public because the ledger's append check reuses it (spec §2 steps 3-4)."""
    term = store.term(term_id)
    if term is None:
        primary = store.primary_id(term_id)
        if primary is not None:
            return [Error(Code.ALT_ID_IN_KERNEL, f"{term_id} is an alt_id of {primary}",
                          step=step, position=position, expected=primary, actual=term_id)]
        return [Error(Code.UNKNOWN_TERM, f"unknown term {term_id}", step=step, position=position,
                      actual=term_id)]
    if term.obsolete:
        return [Error(Code.OBSOLETE_TERM, f"{term_id} is obsolete", step=step, position=position,
                      actual=term_id,
                      expected={"replaced_by": list(term.replaced_by),
                                "consider": list(term.consider)})]
    return []


def check_qualifier_aspect(
    qualifier: str, term_id: str, store: FactStore, step: str | None = None, position: int = -1,
) -> list[Error]:
    """UNKNOWN_QUALIFIER, or QUALIFIER_ASPECT_MISMATCH when the term is live and its namespace's
    aspect differs from the qualifier's. Nothing when the term is unknown or obsolete: the
    term check reports those. Extracted from ``_check_prop`` for the ledger (spec §2 step 4)."""
    if qualifier not in QUALIFIER_ASPECT:
        return [Error(Code.UNKNOWN_QUALIFIER, f"unknown qualifier {qualifier!r}",
                      step=step, position=position, expected=sorted(QUALIFIER_ASPECT),
                      actual=qualifier)]
    term = store.term(term_id)
    if term is not None and not term.obsolete:
        aspect = NAMESPACE_ASPECT.get(term.namespace)
        wanted = QUALIFIER_ASPECT[qualifier]
        if aspect != wanted:
            return [Error(
                Code.QUALIFIER_ASPECT_MISMATCH,
                f"{qualifier} is a {wanted}-aspect qualifier; {term_id} is {term.namespace}",
                step=step, position=position, expected=wanted, actual=aspect)]
    return []


def _check_prop(prop: Prop, store: FactStore, step: str | None, position: int = -1) -> list[Error]:
    errs: list[Error] = []
    if not store.subject_exists(prop.subject):
        errs.append(Error(Code.UNKNOWN_SUBJECT, f"unknown subject {prop.subject}", step=step,
                          position=position, actual=prop.subject,
                          expected=list(store.subject_for_symbol(prop.subject))))
    errs.extend(check_term(prop.term, store, step, position))
    if not TAXON_RE.match(prop.taxon):
        errs.append(Error(Code.MALFORMED, f"taxon must be NCBITaxon:<digits>, got {prop.taxon!r}",
                          step=step, position=position, actual=prop.taxon))
    errs.extend(check_qualifier_aspect(prop.qualifier, prop.term, store, step, position))
    return errs
```

The error order inside `_check_prop` is unchanged (subject, term, taxon, qualifier), so `tests/fixtures/biolean/golden_verdict.json` still matches.

- [ ] **Step 4: Run the kernel, tactics, elaborate, CLI and bench tests**

Run: `$PYTEST tests/test_biolean_kernel.py tests/test_biolean_gaf.py tests/test_biolean_tactics.py tests/test_biolean_elaborate.py tests/test_biolean_cli.py tests/test_biolean_bench_score.py -q`
Expected: all pass, `test_verdict_matches_committed_golden` included.

Mutation check: in `check_qualifier_aspect`, drop the `not term.obsolete` guard. `test_check_qualifier_aspect_is_the_prop_check_minus_subject_and_taxon` fails on the `(enables, OBS)` case (the obsolete term's namespace is `biological_process`, so a mismatch appears). Restore.

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/biolean/gaf.py src/methods_graph/biolean/kernel.py tests/test_biolean_gaf.py tests/test_biolean_kernel.py
git commit -m "feat(biolean): GAF_COLUMNS; kernel exposes check_term and check_qualifier_aspect

The ledger's append check reuses the kernel's term and qualifier/aspect checks
without _check_prop's subject and taxon checks (spec §2). The extraction is
behaviour-preserving: the golden verdict is unchanged.

mutation checked: dropping the obsolete guard in check_qualifier_aspect fails
the extraction test on (enables, GO:0000110)."
```

---

### Task 3: `ed25519.py`, verify-only, pinned by RFC 8032 §7.1

**Files:**
- Create: `src/methods_graph/biolean/ed25519.py`
- Create: `tests/fixtures/biolean/ledger/rfc8032-ed25519.json` (already written by the planner from the RFC text; step 1 checks it)
- Test: `tests/test_biolean_ed25519.py`

**Interfaces:**
- Produces:
  - `ed25519.verify(public_key: bytes, message: bytes, signature: bytes) -> bool` — RFC 8032 §5.1.7, cofactorless `[S]B = R + [k]A`, with `S < L` and canonical point encodings required (stricter than OpenSSH). Never raises for bad lengths; returns `False`.
  - `ed25519.is_small_order(public_key: bytes) -> bool` — `True` when the 32 bytes do not decode, or decode to a point `A` with `[8]A = identity`.
  - `ed25519.P`, `ed25519.L` (module ints) for tests.

The prototype of this exact module was run by the planner against the five vectors, 320 single-bit flips, `S + L`, the non-canonical encodings and real `ssh-keygen` signatures: 3 ms per verification, all checks green. Any later change still needs review against RFC 8032 §5.1.3 and §5.1.7 (spec, Risks).

- [ ] **Step 1: Check the vectors fixture**

`tests/fixtures/biolean/ledger/rfc8032-ed25519.json` holds the five §7.1 Ed25519 vectors as `[{"name", "public_key", "message", "signature"}]`, hex strings, extracted from `https://www.rfc-editor.org/rfc/rfc8032.txt` lines 1295–1499. Verify it is intact before relying on it (no network: the file is already present):

Run: `.venv/bin/python -c "import json,hashlib; v=json.load(open('tests/fixtures/biolean/ledger/rfc8032-ed25519.json')); print([(x['name'], len(x['message'])//2, len(x['public_key']), len(x['signature'])) for x in v])"`
Expected: `[('1', 0, 64, 128), ('2', 1, 64, 128), ('3', 2, 64, 128), ('1024', 1023, 64, 128), ('SHA(abc)', 64, 64, 128)]`

If the file is missing, recreate it from the RFC text with this extraction (one-off, needs network for the download; the JSON it writes is what gets committed):

```python
# scratch/extract_vectors.py — run once: python extract_vectors.py rfc8032.txt > rfc8032-ed25519.json
import json, re, sys
text = open(sys.argv[1]).read()
start = text.index("7.1.  Test Vectors for Ed25519\n")
end = text.index("7.2.  Test Vectors for Ed25519ctx", start)
lines = [l for l in text[start:end].splitlines()
         if not l.startswith("Josefsson") and not l.startswith("RFC 8032") and l.strip() != "\f"]
out = []
for b in re.split(r"-----TEST ", "\n".join(lines))[1:]:
    name = b.splitlines()[0].strip()
    def grab(label):
        m = re.search(label + r"[^\n]*\n((?:\s*[0-9a-f]*\n)*)", b)
        return "".join(m.group(1).split()) if m else ""
    out.append({"name": name, "public_key": grab("PUBLIC KEY:"),
                "message": grab(r"MESSAGE \(length \d+ bytes?\):"), "signature": grab("SIGNATURE:")})
print(json.dumps(out, indent=1))
```

- [ ] **Step 2: Write the failing tests**

`tests/test_biolean_ed25519.py`:

```python
"""RFC 8032 §5.1.7 verification, pinned by the §7.1 vectors and by what must fail."""
import json
from pathlib import Path

from methods_graph.biolean.ed25519 import L, P, is_small_order, verify

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "biolean" / "ledger" / "rfc8032-ed25519.json").read_text())

# The eight encodings whose point A satisfies [8]A = identity (enumerated by brute force from a
# torsion generator during planning; the two with y = 0 and the identity are the well-known ones).
SMALL_ORDER = [
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000080",
    "0100000000000000000000000000000000000000000000000000000000000000",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
]


def _v(v):
    return bytes.fromhex(v["public_key"]), bytes.fromhex(v["message"]), bytes.fromhex(v["signature"])


def test_rfc8032_vectors_verify():
    assert [v["name"] for v in VECTORS] == ["1", "2", "3", "1024", "SHA(abc)"]
    for v in VECTORS:
        pk, msg, sig = _v(v)
        assert verify(pk, msg, sig), v["name"]


def test_rfc8032_vector_with_one_bit_flipped_fails():
    # Break: `return True` after the length checks; or comparing only the y coordinate.
    for v in VECTORS:
        pk, msg, sig = _v(v)
        for i in range(64):
            bad = bytearray(sig)
            bad[i] ^= 1
            assert not verify(pk, msg, bytes(bad)), (v["name"], i)
        bad_pk = bytearray(pk)
        bad_pk[0] ^= 1
        assert not verify(bytes(bad_pk), msg, sig)
        assert not verify(pk, msg + b"\x00", sig)
        # Break: `_equal` comparing only y. (R, L - S) puts -[S]B against R + [k]A: same y,
        # opposite x, and a second valid signature for the same message if x is ignored.
        s = int.from_bytes(sig[32:], "little")
        assert not verify(pk, msg, sig[:32] + (L - s).to_bytes(32, "little")), v["name"]


def test_non_canonical_s_rejected():
    # Break: drop the `s >= L` check. S + L is the same scalar mod L, so the equation still holds.
    for v in VECTORS:
        pk, msg, sig = _v(v)
        s = int.from_bytes(sig[32:], "little") + L
        assert s < 2**256
        assert not verify(pk, msg, sig[:32] + s.to_bytes(32, "little")), v["name"]


def test_non_canonical_point_rejected():
    # Break: drop the `y >= P` rejection; or drop the `x == 0 and x_0 == 1` rejection. Under
    # either, the encoding below decodes to the identity (mod p), so the identity forgery
    # (R = identity, S = 0) would verify with it as A or as R.
    pk, msg, sig = _v(VECTORS[0])
    identity = bytes.fromhex(SMALL_ORDER[2])
    forged = identity + bytes(32)
    assert verify(identity, b"m", forged)                       # the forgery this test guards against
    y_plus = (P + 1).to_bytes(32, "little")                     # y = p + 1, sign bit clear
    one_with_sign = (1 | (1 << 255)).to_bytes(32, "little")     # y = 1, x = 0, x_0 = 1
    for bad in (y_plus, one_with_sign):
        assert is_small_order(bad)                              # does not decode at all
        assert not verify(bad, msg, sig)
        assert not verify(pk, msg, bad + sig[32:])
        assert not verify(bad, b"m", forged), bad.hex()               # as A
        assert not verify(identity, b"m", bad + bytes(32)), bad.hex()  # as R
    # bit 255 is the sign of x, not an unused bit: setting it on a valid key gives a different key
    flipped = bytearray(pk)
    flipped[31] ^= 0x80
    assert not verify(bytes(flipped), msg, sig)


def test_small_order_keys_are_detected_and_the_identity_key_forges():
    # Break: `is_small_order` checking [4]A or [2]A instead of [8]A misses the order-8 points.
    for enc in SMALL_ORDER:
        assert is_small_order(bytes.fromhex(enc)), enc
    for v in VECTORS:
        assert not is_small_order(bytes.fromhex(v["public_key"]))
    # Why the list matters: under the identity key, R = identity and S = 0 verifies every message.
    identity = bytes.fromhex(SMALL_ORDER[2])
    forged = identity + bytes(32)
    assert verify(identity, b"one message", forged) and verify(identity, b"another", forged)


def test_wrong_lengths_fail_without_raising():
    pk, msg, sig = _v(VECTORS[1])
    assert not verify(pk[:31], msg, sig)
    assert not verify(pk, msg, sig[:63])
    assert not verify(pk + b"\x00", msg, sig)
    assert is_small_order(b"")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_ed25519.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.ed25519'`.

- [ ] **Step 4: Implement `ed25519.py`**

`src/methods_graph/biolean/ed25519.py`:

```python
"""Ed25519 verification, RFC 8032 §5.1.7, over the stdlib. Verify-only: no signing code.

Field arithmetic mod p = 2^255 - 19 on plain ints; extended twisted-Edwards coordinates
(X, Y, Z, T) with the RFC's a = -1 addition law (§5.1.4); point decoding as §5.1.3, rejecting
a non-canonical y (y >= p) and x = 0 with x_0 = 1; cofactorless ``[S]B = R + [k]A`` with
``S < L``. OpenSSH accepts S + L; this module does not, which is why an entry's ``sig`` is
immutable (spec §1). Pinned by the §7.1 vectors and the mutations in tests/test_biolean_ed25519.py.
Any change here needs review against §5.1.3 and §5.1.7 (spec, Risks).
"""
from __future__ import annotations

import hashlib

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P
_SQRT_M1 = pow(2, (P - 1) // 4, P)          # sqrt(-1) mod p

_Point = tuple[int, int, int, int]          # (X, Y, Z, T): x = X/Z, y = Y/Z, x*y = T/Z
_IDENTITY: _Point = (0, 1, 1, 0)


def _decode_point(encoded: bytes) -> _Point | None:
    """§5.1.3. ``None`` for a non-canonical or off-curve encoding."""
    if len(encoded) != 32:
        return None
    y = int.from_bytes(encoded, "little")
    x_0 = y >> 255
    y &= (1 << 255) - 1
    if y >= P:
        return None
    y2 = y * y % P
    u = (y2 - 1) % P
    v = (D * y2 + 1) % P
    x = pow(u * pow(v, P - 2, P), (P + 3) // 8, P)
    vx2 = v * x * x % P
    if vx2 == u:
        pass
    elif vx2 == (-u) % P:
        x = x * _SQRT_M1 % P
    else:
        return None
    if x == 0 and x_0 == 1:
        return None
    if (x & 1) != x_0:
        x = P - x
    return (x, y, 1, x * y % P)


def _add(p: _Point, q: _Point) -> _Point:
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = 2 * t1 * t2 * D % P
    d = 2 * z1 * z2 % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(k: int, p: _Point) -> _Point:
    q = _IDENTITY
    while k:
        if k & 1:
            q = _add(q, p)
        p = _add(p, p)
        k >>= 1
    return q


def _equal(p: _Point, q: _Point) -> bool:
    x1, y1, z1, _ = p
    x2, y2, z2, _ = q
    return (x1 * z2 - x2 * z1) % P == 0 and (y1 * z2 - y2 * z1) % P == 0


_B_Y = 4 * pow(5, P - 2, P) % P
_B = _decode_point(_B_Y.to_bytes(32, "little"))     # sign bit clear: B has even x
if _B is None:
    raise RuntimeError("ed25519 base point failed to decode")


def is_small_order(public_key: bytes) -> bool:
    """``True`` when the encoding does not decode, or decodes to A with [8]A = identity.

    Under such a key, cofactorless verification accepts R = identity, S = 0 for every message
    (and OpenSSH accepts it too), so ``allowed_signers`` refuses it at parse (spec §4).
    """
    a = _decode_point(public_key)
    if a is None:
        return True
    return _equal(_mul(8, a), _IDENTITY)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 §5.1.7 with S < L and canonical encodings required. Never raises on bad input."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a = _decode_point(public_key)
    r = _decode_point(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= L:
        return False
    k = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % L
    return _equal(_mul(s, _B), _add(r, _mul(k, a)))
```

- [ ] **Step 5: Run the tests**

Run: `$PYTEST tests/test_biolean_ed25519.py -q`
Expected: 6 passed in about 3 s.

Mutation checks (each restored before the next): (a) `return True` right after the two length checks at the top of `verify` (always accept well-formed input): the bit-flip, non-canonical-S and non-canonical-point tests fail; the vectors test and the small-order test only assert acceptance, so they cannot see it. (b) delete `if s >= L: return False`: `test_non_canonical_s_rejected` fails. (c) delete `if y >= P: return None`: `test_non_canonical_point_rejected` fails. (d) `_mul(4, a)` in `is_small_order`: the small-order test fails on the four order-8 encodings. (e) `_equal` → `return (y1 * z2 - y2 * z1) % P == 0`: `test_rfc8032_vector_with_one_bit_flipped_fails` fails on `(R, L - S)` for every vector (a y-only comparison makes every signature malleable); the identity-forgery lines of `test_non_canonical_point_rejected` are what (c) and the `x_0` deletion fail on.

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/biolean/ed25519.py tests/test_biolean_ed25519.py tests/fixtures/biolean/ledger/rfc8032-ed25519.json
git commit -m "feat(biolean): stdlib Ed25519 verification pinned by RFC 8032 vectors

Verify-only, cofactorless, S < L, canonical encodings required. is_small_order
backs the allowed_signers refusal of the eight torsion encodings.

mutation checked: dropping the S < L check fails test_non_canonical_s_rejected;
[4]A in is_small_order misses the order-8 points; a y-only point equality
accepts (R, L - S); dropping either canonical-encoding check admits the
identity forgery through a non-canonical key."
```

---

### Task 4: `sshsig.py`: signature blobs, `allowed_signers`, key digests; the fixture keys

**Files:**
- Create: `src/methods_graph/biolean/sshsig.py`
- Create (already written by the planner; step 1 checks them): `tests/fixtures/biolean/ledger/keys/{a,a.pub,b,b.pub}`, `tests/fixtures/biolean/ledger/known/{message-one.txt,message-two.txt,a-one.sig,a-two.sig,a-one-other-namespace.sig,b-one.sig}`
- Test: `tests/test_biolean_sshsig.py`

**Interfaces:**
- Consumes: `ed25519.verify`, `ed25519.is_small_order`.
- Produces (all in `methods_graph.biolean.sshsig`):
  - constants `NAMESPACE = "biolean-ledger"`, `KEY_TYPE = "ssh-ed25519"`, `FIXTURE_KEY_DIGESTS: frozenset[str]` (the two fixture keys' full digests).
  - `class SshsigError(ValueError)`; `class AllowedSignersError(ValueError)` with `.line: int`, `.reason: str`.
  - `parse_key_blob(blob: bytes) -> bytes` — the 32-byte key of an `ssh-ed25519` blob.
  - `key_digest(blob) -> str` (64 hex), `key16(blob) -> str` (16 hex), `fingerprint(blob) -> str` (`SHA256:<unpadded base64>`).
  - `parse_public_key_line(text: str) -> tuple[bytes, str]` — `(blob, comment)`; refuses every type but `ssh-ed25519`.
  - `Sshsig` dataclass: `public_key_blob`, `public_key`, `namespace`, `hash_algorithm`, `signature`.
  - `parse_sshsig(sig: str) -> Sshsig` — structural check of a `sig` value, including canonical base64.
  - `signed_data(message: bytes, namespace: str = NAMESPACE) -> bytes`.
  - `verify_sshsig(sig: str, message: bytes, *, namespace: str = NAMESPACE) -> bytes` — the signer's public-key blob, or `SshsigError`.
  - `dearmor(stdout: bytes) -> str`, `armor(sig: str) -> str`.
  - `Signer` dataclass: `line`, `principals: tuple[str, ...]`, `namespaces: tuple[str, ...] | None`, `blob: bytes`; properties `digest`, `key16`; `permits(namespace) -> bool`.
  - `parse_allowed_signers(text: str) -> list[Signer]`, `find_signer(signers, blob) -> Signer | None`, `allowed_signers_line(principal, blob, comment="") -> str`.

The fixture keys were generated once with `ssh-keygen -t ed25519 -N "" -C biolean-fixture-A -f a` (and B). They are trusted by nothing outside these fixtures. Their digests, from `ssh-keygen -lf` and `sha256` over the blob:

| Key | `key16` | full digest (`by` without `sha256:`) | `ssh-keygen -lf` |
|---|---|---|---|
| A | `1438014318807ad1` | `1438014318807ad1a74d1943c05793434d3cbd11009797a646bbc3cd68c7c51e` | `SHA256:FDgBQxiAetGnTRlDwFeTQ008vREAl5emRrvDzWjHxR4` |
| B | `778b5c6aae736dad` | `778b5c6aae736dad91e838b21ac186bf8590c64cf94e73db1c27c69c53de34d0` | `SHA256:d4tcaq5zba2R6DiyGsGGv4WQxkz5TnPbHCfGnFPeNNA` |

- [ ] **Step 1: Check the key and signature fixtures**

Run: `ls -la tests/fixtures/biolean/ledger/keys tests/fixtures/biolean/ledger/known`
Expected: `a` and `b` (411 bytes, mode 600), `a.pub`, `b.pub` (99 bytes), the two messages (35 bytes each), four `.sig` files (302–310 bytes).

Run: `.venv/bin/python -c "import base64,hashlib; [print(n, hashlib.sha256(base64.b64decode(open(f'tests/fixtures/biolean/ledger/keys/{n}.pub').read().split()[1])).hexdigest()) for n in 'ab']"`
Expected: the two full digests in the table above.

If any file is missing, recreate them all (one-off, needs `ssh-keygen`, no network). The keys must be exactly these files, since the digests are pinned in code and tests:

Note: the two private keys quoted below are test-only keys generated for these fixtures. They have never been used for anything else, and `init` refuses them.

`keys/a`:
```
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACDGwM17PlOwOUh2jp+qjc+rtJE/VLpviJt2ti1qZTl8gAAAAJi5BnpYuQZ6
WAAAAAtzc2gtZWQyNTUxOQAAACDGwM17PlOwOUh2jp+qjc+rtJE/VLpviJt2ti1qZTl8gA
AAAEAjTDSOa2jo0DpOPObKY7jVfJSG2mWyyG+aJGSuirDTgsbAzXs+U7A5SHaOn6qNz6u0
kT9Uum+Im3a2LWplOXyAAAAAEWJpb2xlYW4tZml4dHVyZS1BAQIDBA==
-----END OPENSSH PRIVATE KEY-----
```
`keys/a.pub`: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMbAzXs+U7A5SHaOn6qNz6u0kT9Uum+Im3a2LWplOXyA biolean-fixture-A`

`keys/b`:
```
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACAT3zjOQaRC7aBI2/xJk0JB5IhU5RwvTzdtXgd5pqpXTQAAAJgsXfk3LF35
NwAAAAtzc2gtZWQyNTUxOQAAACAT3zjOQaRC7aBI2/xJk0JB5IhU5RwvTzdtXgd5pqpXTQ
AAAED4XDRM6kBZdHyVIYDnjLqCGKuT8GbrZvzDW/P5Ch/nahPfOM5BpELtoEjb/EmTQkHk
iFTlHC9PN21eB3mmqldNAAAAEWJpb2xlYW4tZml4dHVyZS1CAQIDBA==
-----END OPENSSH PRIVATE KEY-----
```
`keys/b.pub`: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBPfOM5BpELtoEjb/EmTQkHkiFTlHC9PN21eB3mmqldN biolean-fixture-B`

Then `chmod 600 keys/a keys/b` (ssh-keygen refuses a 0644 private key: "Permissions 0644 ... are too open"), write `known/message-one.txt` as the bytes `biolean ledger fixture message one\n` and `known/message-two.txt` as `biolean ledger fixture message two\n`, and sign (stdout is the armor; "Signing data on standard input" goes to stderr):

```
ssh-keygen -Y sign -f keys/a -n biolean-ledger < known/message-one.txt > known/a-one.sig
ssh-keygen -Y sign -f keys/a -n biolean-ledger < known/message-two.txt > known/a-two.sig
ssh-keygen -Y sign -f keys/a -n other-ns       < known/message-one.txt > known/a-one-other-namespace.sig
ssh-keygen -Y sign -f keys/b -n biolean-ledger < known/message-one.txt > known/b-one.sig
```

Ed25519 and sshsig carry no randomness, so these reproduce byte for byte (`sha256sum known/a-one.sig` = `6fc0a86a67969b20f2284761961a5577fccbd2fecb326adfc5c2289240b74116`). `known/a-one.sig` is:

```
-----BEGIN SSH SIGNATURE-----
U1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTkAAAAgxsDNez5TsDlIdo6fqo3Pq7SRP1
S6b4ibdrYtamU5fIAAAAAOYmlvbGVhbi1sZWRnZXIAAAAAAAAABnNoYTUxMgAAAFMAAAAL
c3NoLWVkMjU1MTkAAABABXGIk+lgyzvqe9jck8kOAv5C+t55jdr6J3KnCUkpqnu/Cgs5fk
czRSPtXYQnHOnz/qDr3IZLzYigS4qe/yFDDg==
-----END SSH SIGNATURE-----
```

- [ ] **Step 2: Write the failing tests**

`tests/test_biolean_sshsig.py`:

```python
"""sshsig parsing and verification against real ssh-keygen output; the allowed_signers reader."""
import base64
import struct
from pathlib import Path

import pytest

from methods_graph.biolean import sshsig
from methods_graph.biolean.sshsig import (
    FIXTURE_KEY_DIGESTS, NAMESPACE, AllowedSignersError, SshsigError, allowed_signers_line, armor,
    dearmor, find_signer, fingerprint, key16, key_digest, parse_allowed_signers, parse_public_key_line,
    parse_sshsig, verify_sshsig)
from tests.test_biolean_ed25519 import SMALL_ORDER

LFIX = Path(__file__).parent / "fixtures" / "biolean" / "ledger"
A_PUB = (LFIX / "keys" / "a.pub").read_text()
B_PUB = (LFIX / "keys" / "b.pub").read_text()
A_BLOB, _ = parse_public_key_line(A_PUB)
B_BLOB, _ = parse_public_key_line(B_PUB)
ONE = (LFIX / "known" / "message-one.txt").read_bytes()
TWO = (LFIX / "known" / "message-two.txt").read_bytes()


def _sig(name):
    return dearmor((LFIX / "known" / name).read_bytes())


def _pack(b):
    return struct.pack(">I", len(b)) + b


def _rebuild(sig, *, version=1, pk=None, namespace=None, reserved=b"", halg=b"sha512", signature=None, trailing=b""):
    """Re-encode a parsed sshsig with one field changed."""
    p = parse_sshsig(sig)
    pk_blob = pk if pk is not None else p.public_key_blob
    ns = (namespace if namespace is not None else p.namespace).encode()
    sig_str = signature if signature is not None else _pack(b"ssh-ed25519") + _pack(p.signature)
    blob = (b"SSHSIG" + struct.pack(">I", version) + _pack(pk_blob) + _pack(ns) + _pack(reserved)
            + _pack(halg) + _pack(sig_str) + trailing)
    return base64.b64encode(blob).decode()


def test_real_ssh_keygen_signature_verifies():
    assert verify_sshsig(_sig("a-one.sig"), ONE) == A_BLOB
    assert verify_sshsig(_sig("a-two.sig"), TWO) == A_BLOB
    assert verify_sshsig(_sig("b-one.sig"), ONE) == B_BLOB


def test_wrong_namespace_fails():
    with pytest.raises(SshsigError, match="namespace"):
        verify_sshsig(_sig("a-one-other-namespace.sig"), ONE)
    # and the same signature verifies in the namespace it was made for
    assert verify_sshsig(_sig("a-one-other-namespace.sig"), ONE, namespace="other-ns") == A_BLOB


def test_wrong_message_fails():
    with pytest.raises(SshsigError, match="does not verify"):
        verify_sshsig(_sig("a-one.sig"), TWO)


def test_sshsig_fields_are_enforced():
    # Break: skip any one of these checks; the matching case then verifies or raises elsewhere.
    sig = _sig("a-one.sig")
    p = parse_sshsig(sig)
    assert (p.namespace, p.hash_algorithm, len(p.signature), len(p.public_key)) == (NAMESPACE, "sha512", 64, 32)
    cases = {
        "version": _rebuild(sig, version=2),
        "key type": _rebuild(sig, pk=_pack(b"ssh-rsa") + _pack(p.public_key)),
        "63 bytes": _rebuild(sig, signature=_pack(b"ssh-ed25519") + _pack(p.signature[:63])),
        "sha256": _rebuild(sig, halg=b"sha256"),
        "reserved": _rebuild(sig, reserved=b"x"),
        "trailing bytes": _rebuild(sig, trailing=b"\x00"),
        "trailing inside signature": _rebuild(sig, signature=_pack(b"ssh-ed25519") + _pack(p.signature) + b"\x00"),
        "armor": (LFIX / "known" / "a-one.sig").read_text(),
        "whitespace": sig[:10] + "\n" + sig[10:],
        "urlsafe": sig.replace("+", "-").replace("/", "_"),
        "empty": "",
        "non-canonical padding": sig[:-3] + ("h" if sig[-3] == "g" else "g") + "==",
    }
    for name, bad in cases.items():
        with pytest.raises(SshsigError):
            verify_sshsig(bad, ONE)
        # every refusal is structural: parse_sshsig itself raises, before any crypto
        with pytest.raises(SshsigError):
            parse_sshsig(bad)
    assert verify_sshsig(sig, ONE) == A_BLOB          # the unmodified value still passes


def test_dearmor_and_armor_round_trip():
    raw = (LFIX / "known" / "a-one.sig").read_bytes()
    sig = dearmor(raw)
    assert "\n" not in sig and sig.endswith("==")
    assert armor(sig) == raw.decode()
    with pytest.raises(SshsigError, match="armor"):
        dearmor(b"Signing data on standard input\n")


def test_public_key_digests_match_ssh_keygen_lf():
    assert key16(A_BLOB) == "1438014318807ad1" and key16(B_BLOB) == "778b5c6aae736dad"
    assert fingerprint(A_BLOB) == "SHA256:FDgBQxiAetGnTRlDwFeTQ008vREAl5emRrvDzWjHxR4"
    assert fingerprint(B_BLOB) == "SHA256:d4tcaq5zba2R6DiyGsGGv4WQxkz5TnPbHCfGnFPeNNA"
    assert FIXTURE_KEY_DIGESTS == {key_digest(A_BLOB), key_digest(B_BLOB)}
    assert parse_public_key_line(A_PUB)[1] == "biolean-fixture-A"


def test_unsupported_key_type_refused():
    b64 = A_PUB.split()[1]
    for kind in ("ssh-rsa", "sk-ssh-ed25519@openssh.com", "ssh-ed25519-cert-v01@openssh.com", "ecdsa-sha2-nistp256"):
        with pytest.raises(SshsigError, match=kind):
            parse_public_key_line(f"{kind} {b64} c")
        with pytest.raises(AllowedSignersError, match=kind):
            parse_allowed_signers(f"alice {kind} {b64} c\n")
    with pytest.raises(SshsigError):
        parse_public_key_line("not a key")


def _line(principal="alice", options='namespaces="biolean-ledger"', pub=A_PUB):
    kind, b64, comment = pub.split()
    opts = f" {options}" if options else ""
    return f"{principal}{opts} {kind} {b64} {comment}\n"


def test_allowed_signers_parses_principals_options_and_skips_comments():
    text = "# trusted list\n\n" + _line('"alice smith,bob"', 'namespaces="biolean-ledger,git"') + _line("carol", "", B_PUB)
    signers = parse_allowed_signers(text)
    assert [s.line for s in signers] == [3, 4]
    assert signers[0].principals == ("alice smith", "bob") and signers[0].namespaces == ("biolean-ledger", "git")
    assert signers[0].blob == A_BLOB and signers[0].key16 == "1438014318807ad1"
    assert signers[1].namespaces is None and signers[1].blob == B_BLOB
    assert find_signer(signers, B_BLOB) is signers[1] and find_signer(signers, b"nope") is None
    assert parse_allowed_signers(allowed_signers_line("dave", A_BLOB, "c"))[0].permits(NAMESPACE)


def test_allowed_signers_line_round_trips_or_refuses():
    # A written line re-parses to exactly one Signer with that principal and blob, including the
    # comment a real .pub carries and a comment with spaces.
    _, comment = parse_public_key_line(A_PUB)
    for principal, com in (("dave", "c"), ("dave", comment), ("fixture-a", ""), ("a@b.org", "x y")):
        [s] = parse_allowed_signers(allowed_signers_line(principal, A_BLOB, com))
        assert (s.principals, s.blob, s.namespaces) == ((principal,), A_BLOB, (NAMESPACE,))
    # Break: split the whole text. A second line in a .pub rides in as the "comment", and
    # allowed_signers_line would then write a second trusted key (B) into the file.
    with pytest.raises(SshsigError, match="line"):
        parse_public_key_line(A_PUB + "bob " + B_PUB)
    # Break: write principal and comment unchecked. Each of these writes a file that re-parses to
    # a second signer, to none (a leading '#' makes the line a comment), to two principals (','),
    # to a quoted principal (whitespace), fails to load ("unterminated quote"), or loses its principal;
    # a NUL ends the line early for OpenSSH, and the reader refuses it.
    for principal, com in (("", "c"), ("#x", "c"), ("a,b", "c"), ("dave smith", "c"), ("dave\tsmith", "c"),
                           ('da"ve', "c"), ("dave", 'c"'), ("dave", "c\nbob " + B_PUB),
                           ("dave\rbob", "c"), ("dave", "c\u2028bob " + B_PUB.strip()),   # U+2028: no \n or \r
                           ("dave\x00", ""), ("dave", "c\x00")):
        with pytest.raises(AllowedSignersError):
            allowed_signers_line(principal, A_BLOB, com)


def test_allowed_signers_splits_lines_on_newline_only():
    # Break: split with str.splitlines. OpenSSH reads lines with getline, so a lone \r, a form feed
    # or U+2028 inside a comment is comment text, not a second trusted line (checked against
    # OpenSSH 10.3p1: `ssh-keygen -Y verify -I bob` refuses key B for every break below).
    kind, b64, _ = A_PUB.split()
    for brk in ("\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
        [s] = parse_allowed_signers(f'dave namespaces="biolean-ledger" {kind} {b64} c{brk}bob {B_PUB}')
        assert (s.line, s.principals, s.blob) == (1, ("dave",), A_BLOB)
    # A CRLF file reads as OpenSSH reads it: the \r lands in the comment or after the key token.
    crlf = (_line("alice") + f"bob {kind} {B_PUB.split()[1]}\n").replace("\n", "\r\n")
    assert [(s.line, s.blob) for s in parse_allowed_signers(crlf)] == [(1, A_BLOB), (2, B_BLOB)]


def test_allowed_signers_splits_fields_on_space_and_tab_only():
    # Break: split fields on every whitespace character. OpenSSH separates fields with space and
    # tab only, so a form feed between the options and the key type leaves a malformed field, and
    # OpenSSH 10.3p1 refuses the line. The reader refuses it too, never a permitted signer, and
    # likewise for any other non-space, non-tab whitespace between two fields.
    kind, b64, _ = A_PUB.split()
    ns = 'namespaces="biolean-ledger"'
    for text in (f"dave {ns}\x0c{kind} {b64}\n", f"dave {ns}\x0c{kind} {b64} c\n", f"dave {ns}\u2028{kind} {b64} c\n",
                 f"dave\x0c{ns} {kind} {b64} c\n", f"dave {ns} {kind}\x0c{b64} c\n", f"dave {ns} {kind} {b64}\x0cc\n",
                 f"dave\x0b{kind} {b64}\n"):
        with pytest.raises(AllowedSignersError, match="whitespace other than space or tab") as exc:
            parse_allowed_signers(text)
        assert exc.value.line == 1


def test_allowed_signers_escaped_quote_reads_as_openssh_does():
    # Break: let \" toggle the quoted state. OpenSSH's options tokenizer skips \" without toggling,
    # so the value below never closes and OpenSSH 10.3p1 refuses the line as an unterminated quote.
    # A toggling tokenizer closes it at x\" (the reader once permitted namespaces
    # ('biolean-ledger', 'x\\') here), so the reason is pinned, not only the refusal.
    kind, b64, _ = A_PUB.split()
    for text in (f'dave namespaces="biolean-ledger,x\\" {kind} {b64}\n',
                 f'dave namespaces="biolean-ledger,x\\" {kind} {b64} c\n'):
        with pytest.raises(AllowedSignersError, match="unterminated quote") as exc:
            parse_allowed_signers(text)
        assert exc.value.line == 1
    # The value is read as OpenSSH's opt_dequote reads it: \" is a literal quote and every other
    # backslash is literal, so \\" is a backslash then an escaped quote. After an escaped quote the
    # value is still quoted, so a space there is inside it, not stray whitespace. OpenSSH 10.3p1
    # verifies key A in biolean-ledger on each of these lines.
    for value, want in (('biolean-ledger,x\\"y', ("biolean-ledger", 'x"y')),
                        ('biolean-ledger,x\\" y', ("biolean-ledger", 'x" y')),
                        ('x\\\\"y,biolean-ledger', ('x\\"y', "biolean-ledger"))):
        [s] = parse_allowed_signers(f'dave namespaces="{value}" {kind} {b64}\n')
        assert (s.namespaces, s.blob) == (want, A_BLOB) and s.permits(NAMESPACE)
    # OpenSSH splits the principals with strdelimw, which has no escapes, so the two tokenizers read
    # this line differently; OpenSSH 10.3p1 refuses it, and any principals field holding \" is refused.
    with pytest.raises(AllowedSignersError, match="escaped quote") as exc:
        parse_allowed_signers(f'"a\\" b" namespaces="biolean-ledger" {kind} {b64}\n')
    assert exc.value.line == 1


def test_allowed_signers_strips_c_whitespace_only():
    # Break: strip the line with str.strip(), which drops every Unicode whitespace character. After
    # the key (no comment) OpenSSH's base64 decoder skips only C isspace bytes, so OpenSSH 10.3p1
    # refuses each line below; str.strip() would drop the character first and permit key A.
    kind, b64, _ = A_PUB.split()
    for x in ("\x1c", "\x1d", "\x1e", "\x1f", "\x85", "\xa0", "\u2028", "\u2029"):
        with pytest.raises(AllowedSignersError, match="whitespace other than space or tab") as exc:
            parse_allowed_signers(f'dave namespaces="biolean-ledger" {kind} {b64}{x}\n')
        assert exc.value.line == 1
    # C isspace after the key is stripped; OpenSSH 10.3p1 accepts these lines too.
    for x in ("\x0b", "\x0c", "\r"):
        [s] = parse_allowed_signers(f'dave namespaces="biolean-ledger" {kind} {b64}{x}\n')
        assert (s.line, s.blob) == (1, A_BLOB)
    # Comment text is never checked.
    [s] = parse_allowed_signers(f'dave namespaces="biolean-ledger" {kind} {b64} c\x1c\n')
    assert (s.line, s.blob) == (1, A_BLOB)


def test_allowed_signers_refuses_a_nul_byte_anywhere():
    # Break: read past a NUL. OpenSSH's C string ends there, so to OpenSSH 10.3p1 the first line is
    # just "dave" (invalid), while a NUL-blind reader permits principal 'dave\x00' with key A. A NUL
    # in a comment or a '#' line is refused too: stricter than OpenSSH, never looser.
    kind, b64, _ = A_PUB.split()
    for text in (f'dave\x00 namespaces="biolean-ledger" {kind} {b64}\n',
                 f'dave namespaces="biolean-ledger" {kind} {b64} c\x00d\n',
                 f'# c\x00d\ndave namespaces="biolean-ledger" {kind} {b64}\n'):
        with pytest.raises(AllowedSignersError, match="NUL") as exc:
            parse_allowed_signers(text)
        assert exc.value.line == 1


def test_signer_without_namespaces_option_is_allowed():
    [s] = parse_allowed_signers(_line(options=""))
    assert s.permits("biolean-ledger") and s.permits("anything")


def test_signer_with_other_namespace_is_unknown():
    [s] = parse_allowed_signers(_line(options='namespaces="git"'))
    assert not s.permits("biolean-ledger")
    [s] = parse_allowed_signers(_line(options='NAMESPACES="biolean-ledger"'))   # case-insensitive, as OpenSSH
    assert s.permits("biolean-ledger")


def test_negated_namespace_is_refused_not_permitted():
    # Break: `namespace in value.split(",")` permits "biolean-ledger,!biolean-ledger", which OpenSSH denies.
    for value in ("biolean-ledger,!biolean-ledger", "!biolean-ledger", "biolean-*", "biolean-ledge?"):
        with pytest.raises(AllowedSignersError, match="pattern"):
            parse_allowed_signers(_line(options=f'namespaces="{value}"'))
    # Break: strip each entry, or drop empty ones. OpenSSH's match_pattern_list does not trim, so
    # it refuses the first two (checked against OpenSSH 10.3p1), and a trailing ',' after the last
    # option is "unexpected end-of-options". An empty entry is refused rather than guessed at.
    for opts in ('namespaces="other, biolean-ledger"', 'namespaces=" biolean-ledger"', 'namespaces="biolean-ledger",',
                 'namespaces="biolean-ledger,,git"'):
        with pytest.raises(AllowedSignersError) as exc:
            parse_allowed_signers(_line(options=opts))
        assert exc.value.line == 1


def test_namespaces_entry_of_1023_bytes_or_more_is_refused():
    # Break: no length cap. OpenSSH's match_pattern_list copies each entry into a 1024-byte buffer
    # and matches nothing once an entry reaches 1023 bytes, wherever it sits: OpenSSH 10.3p1
    # verifies with an entry of 1022 bytes beside biolean-ledger and refuses 1023, in either order.
    # Bytes, not characters: 511 two-byte characters are 1022 bytes, and one more 'x' makes 1023.
    for entry in ("x" * 1022, "\xe9" * 511):
        for value in (f"biolean-ledger,{entry}", f"{entry},biolean-ledger"):
            [s] = parse_allowed_signers(_line(options=f'namespaces="{value}"'))
            assert s.permits(NAMESPACE)
    for entry in ("x" * 1023, "\xe9" * 511 + "x"):
        for value in (f"biolean-ledger,{entry}", f"{entry},biolean-ledger"):
            with pytest.raises(AllowedSignersError, match="1023") as exc:
                parse_allowed_signers(_line(options=f'namespaces="{value}"'))
            assert exc.value.line == 1


def test_unsupported_allowed_signers_option_refuses_to_load():
    for opts in ('valid-before="20300101"', 'cert-authority', 'namespaces="biolean-ledger",valid-after="20200101"',
                 'namespaces="biolean-ledger",namespaces="git"', 'namespaces=biolean-ledger', 'bogus="1"'):
        with pytest.raises(AllowedSignersError) as exc:
            parse_allowed_signers(_line(options=opts))
        assert exc.value.line == 1


def test_duplicate_key_and_key16_collision_refused():
    with pytest.raises(AllowedSignersError, match="already listed"):
        parse_allowed_signers(_line("alice") + _line("bob"))
    # A key16 collision needs a second blob with the same first 16 hex of its digest; simulate the
    # index check by monkeypatching key16 to a constant for this call.
    original = sshsig._key16
    sshsig._key16 = lambda blob: "0000000000000000"
    try:
        with pytest.raises(AllowedSignersError, match="key16"):
            parse_allowed_signers(_line("alice") + _line("bob", pub=B_PUB))
    finally:
        sshsig._key16 = original


def test_small_order_keys_refused_in_allowed_signers():
    # Break: drop the is_small_order call; every line then parses.
    for enc in SMALL_ORDER:
        blob = _pack(b"ssh-ed25519") + _pack(bytes.fromhex(enc))
        line = f'evil ssh-ed25519 {base64.b64encode(blob).decode()} c\n'
        with pytest.raises(AllowedSignersError, match="small-order"):
            parse_allowed_signers(line)
    # A 31-byte key, a truncated blob and garbage base64 are refused as bad keys, not accepted.
    for blob in (_pack(b"ssh-ed25519") + _pack(bytes(31)), _pack(b"ssh-ed25519"), b"\x00"):
        with pytest.raises(AllowedSignersError, match="bad key"):
            parse_allowed_signers(f'x ssh-ed25519 {base64.b64encode(blob).decode()}\n')
    with pytest.raises(AllowedSignersError, match="bad key"):
        parse_allowed_signers("x ssh-ed25519 not*base64\n")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_sshsig.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.sshsig'`.

- [ ] **Step 4: Implement `sshsig.py`**

`src/methods_graph/biolean/sshsig.py`:

```python
"""OpenSSH ``sshsig`` signatures, the ``allowed_signers`` list, and key digests. Verify-only.

Layout (OpenSSH PROTOCOL.sshsig):

    blob:        byte[6] "SSHSIG"  uint32 version=1  string publickey  string namespace
                 string reserved  string hash_algorithm  string signature
    signed data: byte[6] "SSHSIG"  string namespace  string reserved  string hash_algorithm
                 string H(message)

``publickey`` is ``string "ssh-ed25519"  string key(32)``; ``signature`` is
``string "ssh-ed25519"  string sig(64)``. The verifier accepts exactly version 1, the
``biolean-ledger`` namespace, ``sha512``, an empty ``reserved`` and no trailing bytes anywhere
(spec §4). Everything else is refused with the reason in the exception.
"""
from __future__ import annotations

import base64
import hashlib
import struct
from dataclasses import dataclass

from methods_graph.biolean.ed25519 import is_small_order, verify

NAMESPACE = "biolean-ledger"
KEY_TYPE = "ssh-ed25519"
_MAGIC = b"SSHSIG"
_ARMOR_BEGIN = "-----BEGIN SSH SIGNATURE-----"
_ARMOR_END = "-----END SSH SIGNATURE-----"
_KEY_TYPE_PREFIXES = ("ssh-", "ecdsa-", "sk-")
_REFUSED_OPTIONS = frozenset({"cert-authority", "valid-after", "valid-before"})

# The two test keypairs under tests/fixtures/biolean/ledger/keys/, trusted by nothing outside
# the fixtures. `init` refuses them (spec §9, Fixtures).
FIXTURE_KEY_DIGESTS: frozenset[str] = frozenset({
    "1438014318807ad1a74d1943c05793434d3cbd11009797a646bbc3cd68c7c51e",   # A
    "778b5c6aae736dad91e838b21ac186bf8590c64cf94e73db1c27c69c53de34d0",   # B
})


class SshsigError(ValueError):
    """A signature, key or armor the verifier refuses; ``str(exc)`` is the reason."""


class AllowedSignersError(ValueError):
    def __init__(self, line: int, reason: str) -> None:
        super().__init__(f"allowed_signers line {line}: {reason}")
        self.line = line
        self.reason = reason


# ---------------------------------------------------------------------------
# SSH wire strings and keys
# ---------------------------------------------------------------------------

def _string(buf: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(buf):
        raise SshsigError("truncated length")
    (n,) = struct.unpack(">I", buf[offset:offset + 4])
    end = offset + 4 + n
    if end > len(buf):
        raise SshsigError("truncated string")
    return buf[offset + 4:end], end


def _pack(value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + value


def parse_key_blob(blob: bytes) -> bytes:
    """The 32-byte key of an ``ssh-ed25519`` public-key blob; SshsigError for anything else."""
    key_type, offset = _string(blob, 0)
    if key_type != KEY_TYPE.encode("ascii"):
        raise SshsigError(f"key type {key_type.decode('ascii', 'replace')!r} is not {KEY_TYPE}")
    key, offset = _string(blob, offset)
    if offset != len(blob):
        raise SshsigError("trailing bytes after the key")
    if len(key) != 32:
        raise SshsigError(f"ed25519 key must be 32 bytes, got {len(key)}")
    return key


def key_digest(blob: bytes) -> str:
    """sha256 of the raw blob, 64 lowercase hex: the contributor id (``by`` without its prefix)."""
    return hashlib.sha256(blob).hexdigest()


def key16(blob: bytes) -> str:
    return key_digest(blob)[:16]


_key16 = key16      # module alias, so Signer.key16 can call the function


def fingerprint(blob: bytes) -> str:
    """The form ``ssh-keygen -lf`` prints: ``SHA256:`` + unpadded base64 of the digest."""
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")


def parse_public_key_line(text: str) -> tuple[bytes, str]:
    """``(blob, comment)`` from one ``ssh-ed25519 AAAA... comment`` line.

    Refuses every other type: ``sk-ssh-ed25519@openssh.com``, ``*-cert-v01@openssh.com``, RSA.
    Refuses text with more than one non-empty line: the comment would carry the rest of the
    file, and ``allowed_signers_line`` would write it out as more trusted keys.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        raise SshsigError(f"expected one public key line, got {len(lines)}")
    fields = text.strip().split(None, 2)
    if len(fields) < 2:
        raise SshsigError("not a public key line")
    if fields[0] != KEY_TYPE:
        raise SshsigError(f"key type {fields[0]!r} is not {KEY_TYPE}")
    try:
        blob = base64.b64decode(fields[1], validate=True)
    except ValueError as exc:                      # binascii.Error is a ValueError
        raise SshsigError(f"public key is not base64: {exc}") from None
    parse_key_blob(blob)
    return blob, (fields[2].strip() if len(fields) == 3 else "")


# ---------------------------------------------------------------------------
# sshsig
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Sshsig:
    public_key_blob: bytes
    public_key: bytes
    namespace: str
    hash_algorithm: str
    signature: bytes


def parse_sshsig(sig: str) -> Sshsig:
    """Decode and structurally check a ``sig`` value (spec §1, §4). Does not verify."""
    if not isinstance(sig, str) or not sig:
        raise SshsigError("sig must be a non-empty string")
    try:
        blob = base64.b64decode(sig, validate=True)
    except ValueError as exc:
        raise SshsigError(f"sig is not standard base64: {exc}") from None
    if base64.b64encode(blob).decode("ascii") != sig:
        raise SshsigError("sig is not canonical base64")
    if blob[:6] != _MAGIC:
        raise SshsigError("missing SSHSIG preamble")
    if len(blob) < 10:
        raise SshsigError("truncated version")
    (version,) = struct.unpack(">I", blob[6:10])
    if version != 1:
        raise SshsigError(f"sshsig version {version} is not 1")
    pk_blob, offset = _string(blob, 10)
    namespace, offset = _string(blob, offset)
    reserved, offset = _string(blob, offset)
    hash_algorithm, offset = _string(blob, offset)
    signature, offset = _string(blob, offset)
    if offset != len(blob):
        raise SshsigError("trailing bytes after the signature")
    if reserved != b"":
        raise SshsigError("reserved field is not empty")
    if hash_algorithm != b"sha512":
        raise SshsigError(f"hash algorithm {hash_algorithm!r} is not sha512")
    public_key = parse_key_blob(pk_blob)
    sig_type, soff = _string(signature, 0)
    sig_value, soff = _string(signature, soff)
    if soff != len(signature):
        raise SshsigError("trailing bytes inside the signature string")
    if sig_type != KEY_TYPE.encode("ascii"):
        raise SshsigError(f"signature type {sig_type!r} is not {KEY_TYPE}")
    if len(sig_value) != 64:
        raise SshsigError(f"ed25519 signature must be 64 bytes, got {len(sig_value)}")
    try:
        ns = namespace.decode("ascii")
    except UnicodeDecodeError:
        raise SshsigError("namespace is not ASCII") from None
    return Sshsig(pk_blob, public_key, ns, "sha512", sig_value)


def signed_data(message: bytes, namespace: str = NAMESPACE) -> bytes:
    """What ssh-keygen signs: the preamble, namespace, reserved, hash name and sha512(message)."""
    return (_MAGIC + _pack(namespace.encode("ascii")) + _pack(b"") + _pack(b"sha512")
            + _pack(hashlib.sha512(message).digest()))


def verify_sshsig(sig: str, message: bytes, *, namespace: str = NAMESPACE) -> bytes:
    """The signer's public-key blob when ``sig`` verifies over ``message`` in ``namespace``;
    SshsigError otherwise."""
    parsed = parse_sshsig(sig)
    if parsed.namespace != namespace:
        raise SshsigError(f"namespace {parsed.namespace!r} is not {namespace!r}")
    if not verify(parsed.public_key, signed_data(message, namespace), parsed.signature):
        raise SshsigError("signature does not verify")
    return parsed.public_key_blob


def dearmor(stdout: bytes) -> str:
    """``sig`` from ssh-keygen's armored stdout: the base64 lines joined with no whitespace."""
    try:
        text = stdout.decode("ascii")
    except UnicodeDecodeError:
        raise SshsigError("armor is not ASCII") from None
    lines = [line.strip() for line in text.splitlines()]
    if _ARMOR_BEGIN not in lines or _ARMOR_END not in lines:
        raise SshsigError("no SSH SIGNATURE armor in the output")
    start, end = lines.index(_ARMOR_BEGIN), lines.index(_ARMOR_END)
    body = "".join(lines[start + 1:end]) if end > start else ""
    if not body:
        raise SshsigError("empty armor")
    return body


def armor(sig: str) -> str:
    """The armored form ``ssh-keygen -Y verify`` reads: base64 wrapped at 70 columns."""
    lines = [sig[i:i + 70] for i in range(0, len(sig), 70)]
    return "\n".join([_ARMOR_BEGIN, *lines, _ARMOR_END]) + "\n"


# ---------------------------------------------------------------------------
# allowed_signers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Signer:
    line: int
    principals: tuple[str, ...]
    namespaces: tuple[str, ...] | None      # None: every namespace, as OpenSSH reads it
    blob: bytes

    @property
    def digest(self) -> str:
        return key_digest(self.blob)

    @property
    def key16(self) -> str:
        return _key16(self.blob)

    def permits(self, namespace: str) -> bool:
        return self.namespaces is None or namespace in self.namespaces


def _split_fields(line: str, lineno: int) -> list[str]:
    """Fields separated by space and tab outside double quotes, as OpenSSH splits them.

    ``\\"`` is an escaped quote, as in OpenSSH's ``sshkey_advance_past_options``: both characters
    stay in the field and the quoted state does not change. Every other backslash is literal.
    Any other whitespace (a form feed, U+2028) stays inside its field; ``_refuse_stray_whitespace``
    then refuses it wherever it lands outside the comment.
    """
    out: list[str] = []
    cur = ""
    quoted = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and line.startswith('"', i + 1):
            cur += '\\"'
            i += 2
            continue
        if ch == '"':
            quoted = not quoted
            cur += ch
        elif ch in " \t" and not quoted:
            if cur:
                out.append(cur)
                cur = ""
        else:
            cur += ch
        i += 1
    if quoted:
        raise AllowedSignersError(lineno, "unterminated quote")
    if cur:
        out.append(cur)
    return out


def _refuse_stray_whitespace(field: str, lineno: int) -> None:
    """A field holding whitespace outside double quotes is malformed: OpenSSH would not split
    there, so reading two fields out of it could permit what OpenSSH refuses. Quotes are tracked
    as ``_split_fields`` tracks them: ``\\"`` never opens or closes one."""
    quoted = False
    i = 0
    while i < len(field):
        ch = field[i]
        if ch == "\\" and field.startswith('"', i + 1):
            i += 2
            continue
        if ch == '"':
            quoted = not quoted
        elif ch.isspace() and not quoted:
            raise AllowedSignersError(lineno, f"field {field!r} holds whitespace other than space or tab")
        i += 1


def _parse_options(opts: str, lineno: int) -> tuple[str, ...] | None:
    """The ``namespaces`` list, or None when absent. Every other option is refused (spec §4)."""
    namespaces: tuple[str, ...] | None = None
    seen: set[str] = set()
    i = 0
    while i < len(opts):
        j = i
        while j < len(opts) and opts[j] not in "=,":
            j += 1
        name = opts[i:j].lower()
        if not name:
            raise AllowedSignersError(lineno, "empty option")
        value: str | None = None
        if j < len(opts) and opts[j] == "=":
            if j + 1 >= len(opts) or opts[j + 1] != '"':
                raise AllowedSignersError(lineno, f"option {name} needs a double-quoted value")
            # As OpenSSH's opt_dequote reads it: \" is a literal quote, every other backslash is
            # literal, and the value ends at the first unescaped quote.
            chars: list[str] = []
            k = j + 2
            while k < len(opts) and opts[k] != '"':
                if opts[k] == "\\" and opts.startswith('"', k + 1):
                    k += 1
                chars.append(opts[k])
                k += 1
            if k >= len(opts):
                raise AllowedSignersError(lineno, f"option {name}: unterminated value")
            value = "".join(chars)
            i = k + 1
        else:
            i = j
        if i < len(opts):
            if opts[i] != ",":
                raise AllowedSignersError(lineno, f"option {name}: expected ',' after the value")
            i += 1
            if i == len(opts):                     # OpenSSH: "unexpected end-of-options"
                raise AllowedSignersError(lineno, "trailing ',' after the last option")
        if name in seen:
            raise AllowedSignersError(lineno, f"option {name} appears twice")
        seen.add(name)
        if name == "namespaces":
            if value is None:
                raise AllowedSignersError(lineno, "namespaces needs a quoted value")
            if any(c in value for c in "*?!"):
                raise AllowedSignersError(lineno, "namespaces pattern characters (* ? !) are not supported")
            # OpenSSH's match_pattern_list compares each entry verbatim, untrimmed, so " x" never
            # matches "x". Stripping here would permit what OpenSSH denies; refuse instead.
            entries = value.split(",")
            for entry in entries:
                if not entry or entry != entry.strip():
                    raise AllowedSignersError(lineno, f"namespaces entry {entry!r} is empty or has surrounding whitespace")
                # match_pattern_list copies each entry into a 1024-byte buffer and matches nothing
                # at all once an entry reaches 1023 bytes, wherever it sits in the list.
                size = len(entry.encode("utf-8"))
                if size >= 1023:
                    raise AllowedSignersError(lineno, f"namespaces entry of {size} bytes: OpenSSH matches "
                                                      "no namespace when an entry has 1023 bytes or more")
            namespaces = tuple(entries)
        elif name in _REFUSED_OPTIONS:
            raise AllowedSignersError(lineno, f"option {name} is not supported by this verifier")
        else:
            raise AllowedSignersError(lineno, f"unknown option {name}")
    return namespaces


def parse_allowed_signers(text: str) -> list[Signer]:
    """OpenSSH allowed_signers, restricted to what the verifier implements (spec §4).

    Raises AllowedSignersError naming the line for: a key type other than ssh-ed25519, any
    option but ``namespaces``, a namespaces pattern, a namespaces entry of 1023 UTF-8 bytes or
    more (OpenSSH then matches no namespace), a principals field holding ``\\"`` (OpenSSH does
    not read it as an escape there), a duplicate key or key16, a small-order key, and a NUL
    anywhere in the line, even in a comment (stricter than OpenSSH, which reads a line only up
    to its first NUL). Blank lines and ``#`` comments are skipped; option names are
    case-insensitive. Lines end at ``\\n`` only, as OpenSSH reads them with getline: a ``\\r``,
    form feed or U+2028 inside a comment is comment text, never a second line
    (``str.splitlines`` would split there). A line is stripped of C whitespace only (space, tab,
    CR, LF, VT, FF), so other whitespace after the key stays in it and is refused, as OpenSSH's
    base64 decoder refuses it. Fields split on space and tab only, as in OpenSSH; other
    whitespace between two fields before the comment is refused.
    """
    signers: list[Signer] = []
    seen_blobs: dict[bytes, int] = {}
    seen_key16: dict[str, int] = {}
    usage = "expected: principals [options] ssh-ed25519 <base64> [comment]"
    for lineno, raw in enumerate(text.split("\n"), 1):
        if "\x00" in raw:
            raise AllowedSignersError(lineno, "NUL byte: OpenSSH reads the line only up to it")
        line = raw.strip(" \t\r\n\v\f")             # C isspace; other whitespace stays and is refused
        if not line or line.startswith("#"):
            continue
        fields = _split_fields(line, lineno)
        if '\\"' in fields[0]:
            # OpenSSH splits the principals with strdelimw, which has no escapes: there \" opens or
            # closes a quote, so the two tokenizers would read different fields. Stricter: refuse.
            raise AllowedSignersError(lineno, f"principals field {fields[0]!r} holds an escaped quote: "
                                              "OpenSSH has no escapes there")
        for field in fields[:2]:                   # the principals; the options or the key type
            _refuse_stray_whitespace(field, lineno)
        if len(fields) < 3:
            raise AllowedSignersError(lineno, usage)
        principals_raw = fields[0]
        if len(principals_raw) >= 2 and principals_raw[0] == principals_raw[-1] == '"':
            principals_raw = principals_raw[1:-1]
        principals = tuple(p for p in principals_raw.split(",") if p)
        if not principals:
            raise AllowedSignersError(lineno, "no principal")
        if fields[1] == KEY_TYPE or fields[1].startswith(_KEY_TYPE_PREFIXES):
            options, key_type, b64 = "", fields[1], fields[2]
        elif len(fields) >= 4:
            options, key_type, b64 = fields[1], fields[2], fields[3]
        else:
            raise AllowedSignersError(lineno, usage)
        for field in (key_type, b64):              # everything after b64 is the comment
            _refuse_stray_whitespace(field, lineno)
        if key_type != KEY_TYPE:
            raise AllowedSignersError(lineno, f"key type {key_type!r} is not {KEY_TYPE}")
        namespaces = _parse_options(options, lineno)
        try:
            blob = base64.b64decode(b64, validate=True)
            key = parse_key_blob(blob)
        except ValueError as exc:                  # SshsigError and binascii.Error are ValueErrors
            raise AllowedSignersError(lineno, f"bad key: {exc}") from None
        if is_small_order(key):
            raise AllowedSignersError(lineno, "small-order key: one fixed signature would verify every message")
        if blob in seen_blobs:
            raise AllowedSignersError(lineno, f"key already listed on line {seen_blobs[blob]}")
        short = _key16(blob)
        if short in seen_key16:
            raise AllowedSignersError(lineno, f"key16 {short} collides with line {seen_key16[short]}")
        seen_blobs[blob] = lineno
        seen_key16[short] = lineno
        signers.append(Signer(lineno, principals, namespaces, blob))
    return signers


def find_signer(signers: list[Signer], blob: bytes) -> Signer | None:
    for signer in signers:
        if signer.blob == blob:
            return signer
    return None


def allowed_signers_line(principal: str, blob: bytes, comment: str = "") -> str:
    """One line in the form ``init`` writes: the principal, the ledger namespace, the key.

    Refuses (AllowedSignersError, line 0: not read from a file) any principal the reader would
    not hand back as written: empty, starting with ``#`` (the line reads as a comment), or
    holding ``,`` (several principals), whitespace (a quoted token) or ``"``. Also refuses a
    ``"`` or any line break ``str.splitlines`` honours in the comment, and a NUL in either
    (OpenSSH would read the line only up to it, and the reader refuses it). Each would write a
    file that re-parses to another signer, to none, fails to load, or changes its principal.
    """
    if not principal:
        raise AllowedSignersError(0, "empty principal")
    if principal.startswith("#"):
        raise AllowedSignersError(0, f"principal {principal!r} starts with '#': the line would read as a comment")
    if "," in principal:
        raise AllowedSignersError(0, f"principal {principal!r} contains ',': it would read as several principals")
    if any(c.isspace() for c in principal):
        raise AllowedSignersError(0, f"principal {principal!r} contains whitespace")
    for what, value in (("principal", principal), ("comment", comment)):
        if "\x00" in value:
            raise AllowedSignersError(0, f"{what} {value!r} contains a NUL byte: OpenSSH would end the line there")
        if '"' in value or (value and value.splitlines() != [value]):
            raise AllowedSignersError(0, f"{what} {value!r} contains a double quote or a line break")
    b64 = base64.b64encode(blob).decode("ascii")
    tail = f" {comment}" if comment else ""
    return f'{principal} namespaces="{NAMESPACE}" {KEY_TYPE} {b64}{tail}\n'
```

- [ ] **Step 5: Run the tests**

Run: `$PYTEST tests/test_biolean_sshsig.py tests/test_biolean_ed25519.py -q`
Expected: all pass.

Mutation checks: (a) in `_parse_options`, replace the pattern refusal with `namespaces = tuple(value.split(","))`: `test_negated_namespace_is_refused_not_permitted` fails. (b) delete the `is_small_order` call: `test_small_order_keys_refused_in_allowed_signers` fails. (c) delete the canonical-base64 comparison in `parse_sshsig`: the "non-canonical padding" case of `test_sshsig_fields_are_enforced` fails (the decoded bytes are identical, so verification would pass). (d) delete the `hash_algorithm != b"sha512"` check: `parse_sshsig` accepts the relabeled blob and, because `signed_data` always rebuilds the signed bytes with sha512, the signature then verifies, so the "sha256" case fails at its first `pytest.raises` (`verify_sshsig`); this check is the only defence against a relabeled hash algorithm.

Review fixes folded into the blocks above during execution (branch commits `db5feac`, `dc5f39e`, `0ca972b`; spec §4 "as OpenSSH parses them" over the original draft): `namespaces` entries are split without stripping and an empty or whitespace-padded entry, or a trailing comma after the last option, is refused (OpenSSH 10.3p1 refuses all three); `parse_public_key_line` refuses more than one non-empty line; `allowed_signers_line` refuses a principal that is empty, starts with `#`, or contains `,`, whitespace or `"`, and any line break in principal or comment, so a written line always re-parses as exactly one signer; `parse_allowed_signers` splits the file on `\n` only and fields on space and tab only, as OpenSSH does. `test_biolean_sshsig.py` holds the round-trip and refusal cases; each was confirmed to fail against the previous commit.

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/biolean/sshsig.py tests/test_biolean_sshsig.py tests/fixtures/biolean/ledger/keys tests/fixtures/biolean/ledger/known
git commit -m "feat(biolean): sshsig verification and the allowed_signers reader

Parses OpenSSH sshsig blobs strictly (version 1, biolean-ledger, sha512, no
trailing bytes, canonical base64) and verifies with ed25519.verify. The
allowed_signers reader implements namespaces only and refuses every other
option, key type, pattern, duplicate and small-order key. Fixture keys A and B
and four real ssh-keygen signatures are checked in.

mutation checked: permitting namespaces by split(',') fails the negated-
namespace test; dropping the canonical base64 rule fails the padding case."
```

---

### Task 5: `ledger/errors.py` and `ledger/format.py`: the error shape, canonical bytes, field schema, character rules

**Files:**
- Create: `src/methods_graph/biolean/ledger/__init__.py` (one docstring line: `"""The Biolean ledger: signed, hash-chained, kernel-checked facts (spec 2026-09-25)."""`)
- Create: `src/methods_graph/biolean/ledger/errors.py`
- Create: `src/methods_graph/biolean/ledger/format.py`
- Test: `tests/test_biolean_ledger_format.py`

**Interfaces:**
- Consumes: `gaf.GAF_COLUMNS`, `props.Prop`.
- Produces (`methods_graph.biolean.ledger.errors`):
  - `LedgerCode` — one string constant per code below; `ALL_LEDGER_CODES: frozenset[str]`; `TERMINAL_CODES = {NOT_YET_DISCHARGEABLE, LEDGER_DUPLICATE, LEDGER_BASE_MISMATCH}`; `BASE_INDEPENDENT_CODES` (the §3 "does not depend on the base" set: `LEDGER_BAD_COLUMNS, LEDGER_VERSION, LEDGER_BAD_KIND, LEDGER_BAD_CHARACTER, LEDGER_BAD_SUBJECT, UNKNOWN_QUALIFIER, LEDGER_BAD_REFERENCE, LEDGER_REFERENCE_REQUIRED, LEDGER_BAD_TAXON, LEDGER_BAD_DATE, LEDGER_BAD_OBJECT_TYPE, LEDGER_ASSIGNED_BY, LEDGER_MALFORMED`).
  - `LedgerError(code, message, field, got=None, fix=None, options=(), context=None)` frozen dataclass; `to_dict()` → the seven keys, `options` as a list.
  - `LedgerIntegrityError(errors: list[LedgerError])` exception; `.errors`; `to_json() -> {"errors": [...]}`.
- Produces (`methods_graph.biolean.ledger.format`):
  - constants `FORMAT_VERSION = 1`, `KINDS`, `COMMON_FIELDS`, `KIND_FIELDS`, `OPTIONAL_FIELDS`, `RELEASE_KEYS`, `ASSIGNED_BY_PREFIX = "biolean:"`, `ASCII_COLUMNS`, regexes `TS_RE`, `HEX64_RE`, `LEDGER_ID_RE`, `BY_RE`, `FILE_RE`.
  - `canon(obj) -> bytes`, `unsigned(entry) -> dict`, `entry_hash(entry) -> str`.
  - `parse_line(raw: bytes) -> tuple[Any, str | None]` — `(obj, None)` when `raw == canon(obj) + b"\n"`, else `(None, reason)`.
  - `shape_errors(entry, *, ledger_id: str | None = None, unknown_kind_code: str = LedgerCode.LEDGER_BAD_KIND) -> list[LedgerError]` — §1 field set and JSON types; `LEDGER_VERSION`, `unknown_kind_code`, `LEDGER_WRONG_LEDGER`, else `LEDGER_MALFORMED`.
  - `string_fault(s, *, column=False, ascii_only=False) -> str | None` (the first offending code point as `U+XXXX`), `clean_string(s, *, column=False, ascii_only=False) -> str`, `column_character_error(i: int, value: str) -> LedgerError | None`, `character_errors(entry) -> list[LedgerError]` (every string in the entry, fact columns under the column rules).
  - `pointer_get(obj, pointer)`, `pointer_set(obj, pointer, value) -> deep copy` (RFC 6901, `~0`/`~1` unescaped).

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_ledger_format.py`:

```python
"""Canonical bytes, entry hash, line parsing, the spec section 1 field schema, the section 2 step 1a
character rules. This module is pure ASCII: non-ASCII test values are written as escapes."""
import json

import pytest

from methods_graph.biolean.ledger.errors import ALL_LEDGER_CODES, LedgerCode as LC, LedgerError, LedgerIntegrityError
from methods_graph.biolean.ledger.format import (
    ASCII_COLUMNS, FILE_RE, MAX_DEPTH, canon, character_errors, clean_string, column_character_error,
    entry_hash, nesting_depth, parse_line, pointer_get, pointer_set, shape_errors, string_fault, unsigned)

LEDGER_ID = "0123456789abcdef0123456789abcdef"
DIGEST = "ab" * 32
FACT = ["UniProtKB", "P04637", "TP53", "involved_in", "GO:0006915",
        "DOI:10.1038/s41586-026-00001-0", "IDA", "", "P", "", "", "protein",
        "taxon:9606", "20260925", "biolean:3f2a9c1e8b7d6054", "", ""]


def entry(**over):
    e = {"v": 1, "kind": "axiom", "ledger": LEDGER_ID, "fact": list(FACT),
         "base": {"obo": DIGEST, "gaf": DIGEST, "eco": DIGEST,
                  "release": {"go_basic_data_version": "releases/2026-07-26",
                              "goa_date_generated": "2026-05-21T08:10", "goa_go_version": "x"}},
         "check": {"kernel": "0.1.0", "annotation_id": "gaf:9d1c0000deadbeef", "contested_by": [],
                   "counters": {"new_subject": 0}},
         "prev": "", "by": "sha256:" + DIGEST, "ts": "2026-09-25T10:00:00Z", "sig": "U1NIU0lH"}
    e.update(over)
    return e


def test_canon_is_compact_sorted_ascii_and_refuses_nan():
    assert canon({"b": 1, "a": [True, None, "\u00e9"]}) == b'{"a":[true,null,"\\u00e9"],"b":1}'
    with pytest.raises(ValueError):
        canon({"x": float("nan")})


def test_entry_hash_excludes_sig_and_is_64_hex():
    e = entry()
    h = entry_hash(e)
    assert len(h) == 64 and h == h.lower() and h == entry_hash(entry(sig="other"))
    assert h != entry_hash(entry(ts="2026-09-25T10:00:01Z"))
    assert "sig" not in unsigned(e) and "sig" in e


def test_parse_line_accepts_only_canonical_lines():
    # Break: compare json.loads results instead of bytes; four "reason" cases then parse
    # (reordered keys, whitespace, number form, duplicate key). Break: drop the ValueError guard
    # around canon; the two overflow cases (json.loads reads them as +-inf) then raise.
    line = canon(entry()) + b"\n"
    obj, reason = parse_line(line)
    assert reason is None and obj == entry()
    reasons = {
        "reordered keys": b'{"v":1,"kind":"axiom"}\n',
        "whitespace": b'{"kind": "axiom","v":1}\n',
        "carriage return": canon(entry()) + b"\r\n",
        "blank": b"\n",
        "missing newline": canon(entry()),
        "NaN": b'{"v":NaN}\n',
        "Infinity": b'{"v":Infinity}\n',
        "number form": b'{"v":1e5}\n',
        "duplicate key": b'{"v":1,"v":2}\n',
        "float overflow": b'{"v":1e999}\n',
        "negative float overflow": b'[-1e400]\n',
        "non-ASCII byte": '{"v":"\u00e9"}\n'.encode("utf-8"),
        "not JSON": b"nope\n",
    }
    for name, bad in reasons.items():
        obj, reason = parse_line(bad)
        assert obj is None and reason, name
    assert "Out of range" in parse_line(b'{"v":1e999}\n')[1]


def _nested(depth):
    obj = "x"
    for i in range(depth):
        obj = {"a": obj} if i % 2 else [obj]
    return obj


def test_nesting_depth_counts_containers_iteratively():
    # Break: a recursive walk (RecursionError at 100000 deep); no stop past MAX_DEPTH (100000 deep
    # then reports 100000, which fails before the cyclic case, and the cyclic list never returns).
    assert (nesting_depth(1), nesting_depth({"a": 1}), nesting_depth({"a": [1]}), nesting_depth([])) == (0, 1, 2, 1)
    assert nesting_depth(entry()) == 3 and nesting_depth(_nested(MAX_DEPTH)) == MAX_DEPTH == 64
    assert nesting_depth(_nested(MAX_DEPTH + 1)) == nesting_depth(_nested(100000)) == MAX_DEPTH + 1
    cyclic = []
    cyclic.append(cyclic)
    assert nesting_depth(cyclic) == MAX_DEPTH + 1
    with pytest.raises(ValueError, match="nesting deeper than 64 levels"):
        canon(cyclic)


def test_parse_line_refuses_nesting_deeper_than_max_depth():
    # Break: drop the depth check (the 65-deep line then parses); drop the RecursionError catch
    # (the 1000000-deep line then raises; 3.14's json.loads decodes 100000 levels, 3.12's does not).
    deepest = _nested(MAX_DEPTH)
    assert parse_line(canon(deepest) + b"\n") == (deepest, None)
    too_deep = json.dumps(_nested(MAX_DEPTH + 1), separators=(",", ":")).encode("ascii") + b"\n"
    assert parse_line(too_deep) == (None, "nesting deeper than 64 levels")
    for n in (100000, 1000000):
        assert parse_line(b"[" * n + b"]" * n + b"\n") == (None, "nesting deeper than 64 levels"), n


def test_canon_refuses_nesting_deeper_than_max_depth():
    # Break: drop the depth check in canon; the 65-deep object is then written.
    with pytest.raises(ValueError, match="nesting deeper than 64 levels"):
        canon(_nested(MAX_DEPTH + 1))
    with pytest.raises(ValueError, match="nesting deeper than 64 levels"):
        canon(_nested(100000))


def test_shape_errors_on_the_example_entry_is_empty():
    assert shape_errors(entry(), ledger_id=LEDGER_ID) == []
    assert shape_errors(entry(admission={"policy": "allowed_signers"}), ledger_id=LEDGER_ID) == []
    assert shape_errors(entry(check={**entry()["check"], "reference_resolved": {"title": "x"}}), ledger_id=LEDGER_ID) == []


def test_version_true_or_float_is_ledger_version():
    # Break: `entry.get("v") == 1` (True == 1 and 1.0 == 1 in Python).
    for v in (True, 1.0, "1", 2, None):
        [e] = [x for x in shape_errors(entry(v=v)) if x.field == "/v"]
        assert (e.code, e.got, e.fix) == (LC.LEDGER_VERSION, v, 1)


def test_unknown_kind_missing_and_extra_fields_are_malformed():
    errs = shape_errors(entry(kind="rule"))
    assert [(e.code, e.field) for e in errs] == [(LC.LEDGER_BAD_KIND, "/kind")]
    assert errs[0].options == ("axiom", "computed", "derived") and errs[0].fix is None
    assert [(e.code, e.field) for e in shape_errors(entry(kind="rule"), unknown_kind_code=LC.LEDGER_MALFORMED)] == [(LC.LEDGER_MALFORMED, "/kind")]
    e = entry()
    del e["prev"]
    assert [(x.code, x.field, x.got) for x in shape_errors(e)] == [(LC.LEDGER_MALFORMED, "/prev", None)]
    assert [(x.code, x.field) for x in shape_errors(entry(foo=1))] == [(LC.LEDGER_MALFORMED, "/foo")]
    assert [(x.code, x.field) for x in shape_errors(entry(admission="yes"))] == [(LC.LEDGER_MALFORMED, "/admission")]
    assert [(x.code, x.field) for x in shape_errors("not an object")] == [(LC.LEDGER_MALFORMED, "")]
    # derived and computed carry their own fields, and an axiom must not carry theirs
    assert [(x.code, x.field) for x in shape_errors(entry(derivation={}))] == [(LC.LEDGER_MALFORMED, "/derivation")]


def test_wrong_ledger_id_is_wrong_ledger_and_bad_ids_are_malformed():
    [e] = shape_errors(entry(), ledger_id="f" * 32)
    assert (e.code, e.field, e.got) == (LC.LEDGER_WRONG_LEDGER, "/ledger", LEDGER_ID)
    assert [x.code for x in shape_errors(entry(ledger="ABC"))] == [LC.LEDGER_MALFORMED]
    assert [x.field for x in shape_errors(entry(prev="0" * 63))] == ["/prev"]
    assert [x.field for x in shape_errors(entry(by=DIGEST))] == ["/by"]
    assert [x.field for x in shape_errors(entry(sig=None))] == ["/sig"]


def test_impossible_ts_is_malformed_by_shape():
    # The last case is Arabic-Indic digits. Break: `\d` for `[0-9]` in TS_RE (strptime accepts them).
    for ts in ("2026-02-30T00:00:00Z", "2026-09-25T10:00:00", "2026-09-25 10:00:00Z", "2026-09-25T24:00:00Z",
               "\u0662\u0660\u0662\u0666-09-25T10:00:00Z"):
        assert [(x.code, x.field) for x in shape_errors(entry(ts=ts))] == [(LC.LEDGER_MALFORMED, "/ts")], ts


def test_a_trailing_newline_is_malformed():
    # Break: `$` for `\Z` in HEX64_RE (`$` also matches just before a final newline).
    base = entry()["base"]
    cases = {"/prev": entry(prev="0" * 64 + "\n"), "/by": entry(by="sha256:" + DIGEST + "\n"),
             "/ledger": entry(ledger=LEDGER_ID + "\n"), "/base": entry(base={**base, "obo": DIGEST + "\n"}),
             "/ts": entry(ts="2026-09-25T10:00:00Z\n")}
    for field, e in cases.items():
        assert [(x.code, x.field) for x in shape_errors(e, ledger_id=LEDGER_ID)] == [(LC.LEDGER_MALFORMED, field)], field
    assert FILE_RE.match("0123456789abcdef.jsonl") and not FILE_RE.match("0123456789abcdef.jsonl\n")


def test_base_and_check_blocks_are_typed_per_kind():
    base = entry()["base"]
    assert [x.field for x in shape_errors(entry(base={**base, "obo": "short"}))] == ["/base"]
    assert [x.field for x in shape_errors(entry(base={**base, "extra": 1}))] == ["/base"]
    assert [x.field for x in shape_errors(entry(base={**base, "release": {}}))] == ["/base"]
    chk = entry()["check"]
    assert [x.field for x in shape_errors(entry(check={**chk, "counters": {"new_subject": True}}))] == ["/check"]
    assert [x.field for x in shape_errors(entry(check={**chk, "contested_by": "gaf:x"}))] == ["/check"]
    assert [x.field for x in shape_errors(entry(check={**chk, "extra": 1}))] == ["/check"]
    assert [x.field for x in shape_errors(entry(fact=FACT[:16]))] == ["/fact"]
    assert [x.field for x in shape_errors(entry(fact=FACT[:16] + [1]))] == ["/fact"]
    d = entry(kind="derived", derivation={"goal": {}, "steps": [], "root": "s1"},
              conclusion={"subject": "UniProtKB:P1", "qualifier": "involved_in", "term": "GO:1",
                          "taxon": "NCBITaxon:9606", "negated": False},
              check={"kernel": "0.1.0", "axioms": [], "conflicts": []})
    del d["fact"]
    assert shape_errors(d, ledger_id=LEDGER_ID) == []
    assert [x.field for x in shape_errors({**d, "conclusion": {"subject": "x"}})] == ["/conclusion"]
    assert [x.field for x in shape_errors({**d, "check": {"kernel": "0.1.0"}})] == ["/check"]


def test_character_errors_find_surrogates_controls_and_nfc():
    # Break: skip the surrogate check (UnicodeEncodeError later); skip NFC; treat U+2028 as fine.
    e = entry(fact=FACT[:16] + ["\ud800"])
    [err] = character_errors(e)
    assert (err.code, err.field, err.got, err.fix) == (LC.LEDGER_BAD_CHARACTER, "/fact/16", "U+D800", "")
    [err] = character_errors(entry(fact=FACT[:16] + ["x\r"]))
    assert (err.field, err.got, err.fix) == ("/fact/16", "U+000D", "x")
    [err] = character_errors(entry(fact=FACT[:1] + ["P0463\u00e9"] + FACT[2:]))   # column 2 is ASCII-only
    assert (err.field, err.got, err.fix) == ("/fact/1", "U+00E9", "P0463")
    nfd = "cafe\u0301"                                                       # column 10 allows non-ASCII, NFC only
    [err] = character_errors(entry(fact=FACT[:9] + [nfd] + FACT[10:]))
    assert (err.field, err.got, err.fix) == ("/fact/9", "U+0065", "caf\u00e9")
    [err] = character_errors(entry(fact=FACT[:9] + ["a\u2028b"] + FACT[10:]))
    assert (err.field, err.got, err.fix) == ("/fact/9", "U+2028", "ab")
    [err] = character_errors(entry(fact=FACT[:9] + ["a\u200bb"] + FACT[10:]))   # Cf
    assert err.got == "U+200B"
    [err] = character_errors(entry(ts="2026-09-25T10:00:00Z\ud800"))
    assert err.field == "/ts" and err.got == "U+D800"
    d = entry(kind="derived", derivation={"steps": [{"id": nfd}]}, conclusion={})
    [err] = character_errors(d)
    assert err.field == "/derivation/steps/0/id" and err.fix == "caf\u00e9"
    assert character_errors(entry()) == []


def test_character_errors_check_dict_keys_at_the_containing_object():
    # Break: walk values only; a key with a lone surrogate or in NFD then passes.
    [err] = character_errors(entry(admission={"policy": "allowed_signers", "s\ud800": "x"}))
    assert (err.code, err.field, err.got, err.fix) == (LC.LEDGER_BAD_CHARACTER, "/admission", "U+D800", None)
    assert repr("s\ud800") in err.message
    nfd = "cafe\u0301"
    [err] = character_errors(entry(kind="derived", derivation={"steps": [{nfd: "s1"}]}, conclusion={}))
    assert (err.code, err.field, err.got, err.fix) == (LC.LEDGER_BAD_CHARACTER, "/derivation/steps/0", "U+0065", None)
    assert repr(nfd) in err.message
    [err] = character_errors({**entry(), "\ud800": 1})
    assert (err.field, err.got, err.fix) == ("", "U+D800", None) and "top level" in err.message
    assert character_errors(entry(admission={"policy": "allowed_signers"})) == []
    assert character_errors(entry()) == []


def test_empty_columns_15_16_17_pass_character_check():
    row = list(FACT)
    row[14] = ""
    assert all(column_character_error(i, v) is None for i, v in enumerate(row))
    assert ASCII_COLUMNS == {0, 1, 3, 4, 5, 6, 7, 8, 12, 13, 14, 15, 16}
    assert string_fault("a b", ascii_only=True) == "U+0020" and clean_string("a b", ascii_only=True) == "ab"
    assert string_fault("a b") is None and column_character_error(9, "gene one") is None


def test_pointer_get_and_set():
    e = entry()
    assert pointer_get(e, "/fact/3") == "involved_in" and pointer_get(e, "/check/counters/new_subject") == 0
    e2 = pointer_set(e, "/fact/3", "NOT|involved_in")
    assert e2["fact"][3] == "NOT|involved_in" and e["fact"][3] == "involved_in"
    assert pointer_set({"a~b": {"c/d": 1}}, "/a~0b/c~1d", 2) == {"a~b": {"c/d": 2}}
    assert pointer_get({"x": 1}, "") == {"x": 1}
    with pytest.raises(KeyError):
        pointer_get(e, "/nope")


def test_ledger_error_serializes_exactly_seven_keys_and_the_code_table_is_closed():
    err = LedgerError(LC.LEDGER_BAD_TAXON, "m", "/fact/12", got="x", options=("b", "a"))
    d = err.to_dict()
    assert set(d) == {"code", "message", "field", "got", "fix", "options", "context"}
    assert d["options"] == ["a", "b"] and d["fix"] is None and d["context"] is None
    assert json.dumps(d)
    assert LC.LEDGER_MALFORMED in ALL_LEDGER_CODES and len(ALL_LEDGER_CODES) == 39
    exc = LedgerIntegrityError([err])
    assert exc.to_json() == {"errors": [d]} and exc.errors == [err]


def test_ledger_and_verifier_modules_import_no_network_or_bench_module():
    # Spec section 0.1: the trusted base stays one thing. Break: `from methods_graph.fetch import ...`
    # anywhere under biolean/ledger, sshsig.py, ed25519.py or store.py.
    import re
    from pathlib import Path
    import methods_graph.biolean as pkg
    root = Path(pkg.__file__).parent
    files = [root / "ed25519.py", root / "sshsig.py", root / "store.py", *sorted((root / "ledger").glob("*.py"))]
    banned = re.compile(r"^\s*(from|import)\s+methods_graph\.(fetch|bench|biolean\.bench)\b", re.M)
    for f in files:
        assert not banned.search(f.read_text(encoding="utf-8")), f
    assert len(files) >= 4
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_ledger_format.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.ledger'`.

- [ ] **Step 3: Implement `errors.py`**

`src/methods_graph/biolean/ledger/errors.py`:

```python
"""Ledger error codes and the seven-key error object every ledger rejection carries (spec §7).

This is not the kernel's six-key ``Error``; no kernel error is ever passed through. ``fix``
is ``None`` or exactly one JSON value that clears the error when written at ``field``;
``options`` lists complete candidate values for ``field``; ``context`` is never substituted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class LedgerCode:
    # body faults: exit 3, the caller can change the body
    LEDGER_BAD_BODY = "LEDGER_BAD_BODY"
    LEDGER_BAD_COLUMNS = "LEDGER_BAD_COLUMNS"
    LEDGER_VERSION = "LEDGER_VERSION"
    LEDGER_BAD_KIND = "LEDGER_BAD_KIND"
    LEDGER_BAD_CHARACTER = "LEDGER_BAD_CHARACTER"
    LEDGER_BAD_SUBJECT = "LEDGER_BAD_SUBJECT"
    UNKNOWN_TERM = "UNKNOWN_TERM"
    LEDGER_ALT_ID = "LEDGER_ALT_ID"
    OBSOLETE_TERM = "OBSOLETE_TERM"
    LEDGER_ASPECT_MISMATCH = "LEDGER_ASPECT_MISMATCH"
    UNKNOWN_QUALIFIER = "UNKNOWN_QUALIFIER"
    QUALIFIER_ASPECT_MISMATCH = "QUALIFIER_ASPECT_MISMATCH"
    LEDGER_ECO_UNMAPPED = "LEDGER_ECO_UNMAPPED"
    LEDGER_BAD_REFERENCE = "LEDGER_BAD_REFERENCE"
    LEDGER_REFERENCE_REQUIRED = "LEDGER_REFERENCE_REQUIRED"
    LEDGER_BAD_TAXON = "LEDGER_BAD_TAXON"
    LEDGER_BAD_DATE = "LEDGER_BAD_DATE"
    LEDGER_BAD_OBJECT_TYPE = "LEDGER_BAD_OBJECT_TYPE"
    LEDGER_ASSIGNED_BY = "LEDGER_ASSIGNED_BY"
    LEDGER_MALFORMED = "LEDGER_MALFORMED"
    LEDGER_DUPLICATE = "LEDGER_DUPLICATE"
    LEDGER_DERIVATION_REJECTED = "LEDGER_DERIVATION_REJECTED"
    LEDGER_SORRY_USED = "LEDGER_SORRY_USED"
    LEDGER_SORRY_UNUSED = "LEDGER_SORRY_UNUSED"
    LEDGER_CONCLUSION_MISMATCH = "LEDGER_CONCLUSION_MISMATCH"
    NOT_YET_DISCHARGEABLE = "NOT_YET_DISCHARGEABLE"
    LEDGER_BAD_COMPUTED = "LEDGER_BAD_COMPUTED"
    # integrity and environment: exit 2, raised inside LedgerIntegrityError
    LEDGER_BASE_MISMATCH = "LEDGER_BASE_MISMATCH"
    LEDGER_SIGNERS_MISMATCH = "LEDGER_SIGNERS_MISMATCH"
    LEDGER_WRONG_LEDGER = "LEDGER_WRONG_LEDGER"
    LEDGER_SIGNER_MISMATCH = "LEDGER_SIGNER_MISMATCH"
    LEDGER_UNKNOWN_SIGNER = "LEDGER_UNKNOWN_SIGNER"
    LEDGER_BAD_SIGNATURE = "LEDGER_BAD_SIGNATURE"
    LEDGER_CHAIN_BROKEN = "LEDGER_CHAIN_BROKEN"
    LEDGER_INVALID_ENTRY = "LEDGER_INVALID_ENTRY"
    LEDGER_ROLLBACK = "LEDGER_ROLLBACK"
    LEDGER_UNSUPPORTED_KEY = "LEDGER_UNSUPPORTED_KEY"
    LEDGER_KEY16_COLLISION = "LEDGER_KEY16_COLLISION"
    LEDGER_SIGNING_FAILED = "LEDGER_SIGNING_FAILED"


ALL_LEDGER_CODES: frozenset[str] = frozenset(
    v for k, v in vars(LedgerCode).items() if k.isupper() and isinstance(v, str))

# No change to the body clears these; a retry loop must stop on them (spec §7).
TERMINAL_CODES: frozenset[str] = frozenset({
    LedgerCode.NOT_YET_DISCHARGEABLE, LedgerCode.LEDGER_DUPLICATE, LedgerCode.LEDGER_BASE_MISMATCH})

# §2 checks that do not depend on the base: a signed entry failing one of these is
# LEDGER_INVALID_ENTRY whatever base it names (spec §3, base binding).
BASE_INDEPENDENT_CODES: frozenset[str] = frozenset({
    LedgerCode.LEDGER_BAD_COLUMNS, LedgerCode.LEDGER_VERSION, LedgerCode.LEDGER_BAD_KIND,
    LedgerCode.LEDGER_BAD_CHARACTER, LedgerCode.LEDGER_BAD_SUBJECT, LedgerCode.UNKNOWN_QUALIFIER,
    LedgerCode.LEDGER_BAD_REFERENCE, LedgerCode.LEDGER_REFERENCE_REQUIRED, LedgerCode.LEDGER_BAD_TAXON,
    LedgerCode.LEDGER_BAD_DATE, LedgerCode.LEDGER_BAD_OBJECT_TYPE, LedgerCode.LEDGER_ASSIGNED_BY,
    LedgerCode.LEDGER_MALFORMED})


@dataclass(frozen=True)
class LedgerError:
    code: str
    message: str
    field: str | None
    got: Any = None
    fix: Any = None
    options: tuple[Any, ...] = ()
    context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "field": self.field, "got": self.got,
                "fix": self.fix, "options": sorted(self.options, key=str), "context": self.context}


class LedgerIntegrityError(Exception):
    """Raised when a ledger cannot be trusted or an append cannot proceed: exit 2, nothing loads."""

    def __init__(self, errors: list[LedgerError]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(f"{e.code}: {e.message}" for e in self.errors))

    def to_json(self) -> dict[str, Any]:
        return {"errors": [e.to_dict() for e in self.errors]}
```

- [ ] **Step 4: Implement `format.py`**

`src/methods_graph/biolean/ledger/format.py`:

```python
"""The entry format (spec §1): canonical bytes, entry hash, the field schema, the character
rules of §2 step 1a, and the RFC 6901 pointers the error payload uses."""
from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import re
import unicodedata
from typing import Any

from methods_graph.biolean.gaf import GAF_COLUMNS
from methods_graph.biolean.ledger.errors import LedgerCode, LedgerError
from methods_graph.biolean.props import Prop

FORMAT_VERSION = 1
KINDS: tuple[str, ...] = ("axiom", "derived", "computed")
COMMON_FIELDS: tuple[str, ...] = ("v", "kind", "ledger", "base", "check", "prev", "by", "ts", "sig")
KIND_FIELDS: dict[str, tuple[str, ...]] = {
    "axiom": ("fact",),
    "derived": ("derivation", "conclusion"),
    "computed": ("method", "dataset", "graph_hash", "preconditions", "run", "conclusion"),
}
OPTIONAL_FIELDS: tuple[str, ...] = ("admission",)
RELEASE_KEYS: tuple[str, ...] = ("go_basic_data_version", "goa_date_generated", "goa_go_version")
ASSIGNED_BY_PREFIX = "biolean:"
# Columns 1, 2, 4-9 and 13-17: printable ASCII 0x21-0x7E only, when non-empty (spec §2 step 1a).
ASCII_COLUMNS: frozenset[int] = frozenset({0, 1, 3, 4, 5, 6, 7, 8, 12, 13, 14, 15, 16})

# `\Z`, not `$`: `$` also matches just before a final "\n", so "<64 hex>\n" would pass.
# `[0-9]`, not `\d`: `\d` (and strptime) accept any Unicode digit, e.g. U+0662.
TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
HEX64_RE = re.compile(r"^[0-9a-f]{64}\Z")
LEDGER_ID_RE = re.compile(r"^[0-9a-f]{32}\Z")
BY_RE = re.compile(r"^sha256:[0-9a-f]{64}\Z")
FILE_RE = re.compile(r"^[0-9a-f]{16}\.jsonl\Z")
# Deepest container nesting canon() writes and parse_line() reads. A legitimate entry is a few
# levels deep; the bound keeps every recursive walk of an entry far from the interpreter's limit.
MAX_DEPTH = 64
_TOO_DEEP = f"nesting deeper than {MAX_DEPTH} levels"

_AXIOM_CHECK_REQUIRED = ("kernel", "annotation_id", "contested_by", "counters")
_DERIVED_CHECK_REQUIRED = ("kernel", "axioms", "conflicts")
_CHECK_OPTIONAL = ("reference_resolved",)


# ---------------------------------------------------------------------------
# canonical bytes
# ---------------------------------------------------------------------------

def nesting_depth(obj: Any) -> int:
    """Container depth, capped: a scalar is 0, ``{"a": 1}`` is 1, ``{"a": [1]}`` is 2, and anything
    deeper than MAX_DEPTH is MAX_DEPTH + 1. Iterative (an explicit stack), and the walk stops as
    soon as it passes MAX_DEPTH, so neither a deep nor a cyclic object can hang or overflow it."""
    deepest = 0
    stack: list[tuple[Any, int]] = [(obj, 0)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            children: Any = node.values()
        elif isinstance(node, (list, tuple)):
            children = node
        else:
            continue
        depth += 1
        if depth > MAX_DEPTH:
            return MAX_DEPTH + 1
        deepest = max(deepest, depth)
        stack.extend((child, depth) for child in children)
    return deepest


def canon(obj: Any) -> bytes:
    """Compact, key-sorted, ASCII JSON. Refuses NaN/Infinity and nesting deeper than MAX_DEPTH
    (ValueError), so nothing unreadable by parse_line is ever hashed or written."""
    if nesting_depth(obj) > MAX_DEPTH:
        raise ValueError(_TOO_DEEP)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def unsigned(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k != "sig"}


def entry_hash(entry: dict[str, Any]) -> str:
    return hashlib.sha256(canon(unsigned(entry))).hexdigest()


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not allowed")


def parse_line(raw: bytes) -> tuple[Any, str | None]:
    """``(obj, None)`` when ``raw`` is exactly ``canon(obj) + b"\\n"``; else ``(None, reason)``.

    Re-serializing is how key-order and whitespace tampering is caught without a parser of
    its own; a duplicate key collapses on re-serialization and so fails the same way. Nesting
    deeper than MAX_DEPTH is refused whether ``json.loads`` overflows on it or not.
    """
    if not raw.endswith(b"\n"):
        return None, "line does not end with a newline"
    body = raw[:-1]
    if b"\r" in body:
        return None, "carriage return in line"
    if not body.strip():
        return None, "blank line"
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError:
        return None, "non-ASCII byte in line"
    try:
        obj = json.loads(text, parse_constant=_reject_constant)
    except RecursionError:
        return None, _TOO_DEEP
    except ValueError as exc:
        return None, f"not JSON: {exc}"
    if nesting_depth(obj) > MAX_DEPTH:
        return None, _TOO_DEEP
    try:
        again = canon(obj)
    except ValueError as exc:  # json.loads reads 1e999 as inf, which canon refuses to write
        return None, f"not canonical JSON: {exc}"
    if again != body:
        return None, "not canonical JSON (key order, whitespace or number form)"
    return obj, None


# ---------------------------------------------------------------------------
# field schema (spec §1 "Fields")
# ---------------------------------------------------------------------------

def _is_int(x: Any) -> bool:
    return type(x) is int


def _malformed(field: str, message: str, got: Any = None) -> LedgerError:
    return LedgerError(LedgerCode.LEDGER_MALFORMED, message, field, got=got)


def _str_list(x: Any) -> bool:
    return isinstance(x, list) and all(isinstance(s, str) for s in x)


def _check_block_ok(kind: str, chk: Any) -> bool:
    if not isinstance(chk, dict):
        return False
    if kind == "computed":
        return True
    required = _AXIOM_CHECK_REQUIRED if kind == "axiom" else _DERIVED_CHECK_REQUIRED
    if set(chk) - set(required) - set(_CHECK_OPTIONAL) or any(k not in chk for k in required):
        return False
    if not isinstance(chk["kernel"], str):
        return False
    if kind == "axiom":
        counters = chk["counters"]
        return (isinstance(chk["annotation_id"], str) and _str_list(chk["contested_by"])
                and isinstance(counters, dict) and set(counters) == {"new_subject"}
                and _is_int(counters["new_subject"]))
    return _str_list(chk["axioms"]) and _str_list(chk["conflicts"])


def _base_ok(base: Any) -> bool:
    if not isinstance(base, dict) or set(base) != {"obo", "gaf", "eco", "release"}:
        return False
    if not all(isinstance(base[k], str) and HEX64_RE.match(base[k]) for k in ("obo", "gaf", "eco")):
        return False
    release = base["release"]
    return (isinstance(release, dict) and set(release) == set(RELEASE_KEYS)
            and all(isinstance(release[k], str) for k in RELEASE_KEYS))


def _ts_ok(ts: Any) -> bool:
    if not isinstance(ts, str) or not TS_RE.match(ts):
        return False
    try:
        _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def shape_errors(
    entry: Any, *, ledger_id: str | None = None,
    unknown_kind_code: str = LedgerCode.LEDGER_BAD_KIND,
) -> list[LedgerError]:
    """Exactly the §1 fields for the entry's kind, with the right JSON types. Body semantics
    (§2) are not checked here. Integrity passes ``unknown_kind_code=LEDGER_MALFORMED``."""
    if not isinstance(entry, dict):
        return [_malformed("", "entry must be a JSON object", entry)]
    errs: list[LedgerError] = []
    v = entry.get("v")
    if not (_is_int(v) and v == FORMAT_VERSION):
        errs.append(LedgerError(LedgerCode.LEDGER_VERSION, "v must be the JSON integer 1", "/v",
                                got=v, fix=FORMAT_VERSION))
    kind = entry.get("kind")
    kind_known = isinstance(kind, str) and kind in KINDS
    if not kind_known:
        errs.append(LedgerError(unknown_kind_code, "kind must be axiom, derived or computed", "/kind",
                                got=kind, options=tuple(sorted(KINDS))))
    expected = COMMON_FIELDS + (KIND_FIELDS[kind] if kind_known else ())
    for k in expected:
        if k not in entry:
            errs.append(_malformed(f"/{k}", f"missing field {k}"))
    # With an unknown kind, any kind's own fields are not reported as extra: the kind error is the fix.
    tolerated = set(OPTIONAL_FIELDS) | (set() if kind_known else {f for fs in KIND_FIELDS.values() for f in fs})
    for k in sorted(set(entry) - set(expected) - tolerated):
        errs.append(_malformed(f"/{k}", f"unknown field {k}", entry[k]))
    if "admission" in entry and not isinstance(entry["admission"], dict):
        errs.append(_malformed("/admission", "admission must be an object", entry["admission"]))
    if "ledger" in entry:
        lid = entry["ledger"]
        if not (isinstance(lid, str) and LEDGER_ID_RE.match(lid)):
            errs.append(_malformed("/ledger", "ledger must be 32 lowercase hex", lid))
        elif ledger_id is not None and lid != ledger_id:
            errs.append(LedgerError(LedgerCode.LEDGER_WRONG_LEDGER,
                                    f"entry belongs to ledger {lid}, this directory is {ledger_id}",
                                    "/ledger", got=lid, context={"ledger": ledger_id}))
    if "base" in entry and not _base_ok(entry["base"]):
        errs.append(_malformed("/base", "base must be {obo, gaf, eco: 64 hex, release: {3 strings}}", entry["base"]))
    if "check" in entry and kind_known and not _check_block_ok(kind, entry["check"]):
        errs.append(_malformed("/check", f"check has the wrong shape for kind {kind}", entry["check"]))
    if "prev" in entry:
        prev = entry["prev"]
        if not (isinstance(prev, str) and (prev == "" or HEX64_RE.match(prev))):
            errs.append(_malformed("/prev", "prev must be \"\" or 64 lowercase hex", prev))
    if "by" in entry and not (isinstance(entry["by"], str) and BY_RE.match(entry["by"])):
        errs.append(_malformed("/by", "by must be sha256:<64 hex>", entry["by"]))
    if "ts" in entry and not _ts_ok(entry["ts"]):
        errs.append(_malformed("/ts", "ts must be YYYY-MM-DDTHH:MM:SSZ, a real UTC instant", entry["ts"]))
    if "sig" in entry and not isinstance(entry["sig"], str):
        errs.append(_malformed("/sig", "sig must be a string", entry["sig"]))
    if kind == "axiom" and "fact" in entry:
        fact = entry["fact"]
        if not (isinstance(fact, list) and len(fact) == len(GAF_COLUMNS) and all(isinstance(c, str) for c in fact)):
            errs.append(_malformed("/fact", "fact must be 17 string columns", fact))
    if kind == "derived":
        if "derivation" in entry and not isinstance(entry["derivation"], dict):
            errs.append(_malformed("/derivation", "derivation must be an object", entry["derivation"]))
        if "conclusion" in entry and Prop.from_dict(entry["conclusion"]) is None:
            errs.append(_malformed("/conclusion", "conclusion must be a Prop", entry["conclusion"]))
    if kind == "computed":
        for k, typ in (("method", str), ("dataset", dict), ("graph_hash", str), ("preconditions", list),
                       ("run", dict), ("conclusion", dict)):
            if k in entry and not isinstance(entry[k], typ):
                errs.append(_malformed(f"/{k}", f"{k} must be a JSON {typ.__name__}", entry[k]))
    return errs


# ---------------------------------------------------------------------------
# characters (spec §2 step 1a)
# ---------------------------------------------------------------------------

_FORBIDDEN_CATEGORIES = frozenset({"Cf", "Zl", "Zp"})


def _is_surrogate(ch: str) -> bool:
    return 0xD800 <= ord(ch) <= 0xDFFF


def _forbidden_in_column(ch: str) -> bool:
    o = ord(ch)
    return (o < 0x20 or 0x7F <= o <= 0x9F or o in (0x2028, 0x2029)
            or unicodedata.category(ch) in _FORBIDDEN_CATEGORIES)


def _bad(ch: str, *, column: bool, ascii_only: bool) -> bool:
    if _is_surrogate(ch):
        return True
    if column and _forbidden_in_column(ch):
        return True
    return ascii_only and not (0x21 <= ord(ch) <= 0x7E)


def string_fault(s: str, *, column: bool = False, ascii_only: bool = False) -> str | None:
    """The first offending code point as ``U+XXXX``, or None. Order: surrogates and forbidden
    characters first, then the first position where NFC differs."""
    for ch in s:
        if _bad(ch, column=column, ascii_only=ascii_only):
            return f"U+{ord(ch):04X}"
    nfc = unicodedata.normalize("NFC", s)
    if nfc != s:
        for a, b in zip(s, nfc):
            if a != b:
                return f"U+{ord(a):04X}"
        return f"U+{ord(s[len(nfc)]):04X}" if len(s) > len(nfc) else f"U+{ord(s[-1]):04X}"
    return None


def clean_string(s: str, *, column: bool = False, ascii_only: bool = False) -> str:
    kept = "".join(ch for ch in s if not _bad(ch, column=column, ascii_only=ascii_only))
    return unicodedata.normalize("NFC", kept)


def column_character_error(i: int, value: str) -> LedgerError | None:
    """§2 step 1a for GAF column ``i`` (0-based). The fix is the cleaned value."""
    ascii_only = i in ASCII_COLUMNS
    got = string_fault(value, column=True, ascii_only=ascii_only)
    if got is None:
        return None
    return LedgerError(LedgerCode.LEDGER_BAD_CHARACTER,
                       f"column {i + 1} ({GAF_COLUMNS[i]}) contains {got}"
                       + (" (printable ASCII only)" if ascii_only else ""),
                       f"/fact/{i}", got=got, fix=clean_string(value, column=True, ascii_only=ascii_only))


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _walk_strings(node: Any, pointer: str, out: list[tuple[str, str, bool]]) -> None:
    """Collect ``(pointer, string, is_key)``. A key is collected at the pointer of the object
    that holds it; a value at its own pointer."""
    if isinstance(node, str):
        out.append((pointer, node, False))
    elif isinstance(node, dict):
        for k in sorted(node):
            out.append((pointer, k, True))
            _walk_strings(node[k], f"{pointer}/{_escape(k)}", out)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk_strings(item, f"{pointer}/{i}", out)


def character_errors(entry: Any) -> list[LedgerError]:
    """Every string in the entry, keys included, must encode to UTF-8 and be NFC; fact columns
    also obey the column rules. Runs on every line at verify (spec §3 step 2) and at append.
    A bad key has ``fix`` None: renaming a key is not a value ``pointer_set`` can write."""
    errs: list[LedgerError] = []
    strings: list[tuple[str, str, bool]] = []
    _walk_strings(entry, "", strings)
    fact = entry.get("fact") if isinstance(entry, dict) else None
    fact_ok = isinstance(fact, list)
    for pointer, value, is_key in strings:
        if is_key:
            got = string_fault(value)
            if got is not None:
                errs.append(LedgerError(LedgerCode.LEDGER_BAD_CHARACTER,
                                        f"key {value!r} at {pointer or 'the top level'} contains {got}",
                                        pointer, got=got, fix=None))
            continue
        if fact_ok and pointer.startswith("/fact/") and pointer.count("/") == 2:
            idx = int(pointer[6:])
            err = column_character_error(idx, value) if idx < len(GAF_COLUMNS) else None
            if err is not None:
                errs.append(err)
            continue
        got = string_fault(value)
        if got is not None:
            errs.append(LedgerError(LedgerCode.LEDGER_BAD_CHARACTER, f"{pointer} contains {got}",
                                    pointer, got=got, fix=clean_string(value)))
    return errs


# ---------------------------------------------------------------------------
# RFC 6901
# ---------------------------------------------------------------------------

def _tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"pointer must start with '/': {pointer!r}")
    return [t.replace("~1", "/").replace("~0", "~") for t in pointer.split("/")[1:]]


def pointer_get(obj: Any, pointer: str) -> Any:
    cur = obj
    for tok in _tokens(pointer):
        if isinstance(cur, list):
            cur = cur[int(tok)]
        elif isinstance(cur, dict):
            cur = cur[tok]
        else:
            raise KeyError(pointer)
    return cur


def pointer_set(obj: Any, pointer: str, value: Any) -> Any:
    """A deep copy of ``obj`` with ``value`` at ``pointer`` (an RFC 6901 replace)."""
    out = copy.deepcopy(obj)
    toks = _tokens(pointer)
    if not toks:
        return copy.deepcopy(value)
    parent = pointer_get(out, "/" + "/".join(_escape(t) for t in toks[:-1])) if len(toks) > 1 else out
    last = toks[-1]
    if isinstance(parent, list):
        parent[int(last)] = value
    else:
        parent[last] = value
    return out
```

- [ ] **Step 5: Run the tests**

Run: `$PYTEST tests/test_biolean_ledger_format.py -q`
Expected: 13 passed.

Mutation checks: (a) `parse_line`: return `(obj, None)` without the `canon(obj) != body` comparison: four of the eleven reason cases parse (the ones whose bytes are valid JSON). (b) `shape_errors`: `v == 1` instead of `_is_int(v) and v == 1`: `test_version_true_or_float_is_ledger_version` fails on `True` and `1.0`. (c) `_bad`: drop the surrogate branch: the `\ud800` case at `/ts` silently passes, so its `[err] =` unpack fails (the `/fact/16` surrogate case does not detect this edit: column 17 is ASCII-only and that check fires first). (d) `_forbidden_in_column`: drop `Zl` from `_FORBIDDEN_CATEGORIES` *and* the explicit `(0x2028, 0x2029)` pair: the U+2028 case fails (its `[err] =` unpack gets nothing). Either edit alone survives, because U+2028 is the only `Zl` character and the two guards mask each other; the explicit pair stays because spec §2 step 1a names U+2028/U+2029 by code point. (e) drop `Cf` from `_FORBIDDEN_CATEGORIES`: the U+200B case fails. Fix-round checks (controller rulings after the first commit; code above is the corrected code): `\Z` → `$` in `HEX64_RE`: `test_a_trailing_newline_is_malformed` fails at `/prev` (the same edit in `BY_RE`, `LEDGER_ID_RE` and `FILE_RE` fails at its own case; in `TS_RE` it is an equivalent mutant, `strptime` refuses the leftover newline, so the `/ts` case is a pin); `[0-9]` → `\d` in `TS_RE`: `test_impossible_ts_is_malformed_by_shape` fails on the Arabic-Indic case (`strptime` accepts those digits); drop `canon`'s depth check: `test_canon_refuses_nesting_deeper_than_max_depth` fails (did not raise); drop `parse_line`'s: `test_parse_line_refuses_nesting_deeper_than_max_depth` fails (the guard turns canon's refusal into "not canonical JSON: nesting deeper than 64 levels", which the exact-reason assertion catches); drop the `RecursionError` catch in `parse_line`: the same test fails at its 1,000,000-deep line (Python 3.14's `json.loads` decodes 100,000 levels; 3.12 raises at both); make `nesting_depth` recursive: its test and the canon test fail with RecursionError at 100,000 deep; skip keys in `_walk_strings`: `test_character_errors_check_dict_keys_at_the_containing_object` fails. Mutation drivers must give each run a fresh bytecode cache (`PYTHONPYCACHEPREFIX`): same-size edits within one second reuse a stale `.pyc`. Round 2 (review finding: `parse_line` raised ValueError on `1e999`/`-1e400`, which `json.loads` reads as ±inf and `canon` refuses): drop the `try` around `canon(obj)` in `parse_line`: `test_parse_line_accepts_only_canonical_lines` raises ValueError at the `1e999` case; remove the early stop in `nesting_depth`: `test_nesting_depth_counts_containers_iteratively` fails at the 100,000-deep assertion (`65 == 100000`), and run alone from a shell under `timeout` the cyclic case never returns.

- [ ] **Step 6: Add the import-boundary test**

Append to `tests/test_biolean_ledger_format.py`:

```python
# Folded into the Step 1 block above: the committed test module already holds
# test_ledger_and_verifier_modules_import_no_network_or_bench_module (synced after the Task 5 fix round).
```

Run: `$PYTEST tests/test_biolean_ledger_format.py -q` → 14 passed.

- [ ] **Step 7: Commit**

```bash
git add src/methods_graph/biolean/ledger/__init__.py src/methods_graph/biolean/ledger/errors.py src/methods_graph/biolean/ledger/format.py tests/test_biolean_ledger_format.py
git commit -m "feat(biolean-ledger): error shape, canonical bytes, field schema, character rules

The seven-key LedgerError (spec §7), the 39 codes, canon()/entry_hash(),
parse_line (a line is exactly canon(obj)+newline), shape_errors (spec §1
fields per kind), the §2 step 1a character rules, and RFC 6901 helpers.

mutation checked: comparing parsed JSON instead of bytes in parse_line lets
reordered keys through; `v == 1` accepts True and 1.0."
```

---

### Task 6: `ledger/check.py`: the §2 append check, with the ledger fixture base

**Files:**
- Create: `src/methods_graph/biolean/ledger/check.py`
- Create: `tests/fixtures/biolean/ledger/ledger.obo`, `ledger.gaf`, `ledger-eco.txt`
- Create: `tests/biolean_ledger_fixture.py` (Task 8 extends it)
- Test: `tests/test_biolean_ledger_check.py`

**Interfaces:**
- Consumes: `kernel.check_term`, `kernel.check_qualifier_aspect`, `kernel.check`, `elaborate.elaborate`, `gaf.parse_gaf`, `gaf.annotation_id`, `gaf.GAF_COLUMNS`, `format.column_character_error`, `format.ASSIGNED_BY_PREFIX`, `errors.LedgerError`, `errors.LedgerCode`, `store.FactStore`, `store.BaseLoad`, `props.*`.
- Produces (`methods_graph.biolean.ledger.check`):
  - `CheckContext(store, eco_map, primary_id, term, key16, ledger_sources={}, kernel_version=methods_graph.__version__)` dataclass. `ledger_sources` maps an admitted ledger annotation id to `"ledger/<key16>.jsonl:<line>"`; `store` is base plus admitted ledger facts at append time.
  - `AxiomResult(errors, deferred, fact, annotation, check, counters, gaf_report)` with `.ok`.
  - `DerivedResult(errors, derivation, conclusion, check)` with `.ok`.
  - `fact_from_body(body) -> tuple[list[str] | None, list[LedgerError]]`.
  - `check_axiom(fact, ctx, *, mode="append" | "recheck") -> AxiomResult`. `append`: steps 1–9 with fix application, column 15 filled, `deferred` per refinement 2. `recheck`: steps 1–7a on the row as signed, no fixes applied, column 15 must equal `biolean:<ctx.key16>`, `annotation` set whenever the row round-trips (used by Task 7's base binding).
  - `check_derived(body, ctx) -> DerivedResult`.
  - `check_computed(body, ctx) -> list[LedgerError]` (always ends with `NOT_YET_DISCHARGEABLE`).
  - `content_key(a: Annotation) -> tuple`, `content_key_json(a) -> list`.
  - `term_errors(term_id, store, field) -> list[LedgerError]`, `qualifier_options(aspect: str | None, prefix="") -> tuple[str, ...]`.
- Produces (`tests/biolean_ledger_fixture.py`): `LFIX`, `KEY_A`, `KEY_B`, `PUB_A`, `PUB_B`, `KEY16_A`, `KEY16_B`, `DIGEST_A`, `DIGEST_B`, `BY_A`, `BY_B`, `TS`, `LEDGER_ID`, `BASE_FILES`, `RELEASE`, `ledger_base() -> BaseLoad`, `ledger_store() -> StaticFactStore`, `copy_ledger_store(dest) -> Path`, `context(key16, *, store=None, sources=None, base=None) -> CheckContext`, `new_fact(**overrides) -> list[str]`, `base_row(n) -> list[str]`.

- [ ] **Step 1: Write the fixture base**

`tests/fixtures/biolean/ledger/ledger.obo`:

```
format-version: 1.2
data-version: releases/2026-02-02
ontology: go-ledger

[Term]
id: GO:0000001
name: root process
namespace: biological_process

[Term]
id: GO:0000002
name: process child
namespace: biological_process
alt_id: GO:0000102
is_a: GO:0000001 ! root process

[Term]
id: GO:0000003
name: process grandchild
namespace: biological_process
is_a: GO:0000002 ! process child

[Term]
id: GO:0000010
name: obsolete old child
namespace: biological_process
alt_id: GO:0000110
is_obsolete: true
replaced_by: GO:0000002

[Term]
id: GO:0000011
name: obsolete moved to function
namespace: biological_process
is_obsolete: true
replaced_by: GO:0000021

[Term]
id: GO:0000012
name: obsolete with considers
namespace: biological_process
alt_id: GO:0000112
is_obsolete: true
consider: GO:0000002
consider: GO:0000003
consider: GO:0000999

[Term]
id: GO:0000013
name: obsolete orphan
namespace: biological_process
is_obsolete: true

[Term]
id: GO:0000014
name: obsolete with two replacements
namespace: biological_process
is_obsolete: true
replaced_by: GO:0000002
replaced_by: GO:0000003

[Term]
id: GO:0000020
name: root function
namespace: molecular_function

[Term]
id: GO:0000021
name: function child
namespace: molecular_function
is_a: GO:0000020 ! root function

[Typedef]
id: part_of
name: part of
```

`tests/fixtures/biolean/ledger/ledger.gaf` (columns are TAB-separated; the Write tool must emit real tabs; check with `awk -F'\t' '!/^!/{print NF}' ledger.gaf` printing `17` ten times):

```
!gaf-version: 2.2
!generated-by: biolean-ledger-fixture
!date-generated: 2026-02-02
!go-version: http://purl.obolibrary.org/obo/go/releases/2026-02-02/extensions/go-plus.ofn
UniProtKB	P10001	G1	involved_in	GO:0000002	PMID:100|PMID:99	IDA		P	gene one		protein	taxon:9606	20200101	UniProt		
UniProtKB	P10001	G1	involved_in	GO:0000002	PMID:100|PMID:99	IDA		P	gene one		protein	taxon:9606	20200101	MGI		
UniProtKB	P10001	G1	NOT|involved_in	GO:0000003	PMID:101	IDA		P	gene one		protein	taxon:9606	20200101	UniProt		
UniProtKB	P10002	G2	involved_in	GO:0000001	PMID:102	IMP		P	gene two		protein	taxon:9606	20200101	UniProt		
UniProtKB	P10002	G2	enables	GO:0000021	PMID:103	IDA		F	gene two		protein	taxon:9606	20200101	UniProt		
UniProtKB	P10003	G3	involved_in	GO:0000003	PMID:104	IDA		P	gene three		protein	taxon:9606	20200101	UniProt		
UniProtKB	P10003	G3	enables	GO:0000020	PMID:105	IPI	UniProtKB:P10002	F	gene three		protein	taxon:9606	20200101	UniProt		
UniProtKB	P10004	G4	involved_in	GO:0000002	GO_REF:0000002	IEA		P	gene four		protein	taxon:9606	20260101	UniProt		
UniProtKB	P10004	G4	involved_in	GO:0000003	PMID:106	IDA		P	gene four		protein	taxon:9606	20200101	UniProt		
UniProtKB	P10005	G5	involved_in	GO:0000001	PMID:108	IDA		P	gene five		protein	taxon:9606|taxon:562	20200101	UniProt		
```

Rows 1 and 2 differ only in column 15 (`UniProt` / `MGI`); row 3 is the NOT row at `(P10001, involved_in, GO:0000003)`; row 10 carries two taxa. Each line ends with two empty columns, so it ends in two tabs.

`tests/fixtures/biolean/ledger/ledger-eco.txt`:

```
# ledger fixture mapping: four codes
IDA	Default	ECO:0000314
IMP	Default	ECO:0000315
IPI	Default	ECO:0000353
IEA	Default	ECO:0000501
```

- [ ] **Step 2: Write the fixture module**

`tests/biolean_ledger_fixture.py`:

```python
"""Fixture inventory for the ledger tests: the ledger base, the two keys, helpers.

Task 8 adds the fake runner, the signed ledger copies and the append scenarios.
"""
from pathlib import Path
import shutil

from methods_graph.biolean.gaf import GAF_COLUMNS
from methods_graph.biolean.ledger.check import CheckContext
from methods_graph.biolean.store import BaseLoad, StaticFactStore, load_base

LFIX = Path(__file__).parent / "fixtures" / "biolean" / "ledger"
KEY_A, KEY_B = LFIX / "keys" / "a", LFIX / "keys" / "b"
PUB_A, PUB_B = LFIX / "keys" / "a.pub", LFIX / "keys" / "b.pub"
KEY16_A, KEY16_B = "1438014318807ad1", "778b5c6aae736dad"
DIGEST_A = "1438014318807ad1a74d1943c05793434d3cbd11009797a646bbc3cd68c7c51e"
DIGEST_B = "778b5c6aae736dad91e838b21ac186bf8590c64cf94e73db1c27c69c53de34d0"
BY_A, BY_B = "sha256:" + DIGEST_A, "sha256:" + DIGEST_B
TS = "2026-09-25T10:00:00Z"
LEDGER_ID = "0123456789abcdef0123456789abcdef"
BASE_FILES = {"obo": "ledger.obo", "gaf": "ledger.gaf", "eco": "ledger-eco.txt"}
RELEASE = {"go_basic_data_version": "releases/2026-02-02", "goa_date_generated": "2026-02-02",
           "goa_go_version": "http://purl.obolibrary.org/obo/go/releases/2026-02-02/extensions/go-plus.ofn"}


def ledger_base() -> BaseLoad:
    return load_base(LFIX, **BASE_FILES)


def ledger_store() -> StaticFactStore:
    base = ledger_base()
    return StaticFactStore(base.terms, base.edges, base.annotations)


def copy_ledger_store(dest: Path) -> Path:
    """The fixture base under the names `mg biolean --store` expects (plain GAF, not gz)."""
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(LFIX / "ledger.obo", dest / "go-basic.obo")
    shutil.copy(LFIX / "ledger.gaf", dest / "goa_human.gaf")
    shutil.copy(LFIX / "ledger-eco.txt", dest / "gaf-eco-mapping.txt")
    return dest


def context(key16: str = KEY16_A, *, store=None, sources=None, base: BaseLoad | None = None) -> CheckContext:
    base = base or ledger_base()
    return CheckContext(
        store=store if store is not None else StaticFactStore(base.terms, base.edges, base.annotations),
        eco_map=base.eco_map, primary_id=base.primary_id, term=base.term, key16=key16,
        ledger_sources=dict(sources or {}))


def new_fact(**overrides) -> list[str]:
    """A valid new fact for the fixture base (P10002 involved_in GO:0000003, cited by DOI).
    Keyword names are GAF column names; a value replaces that column."""
    row = ["UniProtKB", "P10002", "G2", "involved_in", "GO:0000003", "DOI:10.1038/s41586-026-00001-0",
           "IDA", "", "P", "", "", "protein", "taxon:9606", "20260925", "", "", ""]
    for name, value in overrides.items():
        row[GAF_COLUMNS.index(name)] = value
    return row


def base_row(n: int) -> list[str]:
    """The n-th (1-based) data row of ledger.gaf as a 17-list."""
    rows = [line.split("\t") for line in (LFIX / "ledger.gaf").read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("!")]
    return rows[n - 1]


# ---------------------------------------------------------------------------
# signing without a subprocess: content-addressed real armor (spec section 9, "No subprocess")
# ---------------------------------------------------------------------------
import hashlib
import types
from dataclasses import dataclass
from typing import Any

from methods_graph.biolean.ledger.append import AppendResult, append_entry, init_ledger
from methods_graph.biolean.sshsig import NAMESPACE, allowed_signers_line, parse_public_key_line

SIGS = LFIX / "sigs"
SIGNED = LFIX / "signed"


def fake_runner(argv, *, input, capture_output, check, **extra):
    """The `runner` seam for tests. Asserts the exact argv, returns armor real ssh-keygen made over
    exactly these bytes. A miss means make_fixtures.py must be re-run."""
    assert extra == {}, f"unexpected runner kwargs {sorted(extra)} (text= would break the armor)"
    assert argv[:4] == ["ssh-keygen", "-Y", "sign", "-f"] and argv[4:] == [argv[4], "-n", NAMESPACE] and len(argv) == 7, argv
    assert capture_output is True and check is True and isinstance(input, bytes)
    path = SIGS / (hashlib.sha256(input).hexdigest() + ".sig")
    assert path.is_file(), (f"no fixture signature for these bytes ({path.name}); the entry, base or "
                            "kernel version changed: run tests/fixtures/biolean/ledger/make_fixtures.py")
    return types.SimpleNamespace(stdout=path.read_bytes(), stderr=b"", returncode=0)


def copy_signed(dest: Path) -> Path:
    shutil.copytree(SIGNED, dest, dirs_exist_ok=True)
    return dest


def signed_store(tmp_path: Path, *, replay: bool = False) -> tuple[Path, Path]:
    """(ledger dir, store dir): a copy of signed/ beside a copy of the base. With replay=True the
    ledger is rebuilt from SIGNED_SEQUENCE through the fake runner instead of copied."""
    store = copy_ledger_store(tmp_path / "store")
    ledger = tmp_path / "ledger"
    if replay:
        build_signed(ledger, store, runner=fake_runner)
    else:
        copy_signed(ledger)
    return ledger, store


@dataclass(frozen=True)
class Scenario:
    kind: str
    body: Any
    key: Path
    start: str          # "fresh" (init a new ledger with key A, list B too) or "signed" (a copy of signed/)
    ts: str = TS


def _fact(**over):
    return new_fact(**over)


# The appends that build signed/: three axioms by A, one axiom by B, one derived by A.
SIGNED_SEQUENCE: tuple[tuple[Path, str, Any], ...] = (
    (KEY_A, "axiom", _fact()),                                                                 # P10002 involved_in GO:0000003, DOI
    (KEY_A, "axiom", _fact(db_object_id="P10006", db_object_symbol="G6", db_reference="DOI:10.1000/ledger.6")),   # new subject
    (KEY_A, "axiom", _fact(db_object_id="P10001", db_object_symbol="G1", db_reference="PMID:300")),               # contested by the NOT row
    (KEY_B, "axiom", _fact(db_object_id="P10004", db_object_symbol="G4", go_id="GO:0000001", db_reference="PMID:400", evidence_code="IMP")),
    (KEY_A, "derived", {"derivation": {"biolean": "0.1",
                                       "goal": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000002", "taxon": "NCBITaxon:9606", "negated": False},
                                       "steps": [{"id": "s1", "rule": "axiom", "conclusion": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000003", "taxon": "NCBITaxon:9606", "negated": False}},
                                                 {"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": ["GO:0000003", "GO:0000002"],
                                                  "conclusion": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000002", "taxon": "NCBITaxon:9606", "negated": False}}],
                                       "root": "s2"}}),
)

# Every accepted append a test performs, by name. Rejected appends never reach the runner.
SCENARIOS: dict[str, Scenario] = {
    "fresh-axiom": Scenario("axiom", _fact(), KEY_A, "fresh"),
    "fresh-axiom-object": Scenario("axiom", dict(zip(GAF_COLUMNS, _fact())), KEY_A, "fresh"),
    "signed-append-a": Scenario("axiom", _fact(db_object_id="P10005", db_object_symbol="G5", go_id="GO:0000002", db_reference="PMID:500"), KEY_A, "signed"),
    "signed-append-b": Scenario("axiom", _fact(db_object_id="P10005", db_object_symbol="G5", go_id="GO:0000002", db_reference="PMID:501"), KEY_B, "signed"),
    "signed-derived-elaborated": Scenario("derived", {"derivation": {"goal": {"subject": "G3", "qualifier": "involved_in", "term": "GO:0000002", "taxon": "taxon:9606", "negated": False},
                                                                     "steps": [{"id": "s1", "rule": "axiom", "conclusion": {"subject": "G3", "qualifier": "involved_in", "term": "GO:0000003", "taxon": "9606", "negated": False}},
                                                                               {"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": ["GO:0000003", "GO:0000002"],
                                                                                "conclusion": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000002", "taxon": "NCBITaxon:9606", "negated": False}}],
                                                                     "root": "s2"}}, KEY_A, "signed"),
    "cli-fresh-axiom": Scenario("axiom", _fact(db_reference="PMID:900"), KEY_A, "fresh"),
    "cli-signed-axiom": Scenario("axiom", _fact(db_object_id="P10005", db_object_symbol="G5", go_id="GO:0000002", db_reference="PMID:502"), KEY_A, "signed"),
}


def fresh_ledger(ledger: Path, store: Path) -> Path:
    """`init` with key A (fixed ledger id), then list key B as well, as the owner would."""
    init_ledger(ledger, store_dir=store, key=PUB_A, principal="fixture-a", gaf="goa_human.gaf", ledger_id=LEDGER_ID,
                allow_fixture_keys=True)
    blob_b, comment_b = parse_public_key_line(PUB_B.read_text())
    with (ledger / "allowed_signers").open("a", encoding="utf-8") as fh:
        fh.write(allowed_signers_line("fixture-b", blob_b, comment_b))
    return ledger


def build_signed(ledger: Path, store: Path, *, runner) -> Path:
    """signed/ from SIGNED_SEQUENCE: init, then the five appends in order."""
    fresh_ledger(ledger, store)
    for key, kind, body in SIGNED_SEQUENCE:
        res = append_entry(ledger, kind=kind, body=body, key=key, ts=TS, runner=runner,
                           store_dir=store, gaf="goa_human.gaf", use_cache=False)
        assert res.verdict == "ACCEPTED", [e.to_dict() for e in res.errors]
    return ledger


def run_scenario(name: str, tmp_path: Path, *, runner=fake_runner) -> tuple[AppendResult, Path, Path]:
    scn = SCENARIOS[name]
    store = copy_ledger_store(tmp_path / "store")
    ledger = tmp_path / "ledger"
    if scn.start == "fresh":
        fresh_ledger(ledger, store)
    else:
        copy_signed(ledger)
    res = append_entry(ledger, kind=scn.kind, body=scn.body, key=scn.key, ts=scn.ts, runner=runner,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    return res, ledger, store
```

- [ ] **Step 3: Write the failing tests**

`tests/test_biolean_ledger_check.py`:

```python
"""The append check (spec section 2) over the ledger fixture base. No signing here: check_axiom,
check_derived and check_computed are pure functions of a body and a store. Every rejection
assertion names (code, field); every acceptance asserts errors == []."""
from methods_graph.biolean.gaf import GAF_COLUMNS, annotation_id, parse_gaf
from methods_graph.biolean.kernel import check
from methods_graph.biolean.ledger.check import (
    check_axiom, check_computed, check_derived, content_key, fact_from_body, qualifier_options, term_errors)
from methods_graph.biolean.ledger.errors import ALL_LEDGER_CODES, LedgerCode as LC
from methods_graph.biolean.ledger.format import pointer_set
from methods_graph.biolean.props import QUALIFIER_ASPECT, Prop
from methods_graph.biolean.store import StaticFactStore
from methods_graph.biolean.tactics import prove
from tests.biolean_ledger_fixture import KEY16_A, KEY16_B, base_row, context, ledger_base, new_fact

BASE = ledger_base()
CTX = context(KEY16_A)
BY_A_COL = "biolean:" + KEY16_A
P_QUALS = tuple(sorted(q for q, a in QUALIFIER_ASPECT.items() if a == "P"))
F_QUALS = ("contributes_to", "enables")
SEVEN = {"code", "message", "field", "got", "fix", "options", "context"}
TAX = "NCBITaxon:9606"


def run(fact, ctx=CTX, **kw):
    return check_axiom(fact, ctx, **kw)


def codes(res):
    return [(e.code, e.field) for e in res.errors]


def only(res, code, field):
    errs = [e for e in res.errors if e.code == code and e.field == field]
    assert len(errs) == 1, codes(res)
    return errs[0]


def apply_fixes(fact, res):
    """RFC 6901 replace of every non-null fix, all at once, on the submitted row."""
    doc = {"fact": list(fact)}
    for e in res.errors:
        if e.fix is not None:
            doc = pointer_set(doc, e.field, e.fix)
    return doc["fact"]


def prop(term, subject="UniProtKB:P10003", qualifier="involved_in", negated=False, taxon=TAX):
    return {"subject": subject, "qualifier": qualifier, "term": term, "taxon": taxon, "negated": negated}


def good_derivation():
    return {"biolean": "0.1", "goal": prop("GO:0000002"),
            "steps": [{"id": "s1", "rule": "axiom", "conclusion": prop("GO:0000003")},
                      {"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": ["GO:0000003", "GO:0000002"],
                       "conclusion": prop("GO:0000002")}],
            "root": "s2"}


# ---------- steps 1, 1a, 7 ----------

def test_the_example_fact_is_admitted_with_column_15_filled_and_a_check_block():
    res = run(new_fact())
    assert res.errors == [] and res.deferred == [] and res.ok
    assert res.fact[14] == BY_A_COL and res.fact[:14] == new_fact()[:14]
    assert res.annotation.id == annotation_id(res.fact) == res.check["annotation_id"]
    assert set(res.check) == {"kernel", "annotation_id", "contested_by", "counters"}
    assert res.check["contested_by"] == [] and res.check["counters"] == {"new_subject": 0}
    assert res.gaf_report["annotations"] == 1


def test_assigned_by_empty_is_filled_and_wrong_value_rejected():
    e = only(run(new_fact(assigned_by="UniProt")), LC.LEDGER_ASSIGNED_BY, "/fact/14")
    assert (e.got, e.fix) == ("UniProt", BY_A_COL)
    assert run(new_fact(assigned_by=BY_A_COL)).ok
    # recheck mode: empty is a failure, the signer's value passes (spec section 3 base binding)
    assert (LC.LEDGER_ASSIGNED_BY, "/fact/14") in codes(run(new_fact(), mode="recheck"))
    assert run(new_fact(assigned_by=BY_A_COL), mode="recheck").ok


def test_bad_columns_rejected_with_column_names_in_context():
    for bad in (new_fact()[:16], new_fact() + [""], new_fact()[:13] + [20260925] + new_fact()[14:], "x", None):
        res = run(bad)
        [e] = res.errors
        assert (e.code, e.field, e.fix, e.options) == (LC.LEDGER_BAD_COLUMNS, "/fact", None, ())
        assert e.context == {"columns": list(GAF_COLUMNS)} and res.deferred == []


def test_bad_columns_got_is_the_fact_as_submitted():
    # Spec section 7: got is the whole value at /fact as submitted. Break: got=None for a non-list.
    for bad in ("x", 20260925, {"db": "UniProtKB"}, None, new_fact()[:16]):
        [e] = run(bad).errors
        assert (e.code, e.field, e.got) == (LC.LEDGER_BAD_COLUMNS, "/fact", bad), bad


def test_non_string_column_value_is_bad_columns():
    obj = dict(zip(GAF_COLUMNS, new_fact()))
    obj["date"] = 20260925
    fact, errs = fact_from_body(obj)
    assert errs == [] and fact[13] == 20260925
    [e] = run(fact).errors
    assert (e.code, e.field) == (LC.LEDGER_BAD_COLUMNS, "/fact")


def test_fact_from_body_object_form_and_bad_body():
    obj = dict(zip(GAF_COLUMNS, new_fact()))
    del obj["with_from"]
    fact, errs = fact_from_body(obj)
    assert errs == [] and fact == new_fact()
    fact, [e] = fact_from_body({**obj, "extra": "x"})
    assert fact is None and (e.code, e.field, e.got) == (LC.LEDGER_BAD_COLUMNS, "/fact", {**obj, "extra": "x"})
    assert "extra" in e.message                                 # got is the object as submitted; the names are in the message
    assert e.context == {"columns": list(GAF_COLUMNS)}
    fact, [e] = fact_from_body("a string")
    assert fact is None and (e.code, e.field) == (LC.LEDGER_BAD_BODY, "/fact")
    assert fact_from_body(new_fact()) == (new_fact(), [])


def test_lone_surrogate_is_bad_character_not_a_crash():
    res = run(new_fact(gene_product_form_id="\ud800"))
    [e] = res.errors
    assert (e.code, e.field, e.got, e.fix) == (LC.LEDGER_BAD_CHARACTER, "/fact/16", "U+D800", "")
    assert run(apply_fixes(new_fact(gene_product_form_id="\ud800"), res)).ok


def test_trailing_cr_in_column_17_rejected():
    # Break: strip "\r" before checking (parse_gaf would then give a different annotation id).
    res = run(new_fact(gene_product_form_id="x\r"))
    e = only(res, LC.LEDGER_BAD_CHARACTER, "/fact/16")
    assert (e.got, e.fix) == ("U+000D", "x")


def test_empty_columns_15_16_17_pass_character_check():
    assert not any(e.code == LC.LEDGER_BAD_CHARACTER for e in run(new_fact()).errors)


def test_character_fix_feeds_later_steps():
    # Refinement 1: a tab hiding a valid term id gives only the character error, not UNKNOWN_TERM.
    res = run(new_fact(go_id="GO:0000003\t"))
    assert codes(res) == [(LC.LEDGER_BAD_CHARACTER, "/fact/4")] and res.deferred == []


# ---------- step 2 ----------

def test_bad_subject_rejected_and_new_subject_counted():
    res = run(new_fact(db="1abc", db_object_id="P|1"))
    assert codes(res) == [(LC.LEDGER_BAD_SUBJECT, "/fact/0"), (LC.LEDGER_BAD_SUBJECT, "/fact/1")]
    assert res.deferred == [{"step": 8, "waits_on": [1, 2]}]
    assert (LC.LEDGER_BAD_SUBJECT, "/fact/1") in codes(run(new_fact(db_object_id="")))
    assert (LC.LEDGER_BAD_SUBJECT, "/fact/0") in codes(run(new_fact(db="")))
    # a space in column 2 is a step 1a fault first; step 2 then sees the cleaned value
    assert codes(run(new_fact(db_object_id="P1 2"))) == [(LC.LEDGER_BAD_CHARACTER, "/fact/1")]
    res = run(new_fact(db_object_id="P99999"))
    assert res.ok and res.check["counters"] == {"new_subject": 1}


# ---------- step 3 ----------

def test_unknown_term_rejected():
    res = run(new_fact(go_id="GO:0009999"))
    e = only(res, LC.UNKNOWN_TERM, "/fact/4")
    assert (e.got, e.fix, e.options) == ("GO:0009999", None, ())
    assert res.deferred == [{"step": 4, "waits_on": [5]}, {"step": 8, "waits_on": [5]}]


def test_obsolete_term_rejected_with_replaced_by_fix():
    res = run(new_fact(go_id="GO:0000010"))
    e = only(res, LC.OBSOLETE_TERM, "/fact/4")
    assert e.fix == "GO:0000002" and e.context == {"replaced_by": ["GO:0000002"], "consider": []}
    assert res.deferred == [] and codes(res) == [(LC.OBSOLETE_TERM, "/fact/4")]
    assert run(apply_fixes(new_fact(go_id="GO:0000010"), res)).ok


def test_alt_id_rejected_with_primary_fix():
    e = only(run(new_fact(go_id="GO:0000102")), LC.LEDGER_ALT_ID, "/fact/4")
    assert (e.got, e.fix, e.options) == ("GO:0000102", "GO:0000002", ())


def test_alt_id_with_obsolete_primary_fixes_to_the_replacement():
    # Break: fix = the obsolete primary GO:0000010 (what the kernel's ALT_ID_IN_KERNEL carries).
    e = only(run(new_fact(go_id="GO:0000110")), LC.LEDGER_ALT_ID, "/fact/4")
    assert e.fix == "GO:0000002" and "GO:0000010" in e.message and "GO:0000110" in e.message


def test_obsolete_without_single_replaced_by_uses_consider_options():
    # Break: offer the raw consider list (GO:0000999 is not a term); or fix = replaced_by[0].
    e = only(run(new_fact(go_id="GO:0000012")), LC.OBSOLETE_TERM, "/fact/4")
    assert e.fix is None and e.options == ("GO:0000002", "GO:0000003")
    assert e.context == {"replaced_by": [], "consider": ["GO:0000002", "GO:0000003", "GO:0000999"]}
    e = only(run(new_fact(go_id="GO:0000014")), LC.OBSOLETE_TERM, "/fact/4")
    assert e.fix is None and e.options == ("GO:0000002", "GO:0000003")
    e = only(run(new_fact(go_id="GO:0000013")), LC.OBSOLETE_TERM, "/fact/4")
    assert e.fix is None and e.options == ()
    assert term_errors("GO:0000003", CTX.store, "/x") == []


# ---------- step 4 ----------

def test_qualifier_illegal_for_aspect_rejected_with_legal_options():
    e = only(run(new_fact(qualifier="enables")), LC.QUALIFIER_ASPECT_MISMATCH, "/fact/3")
    assert (e.got, e.fix, e.options) == ("enables", None, P_QUALS)
    assert qualifier_options("F") == F_QUALS and len(qualifier_options(None)) == 13


def test_aspect_must_match_term_namespace():
    e = only(run(new_fact(aspect="F")), LC.LEDGER_ASPECT_MISMATCH, "/fact/8")
    assert (e.got, e.fix) == ("F", "P")


def test_unknown_qualifier_options_match_aspect_and_keep_not():
    # Break: offer all 13 for a resolved term; or strip NOT|.
    e = only(run(new_fact(qualifier="NOT|bogus")), LC.UNKNOWN_QUALIFIER, "/fact/3")
    assert e.got == "NOT|bogus" and e.options == tuple("NOT|" + q for q in P_QUALS)
    res = run(new_fact(qualifier="NOT|bogus", go_id="GO:0009999"))
    e = only(res, LC.UNKNOWN_QUALIFIER, "/fact/3")
    assert len(e.options) == 13 and all(o.startswith("NOT|") for o in e.options)
    assert res.deferred == [{"step": 4, "waits_on": [5]}, {"step": 8, "waits_on": [4, 5]}]
    e = only(run(new_fact(qualifier="a|b")), LC.UNKNOWN_QUALIFIER, "/fact/3")
    assert e.options == ()


def test_qualifier_fix_preserves_not():
    # Break: emit the kernel's bare `expected` list. Caught by the negated assertion, not by ACCEPTED.
    for q, code in (("NOT|involved in", LC.UNKNOWN_QUALIFIER), ("NOT|enables", LC.QUALIFIER_ASPECT_MISMATCH)):
        res = run(new_fact(qualifier=q))
        e = only(res, code, "/fact/3")
        assert e.options and all(o.startswith("NOT|") for o in e.options)
        for option in e.options:
            fixed = run(pointer_set({"fact": new_fact(qualifier=q)}, "/fact/3", option)["fact"])
            assert fixed.ok and fixed.annotation.negated is True, (q, option)


# ---------- step 5 ----------

def test_reference_must_carry_doi_pmid_or_go_ref():
    for refs in ("foo:1", "", "|"):
        e = only(run(new_fact(db_reference=refs)), LC.LEDGER_REFERENCE_REQUIRED, "/fact/5")
        assert e.fix is None and e.options == () and e.got == refs
    assert run(new_fact(db_reference="foo:1|PMID:5")).ok
    assert run(new_fact(db_reference="GO_REF:0000002")).ok


def test_bad_reference_syntax_rejected():
    res = run(new_fact(db_reference="DOI:10.1/x|PMID:0|GO_REF:12"))
    errs = [e for e in res.errors if e.code == LC.LEDGER_BAD_REFERENCE]
    assert len(errs) == 3 and all(e.field == "/fact/5" and e.got == "DOI:10.1/x|PMID:0|GO_REF:12" and e.fix is None for e in errs)
    assert not any(e.code == LC.LEDGER_REFERENCE_REQUIRED for e in res.errors)
    assert run(new_fact(db_reference="DOI:10.1234/abc.def-1|PMID:12|GO_REF:0000001")).ok


def test_unmapped_evidence_code_rejected():
    e = only(run(new_fact(evidence_code="XYZ")), LC.LEDGER_ECO_UNMAPPED, "/fact/6")
    assert (e.fix, e.options) == (None, ("IDA", "IEA", "IMP", "IPI"))


# ---------- step 6 ----------

def test_bad_taxon_date_and_empty_object_type_rejected():
    e = only(run(new_fact(taxon="taxon:abc")), LC.LEDGER_BAD_TAXON, "/fact/12")
    assert e.fix is None and e.context == {"form": "taxon:<digits>"}
    assert only(run(new_fact(taxon="taxon:1|taxon:2|taxon:3")), LC.LEDGER_BAD_TAXON, "/fact/12").fix is None
    assert only(run(new_fact(taxon="taxon:9606|")), LC.LEDGER_BAD_TAXON, "/fact/12").fix is None
    for date in ("2026-13-01", "20261301", "2026925", "yesterday"):
        e = only(run(new_fact(date=date)), LC.LEDGER_BAD_DATE, "/fact/13")
        assert e.fix is None and e.context == {"form": "YYYYMMDD"}, date
    e = only(run(new_fact(db_object_type="")), LC.LEDGER_BAD_OBJECT_TYPE, "/fact/11")
    assert e.fix == "protein"                                   # P10002 is known to the base
    e = only(run(new_fact(db_object_id="P99999", db_object_type="")), LC.LEDGER_BAD_OBJECT_TYPE, "/fact/11")
    assert e.fix is None
    # ordered by step, then by column (spec section 2). Break: emit taxon and date before object type.
    res = run(new_fact(taxon="taxon:abc", date="bad", db_object_type=""))
    assert codes(res) == [(LC.LEDGER_BAD_OBJECT_TYPE, "/fact/11"), (LC.LEDGER_BAD_TAXON, "/fact/12"),
                          (LC.LEDGER_BAD_DATE, "/fact/13")]
    assert res.deferred == [{"step": 8, "waits_on": [13, 14]}]


def test_bad_taxon_spelling_gets_rewritten_fix():
    # Break: fix only the first value; or emit NCBITaxon: (parse_gaf accepts it, GAF 2.2 does not).
    for got, fix in (("NCBITaxon:9606", "taxon:9606"), ("9606", "taxon:9606"),
                     ("9606|NCBITaxon:562", "taxon:9606|taxon:562"), ("taxon:9606|562", "taxon:9606|taxon:562")):
        res = run(new_fact(taxon=got))
        e = only(res, LC.LEDGER_BAD_TAXON, "/fact/12")
        assert (e.got, e.fix) == (got, fix)
        assert run(apply_fixes(new_fact(taxon=got), res)).ok
    e = only(run(new_fact(date="2026-09-25")), LC.LEDGER_BAD_DATE, "/fact/13")
    assert e.fix == "20260925"


def test_non_ascii_taxon_digits_are_a_bad_taxon_never_a_crash():
    # Break: drop the ASCII guard before int(). normalize_taxon accepts any str.isdigit()
    # character; int() refuses U+00B2, so recheck (no step 1a cleaning) raised ValueError.
    for taxon in ("taxon:\u00b2", "\u00b2", "taxon:9606|taxon:\u00b2", "taxon:\u0662"):
        res = run(new_fact(taxon=taxon, assigned_by=BY_A_COL), mode="recheck")
        assert codes(res) == [(LC.LEDGER_BAD_CHARACTER, "/fact/12"), (LC.LEDGER_BAD_TAXON, "/fact/12")], taxon
        e = only(res, LC.LEDGER_BAD_TAXON, "/fact/12")
        assert (e.got, e.fix, e.context) == (taxon, None, {"form": "taxon:<digits>"}), taxon
    # append is unchanged: step 1a strips the digit first, so step 6 sees "taxon:"
    res = run(new_fact(taxon="taxon:\u00b2"))
    assert [(e.code, e.field, e.got, e.fix, e.context) for e in res.errors] == [
        (LC.LEDGER_BAD_CHARACTER, "/fact/12", "U+00B2", "taxon:", None),
        (LC.LEDGER_BAD_TAXON, "/fact/12", "taxon:", None, {"form": "taxon:<digits>"})]
    assert res.deferred == [{"step": 8, "waits_on": [13]}] and res.fact is None and res.annotation is None


def test_taxon_longer_than_the_int_digit_limit_is_checked_not_raised():
    # Break: build the canonical fix with str(int(d)). int() refuses more than 4300 digits
    # (CPython's default limit), so a long taxon raised ValueError in both modes. The long
    # spellings must give what the short ones give.
    for digits in ("562", "7" * 4301):
        for got, fix in (("NCBITaxon:" + digits, "taxon:" + digits), (digits, "taxon:" + digits),
                         ("taxon:9606|" + digits, "taxon:9606|taxon:" + digits)):
            for mode in ("append", "recheck"):
                res = run(new_fact(taxon=got, assigned_by=BY_A_COL), mode=mode)
                assert [(e.code, e.field, e.got, e.fix) for e in res.errors] == [
                    (LC.LEDGER_BAD_TAXON, "/fact/12", got, fix)], (mode, got[:24], len(got))


def test_leading_zero_taxon_is_not_canonical_and_cannot_dodge_the_duplicate_check():
    # Refinement 22. Break: accept leading zeros in column 13. "taxon:09606" then parses to
    # NCBITaxon:09606, a different key from the base row's NCBITaxon:9606, and is admitted again.
    row = base_row(1)
    row[12], row[14] = "taxon:09606", BY_A_COL
    res = run(row)
    assert codes(res) == [(LC.LEDGER_BAD_TAXON, "/fact/12"), (LC.LEDGER_DUPLICATE, "/fact")]
    e = only(res, LC.LEDGER_BAD_TAXON, "/fact/12")
    assert (e.got, e.fix) == ("taxon:09606", "taxon:9606")
    assert codes(run(apply_fixes(row, res))) == [(LC.LEDGER_DUPLICATE, "/fact")]
    e = only(run(row, mode="recheck"), LC.LEDGER_BAD_TAXON, "/fact/12")
    assert (e.got, e.fix) == ("taxon:09606", "taxon:9606")
    # the second value too; an all-zero value keeps one zero, and each fix clears its error
    for got, fix in (("taxon:9606|taxon:0562", "taxon:9606|taxon:562"), ("taxon:00", "taxon:0")):
        res = run(new_fact(taxon=got))
        assert only(res, LC.LEDGER_BAD_TAXON, "/fact/12").fix == fix
        assert (LC.LEDGER_BAD_TAXON, "/fact/12") not in codes(run(apply_fixes(new_fact(taxon=got), res)))


# ---------- step 8 ----------

def test_content_key_ignores_display_columns_date_and_assigned_by():
    r1, r2 = base_row(1), base_row(2)
    anns, _ = parse_gaf(["\t".join(r1), "\t".join(r2)], BASE.eco_map, BASE.primary_id, BASE.term)
    assert len(anns) == 2 and content_key(anns[0]) == content_key(anns[1]) and anns[0].id != anns[1].id
    r3 = list(r1)
    r3[6] = "IMP"
    [a3], _ = parse_gaf(["\t".join(r3)], BASE.eco_map, BASE.primary_id, BASE.term)
    assert content_key(a3) != content_key(anns[0])


def test_base_row_resubmitted_with_own_assigned_by_is_duplicate():
    # Mutations that must fail: compare annotation ids; use a raw-column key.
    row = base_row(1)
    row[5] = "PMID:99|PMID:100"                 # reordered
    row[9] = row[10] = ""                       # display columns emptied
    row[12] = "NCBITaxon:9606"                  # spelling corrected by the taxon fix
    row[13] = "20260925"                        # new date
    row[14] = BY_A_COL
    res = run(row)
    assert codes(res) == [(LC.LEDGER_BAD_TAXON, "/fact/12"), (LC.LEDGER_DUPLICATE, "/fact")]
    dup = only(res, LC.LEDGER_DUPLICATE, "/fact")
    ids = sorted([annotation_id(base_row(1)), annotation_id(base_row(2))])
    assert dup.context == {"existing": [{"annotation_id": i, "source": "base"} for i in ids]}
    assert dup.fix is None and dup.options == () and res.deferred == []
    assert dup.got == row and dup.got[12] == "NCBITaxon:9606"   # spec section 7: got is the row as submitted, not the fixed row


def test_duplicate_of_ledger_row_rejected():
    # The existing row is in a second signer's file. With one signer this passes against the bug
    # (the ids would then be equal): column 15 differs between signers, the content key does not.
    row = new_fact(assigned_by="biolean:" + KEY16_B)
    [ann], _ = parse_gaf(["\t".join(row)], BASE.eco_map, BASE.primary_id, BASE.term)
    store = StaticFactStore(BASE.terms, BASE.edges, BASE.annotations + [ann])
    ctx = context(KEY16_A, store=store, sources={ann.id: f"ledger/{KEY16_B}.jsonl:1"})
    res = run(new_fact(), ctx)
    dup = only(res, LC.LEDGER_DUPLICATE, "/fact")
    assert dup.context == {"existing": [{"annotation_id": ann.id, "source": f"ledger/{KEY16_B}.jsonl:1"}]}


def test_same_prop_different_reference_is_a_new_row():
    row = base_row(1)
    row[5], row[14] = "PMID:200", ""
    res = run(row)
    assert res.ok and res.annotation.id not in {annotation_id(base_row(1)), annotation_id(base_row(2))}


def test_fix_that_creates_duplicate_is_reported_first_try():
    # Break: run step 8 on the unfixed row (the obsolete term then matches nothing). An alt id
    # would not do: parse_gaf canonicalizes it to the primary on its own, so step 8 would find
    # the duplicate whether or not the LEDGER_ALT_ID fix was applied.
    row = base_row(1)
    row[4], row[14] = "GO:0000010", BY_A_COL
    res = run(row)
    assert codes(res) == [(LC.OBSOLETE_TERM, "/fact/4"), (LC.LEDGER_DUPLICATE, "/fact")]
    assert res.deferred == []
    # the alt-id form also reports both in one response, but cannot detect the mutation
    row = base_row(1)
    row[4], row[14] = "GO:0000102", BY_A_COL
    assert codes(run(row)) == [(LC.LEDGER_ALT_ID, "/fact/4"), (LC.LEDGER_DUPLICATE, "/fact")]


# ---------- step 9 ----------

def test_positive_fact_against_base_not_row_is_admitted_and_contested():
    not_id = annotation_id(base_row(3))
    res = run(new_fact(db_object_id="P10001", db_object_symbol="G1", db_reference="PMID:300"))
    assert res.ok and res.check["contested_by"] == [not_id]
    store = StaticFactStore(BASE.terms, BASE.edges, BASE.annotations + [res.annotation])
    d = prove(Prop("UniProtKB:P10001", "involved_in", "GO:0000003", TAX, False), store)
    verdict = check(d, store)
    assert verdict["verdict"] == "ACCEPTED" and [c["annotation"] for c in verdict["conflicts"]] == [not_id]


# ---------- combinations ----------

def test_independent_faults_reported_in_one_response():
    # Break: stop at the first failing step.
    res = run(new_fact(db="1x", db_reference="foo:1", date="bad"))
    assert codes(res) == [(LC.LEDGER_BAD_SUBJECT, "/fact/0"), (LC.LEDGER_REFERENCE_REQUIRED, "/fact/5"),
                          (LC.LEDGER_BAD_DATE, "/fact/13")]
    assert res.deferred == [{"step": 8, "waits_on": [1, 6, 14]}]


def test_cross_namespace_replacement_reports_aspect_errors_together():
    # Break: evaluate step 4 against the submitted term (no aspect errors would appear).
    fact = new_fact(go_id="GO:0000011")
    res = run(fact)
    assert codes(res) == [(LC.OBSOLETE_TERM, "/fact/4"), (LC.QUALIFIER_ASPECT_MISMATCH, "/fact/3"),
                          (LC.LEDGER_ASPECT_MISMATCH, "/fact/8")]
    assert only(res, LC.OBSOLETE_TERM, "/fact/4").fix == "GO:0000021"
    assert only(res, LC.LEDGER_ASPECT_MISMATCH, "/fact/8").fix == "F"
    assert only(res, LC.QUALIFIER_ASPECT_MISMATCH, "/fact/3").options == F_QUALS
    assert res.deferred == [{"step": 8, "waits_on": [4]}]
    fixed = apply_fixes(fact, res)
    res2 = run(fixed)
    assert codes(res2) == [(LC.QUALIFIER_ASPECT_MISMATCH, "/fact/3")]
    for option in only(res2, LC.QUALIFIER_ASPECT_MISMATCH, "/fact/3").options:
        assert run(pointer_set({"fact": fixed}, "/fact/3", option)["fact"]).ok


def test_recheck_mode_applies_no_fix_and_requires_assigned_by():
    res = run(new_fact(go_id="GO:0000102"), mode="recheck")
    assert codes(res) == [(LC.LEDGER_ALT_ID, "/fact/4"), (LC.LEDGER_ASSIGNED_BY, "/fact/14")]
    assert res.deferred == [] and res.annotation is not None and res.annotation.term == "GO:0000002"
    assert res.fact == new_fact(go_id="GO:0000102")


def test_recheck_trailing_newline_fails_each_anchored_column_check():
    # Break: end any column regex in `$`, which also matches just before a final "\n". Append
    # cleans the "\n" at step 1a before these checks run, so only recheck (the row as signed)
    # reaches them with it.
    for column, value, code, fix in (
            ("db", "UniProtKB\n", LC.LEDGER_BAD_SUBJECT, None),
            ("db_reference", "DOI:10.1038/s41586-026-00001-0\n", LC.LEDGER_BAD_REFERENCE, None),
            ("db_reference", "PMID:12\n", LC.LEDGER_BAD_REFERENCE, None),
            ("db_reference", "GO_REF:0000001\n", LC.LEDGER_BAD_REFERENCE, None),
            ("taxon", "taxon:9606\n", LC.LEDGER_BAD_TAXON, "taxon:9606"),
            ("date", "20260925\n", LC.LEDGER_BAD_DATE, None),
            ("date", "2026-09-25\n", LC.LEDGER_BAD_DATE, None)):
        res = run(new_fact(**{column: value, "assigned_by": BY_A_COL}), mode="recheck")
        field = f"/fact/{GAF_COLUMNS.index(column)}"
        assert (LC.LEDGER_BAD_CHARACTER, field) in codes(res), (column, value)
        e = only(res, code, field)
        assert (e.got, e.fix) == (value, fix), (column, value)


def test_recheck_of_an_unencodable_row_reports_and_does_not_raise():
    # Break: drop the UTF-8 guard before step 7a. Recheck hashes the row as signed and
    # annotation_id encodes it as UTF-8, so a lone surrogate raised UnicodeEncodeError.
    for i, want in ((0, [(LC.LEDGER_BAD_CHARACTER, "/fact/0"), (LC.LEDGER_BAD_SUBJECT, "/fact/0")]),
                    (16, [(LC.LEDGER_BAD_CHARACTER, "/fact/16")])):
        fact = new_fact(assigned_by=BY_A_COL)
        fact[i] = "\ud800"
        res = run(fact, mode="recheck")
        assert codes(res) == want and res.annotation is None and res.gaf_report is None, i
        assert res.fact == fact and res.check is None, i
    # every column: one LEDGER_BAD_CHARACTER at that column (no second one), nothing hashed
    for i in range(len(GAF_COLUMNS)):
        fact = new_fact(assigned_by=BY_A_COL)
        fact[i] += "\ud800"
        res = run(fact, mode="recheck")
        chars = [e for e in res.errors if e.code == LC.LEDGER_BAD_CHARACTER]
        assert [(e.field, e.got) for e in chars] == [(f"/fact/{i}", "U+D800")], i
        assert res.annotation is None, i


def test_recheck_step_7a_parses_the_row_as_signed():
    # Pins step 7a: other step 1a faults do not skip it. Break: feed parse_gaf the joined row
    # split with str.splitlines(). That changes nothing for "a b", but U+2028 splits the row: form
    # "a", a different annotation id, and a dropped fragment.
    for form in ("a b", "a\u2028b"):
        fact = new_fact(gene_product_form_id=form, assigned_by=BY_A_COL)
        res = run(fact, mode="recheck")
        assert codes(res) == [(LC.LEDGER_BAD_CHARACTER, "/fact/16")], form
        assert res.annotation is not None and res.annotation.id == annotation_id(fact), form
        assert res.annotation.form == form and res.gaf_report["rows"] == 1, form


# ---------- derived ----------

def test_derived_is_admitted_with_axioms_and_conflicts_in_check():
    res = check_derived({"derivation": good_derivation()}, CTX)
    assert res.errors == [] and res.ok
    assert res.conclusion == prop("GO:0000002") and res.derivation["steps"][1]["id"] == "s2"
    assert res.check == {"kernel": CTX.kernel_version, "axioms": [annotation_id(base_row(6))], "conflicts": []}


def test_derived_with_used_sorry_refused():
    d = good_derivation()
    d["steps"].append({"id": "s3", "rule": "sorry", "conclusion": prop("GO:0000002"),
                       "provenance": {"method": "m:x", "inputs": ["GEO:1"], "parameters": {}, "claim": "c"}})
    d["root"] = "s3"
    res = check_derived({"derivation": d}, CTX)
    assert check(d, CTX.store)["verdict"] == "ACCEPTED"           # the kernel accepts; the ledger does not
    [e] = res.errors
    assert (e.code, e.field, e.fix) == (LC.LEDGER_SORRY_USED, "/derivation/steps/2", None)
    assert e.got["step"] == "s3" and e.got["used"] is True


def test_derived_with_unused_sorry_refused():
    d = good_derivation()
    d["steps"].insert(0, {"id": "s0", "rule": "sorry", "conclusion": prop("GO:0000002"),
                          "provenance": {"method": "m:x", "inputs": ["GEO:1"], "parameters": {}, "claim": "c"}})
    res = check_derived({"derivation": d}, CTX)
    [e] = res.errors
    assert (e.code, e.field) == (LC.LEDGER_SORRY_UNUSED, "/derivation/steps/0")


def test_derived_conclusion_must_equal_goal():
    res = check_derived({"derivation": good_derivation(), "conclusion": prop("GO:0000001")}, CTX)
    [e] = res.errors
    assert (e.code, e.field, e.got, e.fix) == (LC.LEDGER_CONCLUSION_MISMATCH, "/conclusion", prop("GO:0000001"), prop("GO:0000002"))
    assert check_derived({"derivation": good_derivation(), "conclusion": prop("GO:0000002")}, CTX).ok


def test_derived_stores_elaborated_derivation():
    d = good_derivation()
    d["goal"]["subject"] = "G3"
    d["steps"][0]["conclusion"]["taxon"] = "taxon:9606"
    res = check_derived({"derivation": d}, CTX)
    assert res.ok
    assert res.derivation["goal"]["subject"] == "UniProtKB:P10003"
    assert res.derivation["steps"][0]["conclusion"]["taxon"] == TAX
    assert res.conclusion["subject"] == "UniProtKB:P10003"


def test_derived_rejected_carries_kernel_errors_in_context():
    d = good_derivation()
    d["steps"][1]["edge"] = ["GO:0000003", "GO:0000001"]
    res = check_derived({"derivation": d}, CTX)
    [e] = res.errors
    assert (e.code, e.field, e.got, e.fix) == (LC.LEDGER_DERIVATION_REJECTED, "/derivation", None, None)
    kernel = e.context["kernel"]
    assert set(kernel) == {"errors", "elaboration"}
    assert {(x["step"], x["code"]) for x in kernel["errors"]} >= {("s2", "EDGE_NOT_FOUND")}
    assert set(kernel["errors"][0]) == {"step", "code", "message", "expected", "actual", "suggestions"}
    for bad in ("nope", {"derivation": "x"}, {"derivation": d, "extra": 1}, {}):
        res = check_derived(bad, CTX)
        assert res.errors and res.errors[0].code in (LC.LEDGER_BAD_BODY, LC.LEDGER_DERIVATION_REJECTED)


def test_derived_body_key_errors_report_the_value_as_submitted():
    # Spec section 7: got is the whole value at field as submitted, or null if absent. Break: got=None.
    d = good_derivation()
    res = check_derived({"derivation": d, "extra": 1}, CTX)
    assert [(e.code, e.field, e.got) for e in res.errors] == [(LC.LEDGER_BAD_BODY, "/extra", 1)]
    res = check_derived({"a/b~c": [1]}, CTX)                     # absent derivation: got null
    assert [(e.code, e.field, e.got) for e in res.errors] == [(LC.LEDGER_BAD_BODY, "/derivation", None),
                                                             (LC.LEDGER_BAD_BODY, "/a~1b~0c", [1])]


# ---------- computed ----------

def good_computed():
    return {"method": "m:bcftools plugin fill-tags",
            "dataset": {"id": "GEO:GSE12345", "sha256": "ab" * 32},
            "graph_hash": "sha256:" + "cd" * 32,
            "preconditions": [{"id": "replicates>=3", "status": "met", "diagnostic": "n=4"}],
            "run": {"command": "nextflow run x", "container": "quay.io/x@sha256:ab", "exit_code": 0},
            "conclusion": prop("GO:0000003")}


def test_computed_schema_checked_then_refused():
    errs = check_computed(good_computed(), CTX)
    assert [(e.code, e.field) for e in errs] == [(LC.NOT_YET_DISCHARGEABLE, None)] and errs[0].fix is None
    cases = {
        "/graph_hash": {**good_computed(), "graph_hash": "cd" * 32},
        "/method": {**good_computed(), "method": "m:DESeq2"},
        "/run/exit_code": {**good_computed(), "run": {**good_computed()["run"], "exit_code": True}},
        "/preconditions/0/status": {**good_computed(), "preconditions": [{"id": "x", "status": "maybe", "diagnostic": ""}]},
        "/dataset/id": {**good_computed(), "dataset": {"id": "", "sha256": "x"}},
        "/extra": {**good_computed(), "extra": 1},
        "/run": {**good_computed(), "run": {"command": "x"}},
    }
    for field, body in cases.items():
        errs = check_computed(body, CTX)
        assert errs[0].code == LC.LEDGER_BAD_COMPUTED and errs[0].field == field, (field, [(e.code, e.field) for e in errs])
        assert errs[-1].code == LC.NOT_YET_DISCHARGEABLE
    e = check_computed({**good_computed(), "preconditions": [{"id": "x", "status": "maybe", "diagnostic": ""}]}, CTX)[0]
    assert e.options == ("met", "unknown", "unmet")
    for m in ("m:x\u0085y", "m:x\u0080y", "m:x\ty"):                    # C1 and C0 controls mid-string
        e = check_computed({**good_computed(), "method": m}, CTX)[0]
        assert (e.code, e.field, e.got) == (LC.LEDGER_BAD_COMPUTED, "/method", m)
    errs = check_computed({**good_computed(), "conclusion": prop("GO:0000003", qualifier="enables", taxon="9606")}, CTX)
    assert [(e.code, e.field) for e in errs[:-1]] == [(LC.QUALIFIER_ASPECT_MISMATCH, "/conclusion/qualifier"),
                                                     (LC.LEDGER_BAD_COMPUTED, "/conclusion/taxon")]
    assert errs[0].options == P_QUALS and errs[1].fix == TAX
    errs = check_computed({**good_computed(), "conclusion": prop("GO:0000010")}, CTX)
    assert [(e.code, e.field) for e in errs[:-1]] == [(LC.OBSOLETE_TERM, "/conclusion/term")] and errs[0].fix == "GO:0000002"
    assert [(e.code, e.field) for e in check_computed("x", CTX)] == [(LC.LEDGER_BAD_BODY, None), (LC.NOT_YET_DISCHARGEABLE, None)]


def test_computed_taxon_fix_clears_its_error():
    # Spec section 2 fix rule: a non-null fix, written at its field, removes that error. Break:
    # fix = normalize_taxon(taxon), which for U+00B2 is "NCBITaxon:\u00b2", rejected again.
    # A non-ASCII digit gets no fix (as step 6 of an axiom does), even U+0662, which TAXON_RE's
    # \d would accept.
    for taxon, fix in (("NCBITaxon:\u00b2", None), ("taxon:\u00b2", None), ("\u00b2", None),
                       ("taxon:\u0662", None), ("taxon:abc", None),
                       ("taxon:9606", "NCBITaxon:9606"), ("9606", "NCBITaxon:9606")):
        body = {**good_computed(), "conclusion": prop("GO:0000003", taxon=taxon)}
        errs = check_computed(body, CTX)
        assert [(e.code, e.field) for e in errs] == [(LC.LEDGER_BAD_COMPUTED, "/conclusion/taxon"),
                                                     (LC.NOT_YET_DISCHARGEABLE, None)], taxon
        assert (errs[0].got, errs[0].fix) == (taxon, fix), taxon
        assert errs[0].context == (None if fix else {"form": "NCBITaxon:<digits>"}), taxon
        for e in errs:
            if e.fix is not None:
                again = check_computed(pointer_set(body, e.field, e.fix), CTX)
                assert (e.code, e.field) not in [(x.code, x.field) for x in again], (taxon, e.fix)


def test_computed_conclusion_taxon_is_ascii_digits_with_no_trailing_newline():
    # Break: validate with props.TAXON_RE (^NCBITaxon:\d+$): \d takes U+0662 and $ matches just
    # before a final "\n". The newline case keeps a fix: stripped, its digits are ASCII.
    def result(taxon):
        body = {**good_computed(), "conclusion": prop("GO:0000003", taxon=taxon)}
        return [(e.code, e.field, e.fix) for e in check_computed(body, CTX)]
    assert {t: result(t) for t in ("NCBITaxon:\u0662", "NCBITaxon:9606\n", "NCBITaxon:9606")} == {
        "NCBITaxon:\u0662": [(LC.LEDGER_BAD_COMPUTED, "/conclusion/taxon", None), (LC.NOT_YET_DISCHARGEABLE, None, None)],
        "NCBITaxon:9606\n": [(LC.LEDGER_BAD_COMPUTED, "/conclusion/taxon", "NCBITaxon:9606"),
                             (LC.NOT_YET_DISCHARGEABLE, None, None)],
        "NCBITaxon:9606": [(LC.NOT_YET_DISCHARGEABLE, None, None)]}


def test_computed_unknown_key_is_reported_at_its_escaped_pointer():
    # RFC 6901, as the derived path does. Break: an unescaped f"/{k}", which points into /a/b~c.
    errs = check_computed({**good_computed(), "a/b~c": [1]}, CTX)
    assert [(e.code, e.field, e.got) for e in errs] == [(LC.LEDGER_BAD_COMPUTED, "/a~1b~0c", [1]),
                                                       (LC.NOT_YET_DISCHARGEABLE, None, None)]


def test_computed_graph_hash_with_trailing_newline_is_reported():
    # Break: `$` in _GRAPH_HASH_RE (it matches before a final "\n"). character_errors does not
    # flag "\n" outside the fact columns, so this check is the only one that sees it.
    body = {**good_computed(), "graph_hash": "sha256:" + "cd" * 32 + "\n"}
    errs = check_computed(body, CTX)
    assert [(e.code, e.field) for e in errs] == [(LC.LEDGER_BAD_COMPUTED, "/graph_hash"), (LC.NOT_YET_DISCHARGEABLE, None)]
    assert errs[0].got == body["graph_hash"]


# ---------- the shape ----------

def test_rejection_shape_is_ledger_not_kernel():
    # Break: pass a kernel Error.to_dict() through anywhere.
    results = [run(new_fact(go_id="GO:0009999")), run(new_fact(qualifier="enables")), run(new_fact(go_id="GO:0000012")),
               run(new_fact(db="1x", db_reference="foo:1", date="bad")), run(new_fact()[:16]),
               run(base_row(1)[:14] + [BY_A_COL, "", ""])]
    errors = [e for r in results for e in r.errors]
    d = good_derivation()
    d["steps"][1]["edge"] = ["GO:0000003", "GO:0000001"]
    errors += check_derived({"derivation": d}, CTX).errors
    errors += check_computed({**good_computed(), "conclusion": prop("GO:0000010", qualifier="enables")}, CTX)
    assert len(errors) >= 11
    for e in errors:
        d = e.to_dict()
        assert set(d) == SEVEN and d["code"] in ALL_LEDGER_CODES
        assert not isinstance(d["fix"], list) and isinstance(d["options"], list)
        assert d["field"] is None or d["field"].startswith("/")
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_ledger_check.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.ledger.check'`.

- [ ] **Step 5: Implement `check.py`**

`src/methods_graph/biolean/ledger/check.py`:

```python
"""The append check (spec §2): axiom, derived and computed bodies against a store.

Every failure is a ``LedgerError`` in the §7 shape. The kernel's ``check_term``,
``check_qualifier_aspect`` and ``check`` are reused and re-emitted; no kernel ``Error`` passes
through. Order of an axiom check: step 1 (shape; nothing else runs on failure), 1a
(characters; its fixes feed every later step), 2, 3, 4, 5, 6, 7 on the cleaned row, then 7a
and 8 on the row with every non-null fix applied, then 9 only when everything passed.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import methods_graph
from methods_graph.biolean.elaborate import elaborate
from methods_graph.biolean.errors import Code
from methods_graph.biolean.gaf import GAF_COLUMNS, annotation_id, parse_gaf
from methods_graph.biolean.kernel import check, check_qualifier_aspect, check_term
from methods_graph.biolean.ledger.errors import LedgerCode, LedgerError
from methods_graph.biolean.ledger.format import ASSIGNED_BY_PREFIX, column_character_error
from methods_graph.biolean.props import (
    NAMESPACE_ASPECT, QUALIFIER_ASPECT, Annotation, Prop, Term, normalize_taxon)
from methods_graph.biolean.store import FactStore

# `\Z`, not `$`: `$` also matches just before a final "\n" (as in format.py). Step 1a catches a
# "\n" in a fact column first in append mode, but recheck runs on the row as signed, and nothing
# before check_computed looks at "\n" outside the fact columns.
_DB_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*\Z")
_REFERENCE_FORMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("DOI:", re.compile(r"^DOI:10\.[0-9]{4,9}/\S+\Z")),
    ("PMID:", re.compile(r"^PMID:[1-9][0-9]*\Z")),
    ("GO_REF:", re.compile(r"^GO_REF:[0-9]{7}\Z")),
)
# Canonical column 13 value: no leading zero (refinement 22), so one taxon has one spelling and
# a respelled row cannot dodge the step 8 duplicate check.
_TAXON_COL_RE = re.compile(r"^taxon:(?:0|[1-9][0-9]*)\Z")
_ASCII_NCBI_TAXON_RE = re.compile(r"^NCBITaxon:([0-9]+)\Z")
_DATE_RE = re.compile(r"^[0-9]{8}\Z")
_ISO_DATE_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})\Z")
_GRAPH_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}\Z")
_STATUSES: tuple[str, ...] = ("met", "unknown", "unmet")
_DROP_COUNTERS = ("bad_column_count", "unknown_qualifier", "bad_taxon_cardinality",
                  "bad_taxon_format", "duplicate_row")
_COMPUTED_KEYS: tuple[str, ...] = ("method", "dataset", "graph_hash", "preconditions", "run", "conclusion")


@dataclass
class CheckContext:
    """What the check needs. ``store`` is the base plus admitted ledger facts at append time;
    ``ledger_sources`` names where each admitted ledger annotation lives, for step 8."""
    store: FactStore
    eco_map: Mapping[str, str]
    primary_id: Callable[[str], str | None]
    term: Callable[[str], Term | None]
    key16: str
    ledger_sources: Mapping[str, str] = field(default_factory=dict)
    kernel_version: str = methods_graph.__version__


@dataclass
class AxiomResult:
    errors: list[LedgerError]
    deferred: list[dict[str, Any]]
    fact: list[str] | None            # the final row (column 15 filled) when it parsed
    annotation: Annotation | None
    check: dict[str, Any] | None      # the entry's `check` block, only when ok
    counters: dict[str, int]
    gaf_report: dict[str, int] | None

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class DerivedResult:
    errors: list[LedgerError]
    derivation: Any                   # elaborated
    conclusion: dict[str, Any] | None
    check: dict[str, Any] | None

    @property
    def ok(self) -> bool:
        return not self.errors


def _col(i: int) -> str:
    return f"/fact/{i}"


def _sorted_options(values) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def content_key(a: Annotation) -> tuple:
    """Spec §1 "Content key": the parsed fields that make a row a distinct piece of evidence."""
    return (a.subject, a.qualifier, a.negated, a.term, a.taxon, a.references, a.code, a.with_from,
            a.interacting_taxon, a.extension, a.form)


def content_key_json(a: Annotation) -> list[Any]:
    return [a.subject, a.qualifier, a.negated, a.term, a.taxon, list(a.references), a.code,
            list(a.with_from), a.interacting_taxon, a.extension, a.form]


def fact_from_body(body: Any) -> tuple[list[str] | None, list[LedgerError]]:
    """The 17-list from a list body or an object body keyed by column name (spec §7)."""
    if isinstance(body, list):
        return body, []
    if isinstance(body, dict):
        extra = sorted(set(body) - set(GAF_COLUMNS))
        if extra:
            return None, [LedgerError(LedgerCode.LEDGER_BAD_COLUMNS,
                                      f"unknown column key(s): {', '.join(extra)}", "/fact",
                                      got=body, context={"columns": list(GAF_COLUMNS)})]
        return [body.get(name, "") for name in GAF_COLUMNS], []
    return None, [LedgerError(LedgerCode.LEDGER_BAD_BODY,
                              "a fact is a 17-element list or an object keyed by GAF column name",
                              "/fact", got=body)]


# ---------------------------------------------------------------------------
# terms and qualifiers (steps 3 and 4)
# ---------------------------------------------------------------------------

def _live(ids, store: FactStore) -> list[str]:
    out = []
    for t in ids:
        term = store.term(t)
        if term is not None and not term.obsolete:
            out.append(t)
    return sorted(set(out))


def _obsolete(term_id: str, store: FactStore, field_: str, got: str, prefix: str, code: str) -> LedgerError:
    """fix = the single live replaced_by; else options = several live replaced_by, else the live
    consider terms (even one), else []. Never an obsolete or non-term id."""
    term = store.term(term_id)
    assert term is not None
    replaced = _live(term.replaced_by, store)
    consider = _live(term.consider, store)
    context = {"replaced_by": list(term.replaced_by), "consider": list(term.consider)}
    if len(replaced) == 1:
        return LedgerError(code, f"{prefix}; replaced by {replaced[0]}", field_, got=got,
                           fix=replaced[0], context=context)
    options = replaced if len(replaced) > 1 else consider
    what = "choose one of replaced_by" if replaced else ("consider one of these" if consider else "no live replacement")
    return LedgerError(code, f"{prefix}; {what}", field_, got=got, options=tuple(options), context=context)


def term_errors(term_id: str, store: FactStore, field_: str) -> list[LedgerError]:
    """Spec §2 step 3 over the kernel's check_term; [] for a live primary id. The kernel stops
    at an alt id, so an alt id's primary is checked again here."""
    errs = check_term(term_id, store, None)
    if not errs:
        return []
    err = errs[0]
    if err.code == Code.UNKNOWN_TERM:
        return [LedgerError(LedgerCode.UNKNOWN_TERM, f"unknown term {term_id}", field_, got=term_id)]
    if err.code == Code.ALT_ID_IN_KERNEL:
        primary = err.expected
        if not check_term(primary, store, None):
            return [LedgerError(LedgerCode.LEDGER_ALT_ID, f"{term_id} is an alt_id of {primary}",
                                field_, got=term_id, fix=primary)]
        return [_obsolete(primary, store, field_, term_id,
                          f"{term_id} is an alt_id of {primary}, which is obsolete", LedgerCode.LEDGER_ALT_ID)]
    return [_obsolete(term_id, store, field_, term_id, f"{term_id} is obsolete", LedgerCode.OBSOLETE_TERM)]


def qualifier_options(aspect: str | None, prefix: str = "") -> tuple[str, ...]:
    """The qualifiers legal for ``aspect`` (all 13 when None), each carrying ``prefix``."""
    return _sorted_options(prefix + q for q, a in QUALIFIER_ASPECT.items() if aspect is None or a == aspect)


def _real_date(yyyymmdd: str) -> bool:
    try:
        _dt.date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:]))
    except ValueError:
        return False
    return True


def _ascii_taxon_digits(raw: str) -> str | None:
    """The digits of ``raw`` when ``normalize_taxon`` accepts it and every digit is ASCII 0-9;
    else None. ``normalize_taxon`` accepts any ``str.isdigit()`` character, and ``int()`` refuses
    some of them (U+00B2), so a non-ASCII digit is treated as a non-numeric taxon: no fix."""
    normalized = normalize_taxon(raw)
    m = _ASCII_NCBI_TAXON_RE.match(normalized) if normalized is not None else None
    return m.group(1) if m else None


def _key_pointer(key: str) -> str:
    """The RFC 6901 pointer to a top-level body key: ``~`` is ``~0`` and ``/`` is ``~1``."""
    return "/" + key.replace("~", "~0").replace("/", "~1")


def _utf8_encodable(s: str) -> bool:
    """False for a string holding a lone surrogate, the only str that UTF-8 cannot encode."""
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


# ---------------------------------------------------------------------------
# axiom
# ---------------------------------------------------------------------------

def check_axiom(fact: Any, ctx: CheckContext, *, mode: str = "append") -> AxiomResult:
    """Spec §2 ``axiom``.

    ``append``: steps 1-9 with fix application; ``fact`` is the final row with column 15 filled.
    ``recheck`` (spec §3 base binding): steps 1-7a on the row as signed, no fix applied, column 15
    must equal ``biolean:<ctx.key16>``, no duplicate or contested step; ``annotation`` is set
    whenever the row round-trips so the loader can test supersession even for a stale row.
    """
    if mode not in ("append", "recheck"):
        raise ValueError(mode)
    counters = {"new_subject": 0}
    # step 1
    if not (isinstance(fact, list) and len(fact) == len(GAF_COLUMNS) and all(isinstance(c, str) for c in fact)):
        err = LedgerError(LedgerCode.LEDGER_BAD_COLUMNS, "fact must be exactly 17 string columns in GAF 2.2 order",
                          "/fact", got=fact,
                          context={"columns": list(GAF_COLUMNS)})
        return AxiomResult([err], [], None, None, None, counters, None)

    errors: list[LedgerError] = []
    deferred: list[dict[str, Any]] = []
    fixes: dict[int, str] = {}
    unfixable: set[int] = set()

    def emit(err: LedgerError) -> None:
        errors.append(err)
        col = int(err.field[len("/fact/"):])
        if err.fix is None:
            unfixable.add(col)
        else:
            fixes[col] = err.fix

    # step 1a: the cleaned row is what every later step sees (plan refinement 1)
    row = list(fact)
    for i, value in enumerate(fact):
        err = column_character_error(i, value)
        if err is not None:
            emit(err)
            if mode == "append":
                row[i] = err.fix

    # step 2
    db_ok = bool(row[0]) and _DB_RE.match(row[0]) is not None
    id_ok = bool(row[1]) and not any(c.isspace() for c in row[1]) and "|" not in row[1]
    if not db_ok:
        emit(LedgerError(LedgerCode.LEDGER_BAD_SUBJECT, "column 1 must match ^[A-Za-z][A-Za-z0-9_.-]*$",
                         _col(0), got=row[0]))
    if not id_ok:
        emit(LedgerError(LedgerCode.LEDGER_BAD_SUBJECT, "column 2 must be non-empty with no whitespace or |",
                         _col(1), got=row[1]))
    subject = f"{row[0]}:{row[1]}"
    known_subject = ctx.store.subject_exists(subject)
    if db_ok and id_ok and not known_subject:
        counters["new_subject"] = 1

    # step 3
    errs3 = term_errors(row[4], ctx.store, _col(4))
    for err in errs3:
        emit(err)
    resolved_term: str | None = row[4] if not errs3 else (errs3[0].fix if mode == "append" else None)
    term_obj = ctx.store.term(resolved_term) if resolved_term is not None else None
    aspect = NAMESPACE_ASPECT.get(term_obj.namespace) if term_obj is not None else None

    # step 4, qualifier half (always) and aspect half (waits on column 5)
    negated = row[3].startswith("NOT|")
    prefix = "NOT|" if negated else ""
    bare = row[3][4:] if negated else row[3]
    if "|" in bare:
        emit(LedgerError(LedgerCode.UNKNOWN_QUALIFIER, "column 4 is NOT|q or q, with no other |",
                         _col(3), got=row[3]))
    elif bare not in QUALIFIER_ASPECT:
        emit(LedgerError(LedgerCode.UNKNOWN_QUALIFIER, f"unknown qualifier {bare!r}", _col(3),
                         got=row[3], options=qualifier_options(aspect, prefix)))
    if term_obj is None:
        if mode == "append":
            deferred.append({"step": 4, "waits_on": [5]})
    else:
        if bare in QUALIFIER_ASPECT and check_qualifier_aspect(bare, resolved_term, ctx.store):
            emit(LedgerError(LedgerCode.QUALIFIER_ASPECT_MISMATCH,
                             f"{bare} is a {QUALIFIER_ASPECT[bare]}-aspect qualifier; {resolved_term} is {term_obj.namespace}",
                             _col(3), got=row[3], options=qualifier_options(aspect, prefix)))
        if row[8] != aspect:
            emit(LedgerError(LedgerCode.LEDGER_ASPECT_MISMATCH,
                             f"column 9 must be {aspect} for {resolved_term} ({term_obj.namespace})",
                             _col(8), got=row[8], fix=aspect))

    # step 5
    refs = [v for v in row[5].split("|") if v]
    carried = False
    for value in refs:
        for pfx, pattern in _REFERENCE_FORMS:
            if value.startswith(pfx):
                carried = True
                if not pattern.match(value):
                    emit(LedgerError(LedgerCode.LEDGER_BAD_REFERENCE,
                                     f"{value!r} does not match the {pfx} form", _col(5), got=row[5]))
                break
    if not carried:
        emit(LedgerError(LedgerCode.LEDGER_REFERENCE_REQUIRED,
                         "column 6 needs at least one DOI:, PMID: or GO_REF: value", _col(5), got=row[5]))
    if row[6] not in ctx.eco_map:
        emit(LedgerError(LedgerCode.LEDGER_ECO_UNMAPPED, f"evidence code {row[6]!r} has no ECO mapping in the base",
                         _col(6), got=row[6], options=_sorted_options(ctx.eco_map)))

    # step 6 (by column: 12, 13, 14)
    if not row[11]:
        fix = None
        if known_subject:
            anns = ctx.store.annotations(subject)          # sorted by id; refinement 8
            fix = anns[0].object_type or None
        emit(LedgerError(LedgerCode.LEDGER_BAD_OBJECT_TYPE, "column 12 must be non-empty", _col(11),
                         got=row[11], fix=fix))
    taxa = row[12].split("|")
    if len(taxa) not in (1, 2) or not all(_TAXON_COL_RE.match(t) for t in taxa):
        digits = [_ascii_taxon_digits(t) for t in taxa]
        if len(taxa) in (1, 2) and all(d is not None for d in digits):
            # Not str(int(d)): int() refuses more than 4300 digits (CPython's default limit).
            fix = "|".join("taxon:" + (d.lstrip("0") or "0") for d in digits)
            emit(LedgerError(LedgerCode.LEDGER_BAD_TAXON,
                             "column 13 values must be spelled taxon:<digits>, with no leading zero",
                             _col(12), got=row[12], fix=fix))
        else:
            emit(LedgerError(LedgerCode.LEDGER_BAD_TAXON, "column 13 is one or two |-separated taxon:<digits> values",
                             _col(12), got=row[12], context={"form": "taxon:<digits>"}))
    date = row[13]
    if not (_DATE_RE.match(date) and _real_date(date)):
        m = _ISO_DATE_RE.match(date)
        iso = m.group(1) + m.group(2) + m.group(3) if m else None
        if iso is not None and _real_date(iso):
            emit(LedgerError(LedgerCode.LEDGER_BAD_DATE, "column 14 must be YYYYMMDD", _col(13), got=date, fix=iso))
        else:
            emit(LedgerError(LedgerCode.LEDGER_BAD_DATE, "column 14 must be YYYYMMDD, a real date", _col(13),
                             got=date, context={"form": "YYYYMMDD"}))

    # step 7
    expected_by = ASSIGNED_BY_PREFIX + ctx.key16
    if row[14] != expected_by and (mode == "recheck" or row[14] != ""):
        emit(LedgerError(LedgerCode.LEDGER_ASSIGNED_BY, f"column 15 must be {expected_by} (or empty, to be filled)",
                         _col(14), got=row[14], fix=expected_by))

    # the final row: every non-null fix applied, column 15 filled (append only)
    final = list(row)
    if mode == "append":
        for i, value in fixes.items():
            final[i] = value
        if final[14] == "":
            final[14] = expected_by
        if unfixable:
            deferred.append({"step": 8, "waits_on": sorted(c + 1 for c in unfixable)})
            return AxiomResult(errors, deferred, None, None, None, counters, None)

    # Steps 7a and 8 hash the row as UTF-8 (annotation_id). Append has cleaned every column at
    # step 1a; recheck hashes the row as signed, and a lone surrogate cannot be encoded. Step 1a
    # has already reported it, so the hashing steps are skipped with no second error.
    if not all(_utf8_encodable(c) for c in final):
        return AxiomResult(errors, deferred, final if mode == "recheck" else None, None, None, counters, None)

    # step 7a
    anns, rep = parse_gaf(["\t".join(final)], ctx.eco_map, ctx.primary_id, ctx.term)
    if len(anns) != 1 or any(rep[k] for k in _DROP_COUNTERS) or anns[0].id != annotation_id(final):
        errors.append(LedgerError(LedgerCode.LEDGER_MALFORMED,
                                  "row does not round-trip through parse_gaf as exactly one annotation",
                                  "/fact", got=list(fact)))
        return AxiomResult(errors, deferred, final if mode == "recheck" else None, None, None, counters, rep)
    ann = anns[0]
    if mode == "recheck":
        return AxiomResult(errors, [], final, ann, None, counters, rep)

    # step 8
    key = content_key(ann)
    existing = [{"annotation_id": a.id, "source": ctx.ledger_sources.get(a.id, "base")}
                for a in ctx.store.matching(Prop(ann.subject, ann.qualifier, ann.term, ann.taxon, ann.negated))
                if content_key(a) == key]
    if existing:
        existing.sort(key=lambda e: (e["source"], e["annotation_id"]))
        errors.append(LedgerError(LedgerCode.LEDGER_DUPLICATE, "an identical fact already exists; the row must change",
                                  "/fact", got=list(fact), context={"existing": existing}))
    if errors:
        return AxiomResult(errors, deferred, None, ann, None, counters, rep)

    # step 9
    goal = Prop(ann.subject, ann.qualifier, ann.term, ann.taxon, ann.negated).to_dict()
    verdict = check({"goal": goal, "steps": [{"id": "s1", "rule": "axiom", "conclusion": goal}], "root": "s1"},
                    ctx.store)
    contested_by = sorted({c["annotation"] for c in verdict["conflicts"]})
    block = {"kernel": ctx.kernel_version, "annotation_id": ann.id, "contested_by": contested_by,
             "counters": dict(counters)}
    return AxiomResult([], [], final, ann, block, counters, rep)


# ---------------------------------------------------------------------------
# derived
# ---------------------------------------------------------------------------

def check_derived(body: Any, ctx: CheckContext) -> DerivedResult:
    """Spec §2 ``derived``: the elaborated derivation must be ACCEPTED with no sorry, used or
    unused, and ``conclusion`` must equal the elaborated goal (filled when absent)."""
    shape = 'a derived body is {"derivation": <derivation>, "conclusion"?: <Prop>}'
    # got is the value at field as submitted, or null if absent (spec §7)
    if not isinstance(body, dict):
        return DerivedResult([LedgerError(LedgerCode.LEDGER_BAD_BODY, shape, "/derivation", got=None)],
                             None, None, None)
    body_errors = [] if "derivation" in body else [
        LedgerError(LedgerCode.LEDGER_BAD_BODY, shape, "/derivation", got=None)]
    for k in sorted(set(body) - {"derivation", "conclusion"}):
        body_errors.append(LedgerError(LedgerCode.LEDGER_BAD_BODY, f"unknown key {k!r}; {shape}", _key_pointer(k),
                                       got=body[k]))
    if body_errors:
        return DerivedResult(body_errors, None, None, None)
    elaborated, report = elaborate(body["derivation"], ctx.store)
    verdict = check(elaborated, ctx.store)
    errors: list[LedgerError] = []
    if verdict["verdict"] != "ACCEPTED":
        errors.append(LedgerError(LedgerCode.LEDGER_DERIVATION_REJECTED,
                                  "the kernel rejected the derivation; iterate on context.kernel.errors",
                                  "/derivation", got=None,
                                  context={"kernel": {"errors": verdict["errors"], "elaboration": report}}))
    index_of: dict[str, int] = {}
    steps = elaborated.get("steps") if isinstance(elaborated, dict) else None
    if isinstance(steps, list):
        for i, st in enumerate(steps):
            if isinstance(st, dict) and isinstance(st.get("id"), str):
                index_of.setdefault(st["id"], i)
    for s in verdict["sorries"]:
        idx = index_of.get(s["step"])
        code = LedgerCode.LEDGER_SORRY_USED if s["used"] else LedgerCode.LEDGER_SORRY_UNUSED
        where = "on" if s["used"] else "off"
        errors.append(LedgerError(code, f"sorry step {s['step']!r} is {where} the used chain; a ledger entry proves from facts only",
                                  f"/derivation/steps/{idx}" if idx is not None else "/derivation", got=s))
    goal = verdict["goal"]
    conclusion = body.get("conclusion", goal)
    if goal is not None and conclusion != goal:
        errors.append(LedgerError(LedgerCode.LEDGER_CONCLUSION_MISMATCH, "conclusion must equal the elaborated goal",
                                  "/conclusion", got=body.get("conclusion"), fix=goal))
    block = {"kernel": ctx.kernel_version,
             "axioms": sorted({a["annotation"] for a in verdict["axioms"]}),
             "conflicts": sorted({c["annotation"] for c in verdict["conflicts"]})}
    return DerivedResult(errors, elaborated, goal, block if goal is not None else None)


# ---------------------------------------------------------------------------
# computed (spec §5): schema-checked, then refused
# ---------------------------------------------------------------------------

def _not_yet() -> LedgerError:
    return LedgerError(LedgerCode.NOT_YET_DISCHARGEABLE,
                       "computed entries are refused until discharge exists (spec §0.3, §5)", None)


def check_computed(body: Any, ctx: CheckContext) -> list[LedgerError]:
    if not isinstance(body, dict):
        return [LedgerError(LedgerCode.LEDGER_BAD_BODY, "a computed body is a JSON object (spec §5)", None, got=body),
                _not_yet()]
    errors: list[LedgerError] = []

    def bad(field_: str, message: str, got: Any, *, fix: Any = None, options=(), context=None) -> None:
        errors.append(LedgerError(LedgerCode.LEDGER_BAD_COMPUTED, message, field_, got=got, fix=fix,
                                  options=tuple(options), context=context))

    for k in _COMPUTED_KEYS:
        if k not in body:
            bad(f"/{k}", f"{k} is required", None)
    for k in sorted(set(body) - set(_COMPUTED_KEYS)):
        bad(_key_pointer(k), f"unknown key {k}", body[k])
    if "method" in body:
        m = body["method"]
        if not (isinstance(m, str) and m.startswith("m:") and len(m) > 2 and m == m.lower() and m == m.strip()
                and not any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in m)):     # Cc: C0, DEL, C1
            bad("/method", "method is m: + the lowercased method name, no surrounding whitespace, no control characters", m)
    if "dataset" in body:
        ds = body["dataset"]
        if not (isinstance(ds, dict) and set(ds) == {"id", "sha256"}):
            bad("/dataset", "dataset is {id, sha256}", ds)
        else:
            for k in ("id", "sha256"):
                if not (isinstance(ds[k], str) and ds[k]):
                    bad(f"/dataset/{k}", f"dataset.{k} is a non-empty string", ds[k])
    if "graph_hash" in body and not (isinstance(body["graph_hash"], str) and _GRAPH_HASH_RE.match(body["graph_hash"])):
        bad("/graph_hash", "graph_hash is sha256:<64 hex>, the methods.lock.json form", body["graph_hash"])
    if "preconditions" in body:
        pre = body["preconditions"]
        if not (isinstance(pre, list) and pre):
            bad("/preconditions", "preconditions is a non-empty list", pre)
        else:
            for i, p in enumerate(pre):
                if not (isinstance(p, dict) and set(p) == {"id", "status", "diagnostic"}):
                    bad(f"/preconditions/{i}", "a precondition is {id, status, diagnostic}", p)
                    continue
                if not (isinstance(p["id"], str) and p["id"]):
                    bad(f"/preconditions/{i}/id", "id is a non-empty string", p["id"])
                if p["status"] not in _STATUSES:
                    bad(f"/preconditions/{i}/status", "status is met, unmet or unknown", p["status"], options=_STATUSES)
                if not isinstance(p["diagnostic"], str):
                    bad(f"/preconditions/{i}/diagnostic", "diagnostic is a string", p["diagnostic"])
    if "run" in body:
        run = body["run"]
        if not (isinstance(run, dict) and set(run) == {"command", "container", "exit_code"}):
            bad("/run", "run is {command, container, exit_code}", run)
        else:
            for k in ("command", "container"):
                if not (isinstance(run[k], str) and run[k]):
                    bad(f"/run/{k}", f"run.{k} is a non-empty string", run[k])
            if type(run["exit_code"]) is not int:
                bad("/run/exit_code", "run.exit_code is a JSON integer, not a boolean", run["exit_code"])
    if "conclusion" in body:
        prop = Prop.from_dict(body["conclusion"])
        if prop is None:
            bad("/conclusion", "conclusion is a Prop: subject, qualifier, term, taxon (strings), negated (bool)",
                body["conclusion"])
        else:
            errors.extend(term_errors(prop.term, ctx.store, "/conclusion/term"))
            term = ctx.store.term(prop.term)
            aspect = NAMESPACE_ASPECT.get(term.namespace) if term is not None and not term.obsolete else None
            for err in check_qualifier_aspect(prop.qualifier, prop.term, ctx.store):
                code = (LedgerCode.UNKNOWN_QUALIFIER if err.code == Code.UNKNOWN_QUALIFIER
                        else LedgerCode.QUALIFIER_ASPECT_MISMATCH)
                errors.append(LedgerError(code, err.message, "/conclusion/qualifier", got=prop.qualifier,
                                          options=qualifier_options(aspect)))
            # Not props.TAXON_RE (the kernel's ^NCBITaxon:\d+$): \d takes any Unicode decimal digit
            # and $ matches before a final "\n". The fix comes from a match of this same pattern,
            # so it always clears the error (spec §2).
            if not _ASCII_NCBI_TAXON_RE.match(prop.taxon):
                digits = _ascii_taxon_digits(prop.taxon)
                fix = "NCBITaxon:" + digits if digits is not None else None
                bad("/conclusion/taxon", "taxon is NCBITaxon:<digits>", prop.taxon, fix=fix,
                    context=None if fix else {"form": "NCBITaxon:<digits>"})
    errors.append(_not_yet())
    return errors
```

- [ ] **Step 6: Run the tests**

Run: `$PYTEST tests/test_biolean_ledger_check.py -q`
Expected: 41 passed.

Mutation checks (restore after each): (a) steps 7a/8 over `row` instead of `final` (or drop the fix-application loop): `test_fix_that_creates_duplicate_is_reported_first_try` fails on the obsolete-term row (parse_gaf canonicalizes an alt id on its own, so the alt-id row cannot detect this). (b) `resolved_term = row[4]` regardless of errs3: `test_cross_namespace_replacement_reports_aspect_errors_together` fails (no aspect errors). (c) in `term_errors`, return `fix=primary` without re-checking it: `test_alt_id_with_obsolete_primary_fixes_to_the_replacement` fails. (d) `qualifier_options(aspect)` without `prefix`: `test_qualifier_fix_preserves_not` fails at the `negated is True` assertion. (e) `existing` compared by `a.id == ann.id`: `test_duplicate_of_ledger_row_rejected` and `test_base_row_resubmitted_with_own_assigned_by_is_duplicate` fail. (f) `return` after the first `emit` in step 2: `test_independent_faults_reported_in_one_response` fails. (g) drop `options=_STATUSES`: the status case in `test_computed_schema_checked_then_refused` fails. (h) move the object-type block back below the date block: the column-order assertion in `test_bad_taxon_date_and_empty_object_type_rejected` fails. (i) `got=final` at step 8: `test_base_row_resubmitted_with_own_assigned_by_is_duplicate` fails at `dup.got == row`. (j) `got=extra` in `fact_from_body`: `test_fact_from_body_object_form_and_bad_body` fails. (k) the method rule back to `ord(c) == 0x7F`: the `\u0085` and `\u0080` cases in `test_computed_schema_checked_then_refused` fail. Fix-round checks (controller rulings F–I after the first commit; the code above is the corrected code): drop the ASCII guard in `_ascii_taxon_digits` (or restore step 6's `normalize_taxon`/`int` code): `test_non_ascii_taxon_digits_are_a_bad_taxon_never_a_crash` raises ValueError at `taxon:\u00b2`; restore `fix = normalize_taxon(prop.taxon)` in `check_computed`: `test_computed_taxon_fix_clears_its_error` fails (the fix equals the input); `\Z` → `$` in `_GRAPH_HASH_RE`: `test_computed_graph_hash_with_trailing_newline_is_reported` fails; in `_DB_RE`, the DOI/PMID/GO_REF forms, `_TAXON_COL_RE`, `_DATE_RE`, `_ISO_DATE_RE`: `test_recheck_trailing_newline_fails_each_anchored_column_check` fails at that column's case; validate the computed conclusion taxon with the kernel's `props.TAXON_RE` again: `test_computed_conclusion_taxon_is_ascii_digits_with_no_trailing_newline` fails on both cases (and `$` in `_ASCII_NCBI_TAXON_RE` is then caught at the newline case). Post-review checks (rulings J–M and the pointer addendum): restore `str(int(d))` in step 6: `test_taxon_longer_than_the_int_digit_limit_is_checked_not_raised` raises ValueError; drop the `_utf8_encodable` guard before 7a: `test_recheck_of_an_unencodable_row_reports_and_does_not_raise` raises UnicodeEncodeError; split the joined row with `splitlines()` in 7a: `test_recheck_step_7a_parses_the_row_as_signed` fails at the U+2028 case; accept leading zeros in `_TAXON_COL_RE`: `test_leading_zero_taxon_is_not_canonical_and_cannot_dodge_the_duplicate_check` fails; `got=None` at step 1: `test_bad_columns_got_is_the_fact_as_submitted` fails; unescaped key pointers: `test_derived_body_key_errors_report_the_value_as_submitted` and `test_computed_unknown_key_is_reported_at_its_escaped_pointer` fail.

- [ ] **Step 7: Commit**

```bash
git add src/methods_graph/biolean/ledger/check.py tests/biolean_ledger_fixture.py tests/test_biolean_ledger_check.py tests/fixtures/biolean/ledger/ledger.obo tests/fixtures/biolean/ledger/ledger.gaf tests/fixtures/biolean/ledger/ledger-eco.txt
git commit -m "feat(biolean-ledger): the append check for axiom, derived and computed bodies

Spec §2 over a fixture base with two namespaces, alt ids, and every obsolete
shape. Fixes are applied for steps 4, 7a and 8 so one response reports every
error a caller can act on; deferred names what waits on a null fix.

mutation checked: step 8 on the unfixed row misses the obsolete-term duplicate; the
kernel's bare qualifier list drops NOT| and flips the claim."
```

---

### Task 7: `ledger/integrity.py`, `ledger/load.py`, and `load_store(ledger_dir=…)`

**Files:**
- Create: `src/methods_graph/biolean/ledger/integrity.py`
- Create: `src/methods_graph/biolean/ledger/load.py`
- Modify: `src/methods_graph/biolean/store.py` (`load_store` signature)
- Create: `tests/conftest.py`
- Test: `tests/test_biolean_ledger_integrity.py`, `tests/test_biolean_ledger_load.py` (the parts that need no signature; Task 8 adds the rest over `signed/`)

**Interfaces:**
- Consumes: `format.*`, `errors.*`, `sshsig.*`, `check.check_axiom(mode="recheck")`, `check.check_derived`, `check.content_key`, `check.content_key_json`, `store.load_base`, `store.BaseLoad`, `store.StaticFactStore`, `kernel.check`, `gaf.annotation_id`, `gaf.parse_gaf`.
- Produces (`methods_graph.biolean.ledger.integrity`):
  - `LEDGER_VERIFIER_VERSION = 1` (bump on any change to `ed25519.py`, `sshsig.py`, or integrity steps 1–6; 2 since the final-review fix wave changed `sshsig.py`'s principals rule).
  - `LedgerEntry(file: str, line: int, entry: dict, hash: str)` frozen; property `key16` (from `file`).
  - `LedgerState(ledger_dir, ledger_id, signers, allowed_signers_sha256, files: dict[str, list[LedgerEntry]], files_verified_from_cache=0)`; methods `heads() -> dict[str, {"entries", "head"}]`, `entries() -> list[LedgerEntry]` (by key16 then line), `listed_key16s() -> set[str]`.
  - `read_ledger_id(ledger_dir) -> str`, `read_allowed_signers(ledger_dir) -> tuple[bytes, list[Signer]]` (both raise `LedgerIntegrityError([LEDGER_MALFORMED …])`).
  - `verify_ledger(ledger_dir, *, expected_signers_sha256=None, cache_dir=None, use_cache=False) -> LedgerState` — §3 steps 0–7; raises `LedgerIntegrityError`; every error's `context` carries `file` and `line`.
  - `check_extends(state, older: Path) -> list[LedgerError]` — `LEDGER_ROLLBACK` per §3; `ValueError` when `older` is neither a ledger directory nor a heads map.
  - `integrity_report(state) -> dict` — the `ledger` report block with base-dependent counters `None`.
  - `cache_key(ledger_id, name, data, signers_sha256) -> str`, `default_cache_dir() -> Path`.
- Produces (`methods_graph.biolean.ledger.load`):
  - `BoundEntry(entry: LedgerEntry, status: str, annotation, code, base_annotation_id, rechecked_ok: bool, gaf_report)`; `status ∈ {admitted, stale, superseded_by_base, recorded}`.
  - `LoadedLedger(state, base: BaseLoad, bound: list[BoundEntry], report: dict)`; properties `admitted`, `sources: dict[str, str]`.
  - `bind_entries(state, base, base_store) -> list[BoundEntry]` (raises `LedgerIntegrityError` with `LEDGER_INVALID_ENTRY`).
  - `superseded_by(annotation, base_store) -> str | None`.
  - `ledger_report(state, bound, full_store) -> dict`, `contested_entries(bound, full_store) -> list[str]`.
  - `load_with_ledger(snapshot_dir, ledger_dir, *, obo, gaf, eco, expected_signers_sha256=None, cache_dir=None, use_cache=True) -> tuple[StaticFactStore, dict, LoadedLedger]`.
  - `recheck_derived(loaded, store) -> dict` with `derived_rechecked`, `derived_failed`, `derived_failed_entries: [{file, line, hash, errors}]`.
- Produces (`store.load_store`): the keywords `ledger_dir=None, expected_signers_sha256=None, cache_dir=None, use_cache=True`; with `ledger_dir` the report gains `ledger_gaf` and `ledger`.

- [ ] **Step 1: Write the failing integrity tests (signature-free part)**

`tests/test_biolean_ledger_integrity.py`:

```python
"""Per-file integrity (spec section 3) without signatures: layout, line parsing, the pin, --extends,
the cache key. Task 8 adds the signature-dependent cases over the signed fixture ledger."""
import hashlib
import json
import os
import pathlib

import pytest

from methods_graph.biolean.ledger import integrity as integ
from methods_graph.biolean.ledger.errors import LedgerCode as LC, LedgerIntegrityError
from methods_graph.biolean.ledger.format import canon
from methods_graph.biolean.ledger.integrity import (
    LedgerEntry, LedgerState, cache_key, check_extends, integrity_report, verify_ledger)
from methods_graph.biolean.sshsig import allowed_signers_line, parse_allowed_signers, parse_public_key_line
from methods_graph.biolean.store import load_store
from tests.biolean_ledger_fixture import (
    BASE_FILES, BY_A, KEY16_A, KEY16_B, LEDGER_ID, LFIX, PUB_A, PUB_B, TS, ledger_base, RELEASE)

A_BLOB, _ = parse_public_key_line(PUB_A.read_text())
B_BLOB, _ = parse_public_key_line(PUB_B.read_text())
FILE_A = f"ledger/{KEY16_A}.jsonl"


def skeleton(tmp_path, *, signers=(("alice", A_BLOB),)):
    d = tmp_path / "ledger"
    (d / "ledger").mkdir(parents=True)
    (d / "ledger.json").write_text(json.dumps({"ledger": LEDGER_ID}))
    (d / "allowed_signers").write_text("".join(allowed_signers_line(p, b) for p, b in signers))
    return d


def entry(**over):
    base = ledger_base()
    e = {"v": 1, "kind": "axiom", "ledger": LEDGER_ID,
         "fact": ["UniProtKB", "P10002", "G2", "involved_in", "GO:0000003", "PMID:1", "IDA", "", "P", "", "",
                  "protein", "taxon:9606", "20260925", "biolean:" + KEY16_A, "", ""],
         "base": {**base.digests, "release": RELEASE},
         "check": {"kernel": "0.1.0", "annotation_id": "gaf:0000000000000000", "contested_by": [],
                   "counters": {"new_subject": 0}},
         "prev": "", "by": BY_A, "ts": TS, "sig": "U1NIU0lH"}
    e.update(over)
    return e


def errors_of(d, **kw):
    with pytest.raises(LedgerIntegrityError) as exc:
        verify_ledger(d, **kw)
    return exc.value.errors


def refuse_stat(monkeypatch):
    """Path.is_dir / is_file / is_symlink raise PermissionError on every path in the returned set,
    as Python 3.12 does on EACCES (an unsearchable directory); 3.13+ returns False there."""
    blocked = set()
    for method in ("is_dir", "is_file", "is_symlink"):
        real = getattr(pathlib.Path, method)

        def refuse(self, *args, _real=real, **kwargs):
            if self in blocked:
                raise PermissionError(13, "Permission denied", str(self))
            return _real(self, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, method, refuse)
    return blocked


def test_missing_ledger_files_are_malformed_not_a_crash(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context["file"] == "ledger.json"
    (d / "ledger.json").write_text("not json")
    assert errors_of(d)[0].context["file"] == "ledger.json"
    (d / "ledger.json").write_text(json.dumps({"ledger": "XYZ"}))
    assert errors_of(d)[0].context["file"] == "ledger.json"
    (d / "ledger.json").write_text(json.dumps({"ledger": LEDGER_ID, "extra": 1}))
    assert errors_of(d)[0].context["file"] == "ledger.json"
    (d / "ledger.json").write_text(json.dumps({"ledger": LEDGER_ID}))
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context["file"] == "allowed_signers"
    (d / "allowed_signers").write_text(allowed_signers_line("a", A_BLOB))
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context["file"] == "ledger"
    (d / "ledger").mkdir()
    state = verify_ledger(d)
    assert state.files == {} and state.ledger_id == LEDGER_ID and state.heads() == {}


def test_deep_ledger_json_is_malformed_not_a_crash(tmp_path):
    # Break: catch only OSError and ValueError: json.loads raises RecursionError here.
    d = skeleton(tmp_path)
    (d / "ledger.json").write_text("[" * 200000 + "]" * 200000)
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": "ledger.json", "line": None}


def test_unreadable_ledger_file_is_malformed_not_a_crash(tmp_path, monkeypatch):
    # Break: read the file outside a try: the PermissionError escapes verify_ledger.
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    (d / "ledger" / f"{KEY16_B}.jsonl").write_bytes(b"")
    real_read_bytes = pathlib.Path.read_bytes

    def read_bytes(self):
        if self.name == f"{KEY16_A}.jsonl":
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_bytes(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", read_bytes)
    [e] = errors_of(d)                                              # B's file still verifies: one error
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": FILE_A, "line": None}


def test_unreadable_ledger_directory_is_malformed_not_a_crash(tmp_path, monkeypatch):
    # Break: list ledger/ outside a try: the PermissionError escapes verify_ledger.
    d = skeleton(tmp_path)
    real_listdir = os.listdir

    def listdir(path="."):
        if pathlib.Path(path) == d / "ledger":
            raise PermissionError(13, "Permission denied", str(path))
        return real_listdir(path)

    monkeypatch.setattr(os, "listdir", listdir)
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": "ledger", "line": None}


def test_unstattable_paths_under_the_ledger_are_malformed_not_a_crash(tmp_path, monkeypatch):
    # Break: call Path.is_symlink, is_file or is_dir bare in verify_ledger: Python 3.12 raises there.
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    (d / "ledger" / f"{KEY16_B}.jsonl").write_bytes(b"")
    blocked = refuse_stat(monkeypatch)
    blocked.add(d / FILE_A)
    [e] = errors_of(d)                                              # B's file still verifies: one error
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": FILE_A, "line": None}
    blocked.clear()
    blocked.add(d / "ledger")
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": "ledger", "line": None}


def test_allowed_signers_faults_carry_file_and_line(tmp_path):
    d = skeleton(tmp_path)
    (d / "allowed_signers").write_text(allowed_signers_line("a", A_BLOB) + f'b valid-before="20300101" ssh-ed25519 {PUB_B.read_text().split()[1]}\n')
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": "allowed_signers", "line": 2}
    assert "valid-before" in e.message


def test_allowed_signers_not_utf8_names_the_line_of_the_first_bad_byte(tmp_path):
    # Break: leave line None, count every newline in the file, or drop the + 1.
    d = skeleton(tmp_path)
    (d / "allowed_signers").write_bytes(allowed_signers_line("a", A_BLOB).encode("ascii") + b"# \xff\n"
                                        + allowed_signers_line("b", B_BLOB).encode("ascii"))
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": "allowed_signers", "line": 2}


def test_bad_file_names_and_symlinks_are_malformed(tmp_path):
    # Break: follow the symlink. Its target is an empty file outside ledger/, which is intact, so a
    # verifier that follows the link reports nothing for ledger/<B>.jsonl.
    d = skeleton(tmp_path)
    (d / "ledger" / "notes.txt").write_text("x")
    (d / "ledger" / (KEY16_A.upper() + ".jsonl")).write_bytes(b"")
    (d / "ledger" / ".DS_Store").write_bytes(b"")
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(b"")
    (d / "ledger" / f"{KEY16_B}.jsonl").symlink_to(outside)
    errs = errors_of(d)
    assert {e.code for e in errs} == {LC.LEDGER_MALFORMED}
    assert sorted(e.context["file"] for e in errs) == sorted([
        "ledger/.DS_Store", "ledger/notes.txt", f"ledger/{KEY16_A.upper()}.jsonl", f"ledger/{KEY16_B}.jsonl"])


def test_empty_file_is_intact_and_holds_no_entries(tmp_path):
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    state = verify_ledger(d)
    assert state.files == {KEY16_A: []} and state.heads() == {KEY16_A: {"entries": 0, "head": ""}}
    assert integrity_report(state)["entries"] == 0 and integrity_report(state)["admitted"] is None


def test_bom_crlf_and_missing_final_newline_are_malformed(tmp_path):
    # Break: decode with utf-8-sig; rstrip("\r\n"); accept a last line without "\n".
    d = skeleton(tmp_path)
    line = canon(entry())
    for name, data, lineno in (("bom", b"\xef\xbb\xbf" + line + b"\n", 1), ("crlf", line + b"\r\n", 1),
                               ("no newline", line + b"\n" + line, 2), ("blank", b"\n" + line + b"\n", 1)):
        (d / FILE_A).write_bytes(data)
        errs = errors_of(d)
        assert errs[0].code == LC.LEDGER_MALFORMED and errs[0].context == {"file": FILE_A, "line": lineno}, name


def test_shape_and_character_faults_at_integrity_keep_version_and_wrong_ledger_codes(tmp_path):
    d = skeleton(tmp_path)
    cases = [(LC.LEDGER_VERSION, entry(v=True)), (LC.LEDGER_VERSION, entry(v=1.0)),
             (LC.LEDGER_WRONG_LEDGER, entry(ledger="f" * 32))]
    for code, e in cases:
        (d / FILE_A).write_bytes(canon(e) + b"\n")
        errs = errors_of(d)
        assert errs[0].code == code and errs[0].context["line"] == 1, code
        assert errs[0].fix == (1 if code == LC.LEDGER_VERSION else None), code   # refinement 14
    # Break: pass `fix=f.fix` through for every code: the surrogate case ships the cleaned value as a fix.
    for e in (entry(kind="rule"), entry(extra=1), {**entry(), "fact": entry()["fact"][:16] + ["\ud800"]},
              entry(ts="2026-02-30T00:00:00Z")):
        (d / FILE_A).write_bytes(canon(e) + b"\n")
        errs = errors_of(d)
        assert errs[0].code == LC.LEDGER_MALFORMED and errs[0].context["file"] == FILE_A
        assert errs[0].fix is None, errs[0].field
    (d / FILE_A).write_bytes(canon(entry(kind="rule")) + b"\n")   # the unknown kind keeps its options (refinement 16)
    [e] = errors_of(d)
    assert e.options == ("axiom", "computed", "derived") and e.fix is None


def test_unparseable_sig_is_bad_signature_with_file_and_line(tmp_path):
    d = skeleton(tmp_path)
    for sig in ("U1NIU0lH", "", "U1NI-U0lH", "U1NIU0lH\n"):
        (d / FILE_A).write_bytes(canon(entry(sig=sig)) + b"\n")
        errs = errors_of(d)
        assert errs[0].code == LC.LEDGER_BAD_SIGNATURE and errs[0].context == {"file": FILE_A, "line": 1}, sig


def test_signers_pin_mismatch_fails_before_any_entry_is_read(tmp_path):
    # Break: check the pin after the files are read (the line error would appear too).
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"garbage\n")
    actual = hashlib.sha256((d / "allowed_signers").read_bytes()).hexdigest()
    errs = errors_of(d, expected_signers_sha256=actual)
    assert [e.code for e in errs] == [LC.LEDGER_MALFORMED]
    errs = errors_of(d, expected_signers_sha256="0" * 64)
    assert [e.code for e in errs] == [LC.LEDGER_SIGNERS_MISMATCH]
    assert errs[0].context["file"] == "allowed_signers" and errs[0].context["actual"] == actual


def test_signers_pin_mismatch_reads_no_file_and_marks_no_cache(tmp_path):
    # Break: compare the pin after the read loop, even if it still raises there: the empty file
    # verifies first and, with the cache on, is marked, so the cache directory appears.
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    cache = tmp_path / "cache"
    errs = errors_of(d, expected_signers_sha256="0" * 64, cache_dir=cache, use_cache=True)
    assert [e.code for e in errs] == [LC.LEDGER_SIGNERS_MISMATCH]
    assert not cache.exists()
    verify_ledger(d, cache_dir=cache, use_cache=True)       # control: with no pin the same file is marked
    assert len(os.listdir(cache)) == 1


def test_cache_mark_failure_is_counted_not_raised(tmp_path, monkeypatch):
    # Break: let the OSError from writing a mark escape: an intact ledger then fails to load.
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    (d / "ledger" / f"{KEY16_B}.jsonl").write_bytes(b"")
    not_a_dir = tmp_path / "cache-is-a-file"
    not_a_dir.write_bytes(b"")
    state = verify_ledger(d, cache_dir=not_a_dir, use_cache=True)      # mkdir raises FileExistsError
    assert sorted(state.files) == sorted([KEY16_A, KEY16_B]) and state.cache_mark_failures == 2
    assert integrity_report(state)["cache_mark_failures"] == 2
    _, report = load_store(LFIX, **BASE_FILES, ledger_dir=d, cache_dir=not_a_dir)     # use_cache is on by default
    assert (report["ledger"]["files"], report["ledger"]["cache_mark_failures"]) == (2, 2)
    cache = tmp_path / "cache"
    real_write_bytes = pathlib.Path.write_bytes

    def write_bytes(self, data):
        if self.parent == cache:
            raise PermissionError(13, "Permission denied", str(self))
        return real_write_bytes(self, data)

    monkeypatch.setattr(pathlib.Path, "write_bytes", write_bytes)
    state = verify_ledger(d, cache_dir=cache, use_cache=True)           # mkdir works, the mark does not
    assert state.cache_mark_failures == 2 and os.listdir(cache) == []
    assert verify_ledger(d, cache_dir=cache).cache_mark_failures == 0    # no cache in use: nothing to fail


def test_unstattable_cache_entry_is_a_miss_not_a_crash(tmp_path, monkeypatch):
    # Break: call Path.is_file bare in _cache_hit: Python 3.12 raises there.
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    cache = tmp_path / "cache"
    assert verify_ledger(d, cache_dir=cache, use_cache=True).cache_mark_failures == 0    # a hit is there to find
    blocked = refuse_stat(monkeypatch)
    blocked.update(cache / name for name in os.listdir(cache))
    state = verify_ledger(d, cache_dir=cache, use_cache=True)
    assert (sorted(state.files), state.files_verified_from_cache) == ([KEY16_A], 0)      # a miss, never a hit
    blocked.clear()
    assert verify_ledger(d, cache_dir=cache, use_cache=True).files_verified_from_cache == 1   # control: the hit


def h(label):
    """A 64-hex stand-in for an entry hash: a heads map must carry the real form."""
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _state(tmp_path, files):
    d = tmp_path / "cur"
    (d / "ledger").mkdir(parents=True)
    state_files = {}
    for k, labels in files.items():
        (d / "ledger" / f"{k}.jsonl").write_bytes(b"".join(f"line-{x}\n".encode() for x in labels))
        state_files[k] = [LedgerEntry(f"ledger/{k}.jsonl", i, {"kind": "axiom"}, h(x)) for i, x in enumerate(labels, 1)]
    signers = parse_allowed_signers(allowed_signers_line("a", A_BLOB))
    return LedgerState(d, LEDGER_ID, signers, "0" * 64, state_files)


def test_check_extends_over_directories_and_heads_maps(tmp_path):
    # Break: compare entry counts only (the divergent-chain case then passes).
    state = _state(tmp_path, {KEY16_A: ["h1", "h2", "h3"], KEY16_B: ["g1"]})
    older = tmp_path / "older"
    (older / "ledger").mkdir(parents=True)
    (older / "ledger" / f"{KEY16_A}.jsonl").write_bytes(b"line-h1\nline-h2\n")
    assert check_extends(state, older) == []
    (older / "ledger" / f"{KEY16_A}.jsonl").write_bytes(b"line-h1\nline-zz\n")
    [e] = check_extends(state, older)
    assert e.code == LC.LEDGER_ROLLBACK and e.context["file"] == f"ledger/{KEY16_A}.jsonl"
    (older / "ledger" / f"{KEY16_A}.jsonl").write_bytes(b"line-h1\nline-h2\nline-h3\nline-h4\n")
    assert [e.code for e in check_extends(state, older)] == [LC.LEDGER_ROLLBACK]
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps({KEY16_A: {"entries": 3, "head": h("h3")}, KEY16_B: {"entries": 1, "head": h("g1")}}))
    assert check_extends(state, heads) == []
    heads.write_text(json.dumps({KEY16_A: {"entries": 4, "head": h("h4")}}))
    assert [e.code for e in check_extends(state, heads)] == [LC.LEDGER_ROLLBACK]
    heads.write_text(json.dumps({KEY16_A: {"entries": 3, "head": h("other")}}))    # same count, other chain
    [e] = check_extends(state, heads)
    assert e.code == LC.LEDGER_ROLLBACK and e.context["older_head"] == h("other") and e.context["head"] == h("h3")
    heads.write_text(json.dumps({KEY16_A: {"entries": 0, "head": ""}}))
    assert check_extends(state, heads) == []


def test_deleted_file_fails_extends_unless_its_key_was_removed(tmp_path):
    # Break: drop `if k in listed` in either branch (the revoked key's deletion then fails).
    state = _state(tmp_path, {KEY16_A: ["h1"]})                                    # B's file is gone; A is listed, B is not
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps({KEY16_A: {"entries": 1, "head": h("h1")}, KEY16_B: {"entries": 2, "head": h("g2")}}))
    older = tmp_path / "older"
    (older / "ledger").mkdir(parents=True)
    (older / "ledger" / f"{KEY16_B}.jsonl").write_bytes(b"line-g1\n")
    assert check_extends(state, heads) == []                                        # B was revoked: the one allowed shrink
    assert check_extends(state, older) == []                                        # the same shrink, over a directory
    state.signers = parse_allowed_signers(allowed_signers_line("a", A_BLOB) + allowed_signers_line("b", B_BLOB))
    [e] = check_extends(state, heads)
    assert e.code == LC.LEDGER_ROLLBACK and e.context["file"] == f"ledger/{KEY16_B}.jsonl" and e.context["entries"] == 0
    assert [e.code for e in check_extends(state, older)] == [LC.LEDGER_ROLLBACK]


def test_check_extends_refuses_a_path_that_is_neither(tmp_path):
    state = _state(tmp_path, {KEY16_A: ["h1"]})
    (tmp_path / "junk.json").write_text("[1, 2]")
    with pytest.raises(ValueError):
        check_extends(state, tmp_path / "junk.json")
    with pytest.raises(ValueError):
        check_extends(state, tmp_path / "does-not-exist")
    (tmp_path / "nodir").mkdir()
    with pytest.raises(ValueError):
        check_extends(state, tmp_path / "nodir")


def test_check_extends_turns_unreadable_or_deep_input_into_value_error(tmp_path, monkeypatch):
    # Break: catch only ValueError around the heads map, or read the older tree outside a try.
    state = _state(tmp_path, {KEY16_A: ["h1"]})
    deep = tmp_path / "deep.json"
    deep.write_text("[" * 200000 + "]" * 200000)
    with pytest.raises(ValueError, match="RecursionError"):
        check_extends(state, deep)
    older = tmp_path / "older"
    (older / "ledger" / f"{KEY16_A}.jsonl").mkdir(parents=True)            # a directory with a ledger file's name
    with pytest.raises(ValueError, match="IsADirectoryError"):
        check_extends(state, older)
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps({KEY16_A: {"entries": 1, "head": h("h1")}}))
    assert check_extends(state, heads) == []
    real_read_text = pathlib.Path.read_text

    def read_text(self, *args, **kwargs):
        if self == heads:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    with pytest.raises(ValueError, match="PermissionError"):
        check_extends(state, heads)


def test_check_extends_unstattable_paths_raise_value_error_or_fail_closed(tmp_path, monkeypatch):
    # Break: call Path.is_dir or is_file bare in check_extends: Python 3.12 raises there.
    state = _state(tmp_path, {KEY16_A: ["h1"]})
    older = tmp_path / "older"
    (older / "ledger").mkdir(parents=True)
    (older / "ledger" / f"{KEY16_A}.jsonl").write_bytes(b"line-h1\n")
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps({KEY16_A: {"entries": 1, "head": h("h1")}}))
    assert check_extends(state, older) == [] and check_extends(state, heads) == []
    blocked = refuse_stat(monkeypatch)
    for target, arg in ((older, older), (older / "ledger", older), (heads, heads)):
        blocked.clear()
        blocked.add(target)
        with pytest.raises(ValueError):
            check_extends(state, arg)
    blocked.clear()
    blocked.add(state.ledger_dir / "ledger" / f"{KEY16_A}.jsonl")          # the current file of a listed key
    [e] = check_extends(state, older)
    assert e.code == LC.LEDGER_ROLLBACK and e.context["file"] == f"ledger/{KEY16_A}.jsonl"


def test_check_extends_validates_the_heads_map(tmp_path):
    # Break: drop the heads-map validation (each map below then passes or crashes).
    state = _state(tmp_path, {KEY16_A: ["h1"]})
    heads = tmp_path / "heads.json"
    good = {"entries": 1, "head": h("h1")}
    for bad in ({KEY16_A.upper(): good}, {KEY16_A[:15]: good}, {"../" + KEY16_A[3:]: good},
                {KEY16_A: {"entries": -1, "head": ""}}, {KEY16_A: {"entries": -1, "head": h("h1")}},
                {KEY16_A: {"entries": True, "head": h("h1")}},
                {KEY16_A: {"entries": 1.0, "head": h("h1")}}, {KEY16_A: {"entries": 0, "head": h("h1")}},
                {KEY16_A: {"entries": 1, "head": ""}}, {KEY16_A: {"entries": 1, "head": "h1"}},
                {KEY16_A: {"entries": 1, "head": h("h1").upper()}}, {KEY16_A: {"entries": 1, "head": h("h1") + "\n"}},
                {KEY16_A: {**good, "extra": 1}}, {KEY16_A: [1, h("h1")]}, [good]):
        heads.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            check_extends(state, heads)
    for ok in ({}, {KEY16_A: good}, {KEY16_A: {"entries": 0, "head": ""}}, {KEY16_B: {"entries": 0, "head": ""}}):
        heads.write_text(json.dumps(ok))
        assert check_extends(state, heads) == [], ok


def test_cache_key_includes_file_name_signers_and_verifier_version(monkeypatch):
    # Break: leave the file name out (a byte-identical copy under another name would hit).
    a = cache_key(LEDGER_ID, "a.jsonl", b"data", "s" * 64)
    assert a != cache_key(LEDGER_ID, "b.jsonl", b"data", "s" * 64)
    assert a != cache_key(LEDGER_ID, "a.jsonl", b"data!", "s" * 64)
    assert a != cache_key(LEDGER_ID, "a.jsonl", b"data", "t" * 64)
    assert a != cache_key("f" * 32, "a.jsonl", b"data", "s" * 64)
    monkeypatch.setattr(integ, "LEDGER_VERIFIER_VERSION", 999)
    assert a != cache_key(LEDGER_ID, "a.jsonl", b"data", "s" * 64)
    assert len(a) == 64


def test_integrity_report_has_null_base_counters(tmp_path):
    state = _state(tmp_path, {KEY16_A: ["h1", "h2"]})
    r = integrity_report(state)
    assert (r["files"], r["entries"], r["axioms"], r["derived"], r["computed"]) == (1, 2, 2, 0, 0)
    for k in ("admitted", "rechecked_ok", "stale", "stale_entries", "superseded_by_base", "superseded_entries",
              "duplicate_content", "duplicate_content_entries", "contested", "contested_entries",
              "derived_rechecked", "derived_failed", "derived_failed_entries"):
        assert r[k] is None, k
    assert r["heads"] == {KEY16_A: {"entries": 2, "head": h("h2")}} and r["files_verified_from_cache"] == 0
    assert r["cache_mark_failures"] == 0
    assert r["allowed_signers_sha256"] == "0" * 64


# ---------------------------------------------------------------------------
# over the signed fixture ledger (made once by make_fixtures.py)
# ---------------------------------------------------------------------------
import base64

from methods_graph.biolean.ledger.format import entry_hash, parse_line
from tests.biolean_ledger_fixture import DIGEST_B, LFIX, copy_signed


def _lines(d, k=KEY16_A):
    return (d / f"ledger/{k}.jsonl").read_bytes().split(b"\n")[:-1]


def _write(d, lines, k=KEY16_A):
    (d / f"ledger/{k}.jsonl").write_bytes(b"".join(l + b"\n" for l in lines))


def test_signed_fixture_ledger_verifies_and_reports_heads(tmp_path):
    d = copy_signed(tmp_path)
    state = verify_ledger(d)
    assert {k: len(v) for k, v in state.files.items()} == {KEY16_A: 4, KEY16_B: 1}
    assert [e.entry["kind"] for e in state.files[KEY16_A]] == ["axiom", "axiom", "axiom", "derived"]
    assert state.heads()[KEY16_A]["head"] == state.files[KEY16_A][-1].hash
    assert state.entries()[0].file == f"ledger/{KEY16_A}.jsonl" and state.files_verified_from_cache == 0


def test_repeated_row_in_one_file_is_invalid_not_a_crash(tmp_path, monkeypatch):
    # Break: drop `seen_ids` from step 7. The pair then passes integrity and the loader dies in
    # StaticFactStore with a bare ValueError on the duplicate annotation id.
    monkeypatch.setattr(integ, "verify_sshsig", lambda *a, **k: None)     # the repeat is hand-signed here
    d = copy_signed(tmp_path)
    first, _ = parse_line(_lines(d)[0] + b"\n")
    second = dict(first, prev=entry_hash(first))
    _write(d, [canon(first), canon(second)])
    [e] = errors_of(d)
    assert (e.code, e.field, e.context["line"], e.context["first_line"]) == (LC.LEDGER_INVALID_ENTRY, "/fact", 2, 1)
    assert e.got == first["fact"] and e.context["annotation_id"] == first["check"]["annotation_id"]
    _write(d, [canon(first)])
    assert len(verify_ledger(d).entries()) == 2                            # B's file is untouched


def test_one_byte_change_in_a_signed_entry_fails(tmp_path):
    # Every field is covered by the signature; sig itself by the canonical base64 rule.
    d = copy_signed(tmp_path)
    original = _lines(d)
    line = original[0]
    obj, _ = parse_line(line + b"\n")
    for field_ in ("ts", "prev", "by", "ledger", "v", "kind"):
        pos = line.index(f'"{field_}":'.encode()) + len(field_) + 3
        mutated = bytearray(line)
        mutated[pos + 1] ^= 0x01
        _write(d, [bytes(mutated)] + original[1:])
        errs = errors_of(d)
        assert errs[0].context["file"] == FILE_A and errs[0].context["line"] == 1, field_
    fact_pos = line.index(b'"fact":["UniProtKB"') + len(b'"fact":["')
    mutated = bytearray(line)
    mutated[fact_pos] = ord("u")
    _write(d, [bytes(mutated)] + original[1:])
    assert errors_of(d)[0].code == LC.LEDGER_BAD_SIGNATURE
    # a padding-bit change inside sig: same decoded bytes, refused by the canonical base64 rule
    sig = obj["sig"]
    assert sig.endswith("==") or sig.endswith("=")
    last = sig.rstrip("=")[-1]
    alt = chr(ord(last) + 1) if last not in ("9", "z", "Z", "/") else chr(ord(last) - 1)
    mutated_sig = sig.rstrip("=")[:-1] + alt + sig[len(sig.rstrip("=")):]
    assert base64.b64decode(mutated_sig) == base64.b64decode(sig)          # same bytes: only the padding bits differ
    obj2 = dict(obj, sig=mutated_sig)
    _write(d, [canon(obj2)] + original[1:])
    assert errors_of(d)[0].code == LC.LEDGER_BAD_SIGNATURE


def test_reordered_keys_are_malformed(tmp_path):
    d = copy_signed(tmp_path)
    original = _lines(d)
    obj, _ = parse_line(original[0] + b"\n")
    reordered = json.dumps(obj, separators=(",", ":"), sort_keys=False).encode()
    reordered = b'{"kind":"axiom",' + reordered[1:].replace(b'"kind":"axiom",', b"", 1)
    assert reordered != original[0] and json.loads(reordered) == obj
    _write(d, [reordered] + original[1:])
    errs = errors_of(d)
    assert errs[0].code == LC.LEDGER_MALFORMED and errs[0].context == {"file": FILE_A, "line": 1}


def test_missing_middle_entry_breaks_chain(tmp_path):
    d = copy_signed(tmp_path)
    original = _lines(d)
    _write(d, [original[0], original[2], original[3]])
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_CHAIN_BROKEN and e.context["line"] == 2 and e.field == "/prev"
    assert e.context["expected_prev"] == entry_hash(parse_line(original[0] + b"\n")[0])
    assert "fork_of_line" not in e.context


def test_fork_is_a_chain_break(tmp_path):
    d = copy_signed(tmp_path)
    fork = (LFIX / "signed-variants" / "fork.jsonl").read_bytes()
    (d / FILE_A).write_bytes(fork)
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_CHAIN_BROKEN and e.context["line"] == 4 and e.context["fork_of_line"] == 1
    assert e.got == entry_hash(parse_line(fork.split(b"\n")[0] + b"\n")[0])


def test_unlisted_key_is_unknown_signer(tmp_path):
    d = copy_signed(tmp_path)
    (d / "allowed_signers").write_text(allowed_signers_line("a", A_BLOB))
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_UNKNOWN_SIGNER and e.context["file"] == f"ledger/{KEY16_B}.jsonl"
    assert "SHA256:d4tcaq5zba2R6DiyGsGGv4WQxkz5TnPbHCfGnFPeNNA" in e.message and DIGEST_B in e.message


def test_by_must_match_embedded_key_and_filename(tmp_path):
    d = copy_signed(tmp_path)
    original = _lines(d)
    obj, _ = parse_line(original[0] + b"\n")
    _write(d, [canon(dict(obj, by=BY_A[:-4] + "0000"))] + original[1:])
    errs = errors_of(d)
    assert errs[0].code == LC.LEDGER_SIGNER_MISMATCH and errs[0].context["embedded_key"] == BY_A
    d2 = copy_signed(tmp_path / "two")
    (d2 / f"ledger/{KEY16_B}.jsonl").write_bytes((d2 / FILE_A).read_bytes())     # A's chain under B's name
    errs = errors_of(d2)
    assert errs[0].code == LC.LEDGER_SIGNER_MISMATCH and errs[0].context["file"] == f"ledger/{KEY16_B}.jsonl"


def test_another_keys_line_in_a_file_is_signer_mismatch(tmp_path):
    # the file-name clause of step 3: B's real entry appended to A's file fails at `by` before any
    # chain check (appending it with A's head as prev is not possible without B's key anyway)
    d = copy_signed(tmp_path)
    _write(d, _lines(d) + [_lines(d, KEY16_B)[0]])
    errs = errors_of(d)
    assert errs[0].code == LC.LEDGER_SIGNER_MISMATCH and errs[0].context["line"] == 5


def test_all_entries_in_a_file_share_by(tmp_path, monkeypatch):
    # The same-`by` clause of step 3. A real key16 collision needs a 2^64 grind, so simulate one:
    # B's key digest is made to start with A's key16. B's line then passes "by == embedded key"
    # and "key16 == file name", and only the same-`by` clause refuses it.
    # Break: drop `or (by is not None and obj["by"] != by)`: the line reaches step 5, BAD_SIGNATURE.
    d = copy_signed(tmp_path)
    obj_b, _ = parse_line(_lines(d, KEY16_B)[0] + b"\n")
    (d / f"ledger/{KEY16_B}.jsonl").unlink()                   # the patched digest would fail B's own file too
    fake_b = KEY16_A + DIGEST_B[16:]
    real = integ.key_digest
    monkeypatch.setattr(integ, "key_digest", lambda blob: fake_b if real(blob) == DIGEST_B else real(blob))
    _write(d, _lines(d) + [canon(dict(obj_b, by="sha256:" + fake_b))])
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_SIGNER_MISMATCH and e.context["line"] == 5
    assert e.got == e.context["embedded_key"] == "sha256:" + fake_b   # clauses 1 and 2 held; clause 3 refused


def test_second_key_signature_is_signer_mismatch_or_unknown(tmp_path):
    d = copy_signed(tmp_path)
    original = _lines(d)
    obj_a, _ = parse_line(original[0] + b"\n")
    obj_b, _ = parse_line(_lines(d, KEY16_B)[0] + b"\n")
    _write(d, [canon(dict(obj_a, sig=obj_b["sig"]))] + original[1:])        # B's real signature, by names A
    assert errors_of(d)[0].code == LC.LEDGER_SIGNER_MISMATCH
    d2 = copy_signed(tmp_path / "two")
    (d2 / "allowed_signers").write_text(allowed_signers_line("a", A_BLOB))
    assert errors_of(d2)[0].code == LC.LEDGER_UNKNOWN_SIGNER                  # by names B, B absent


def test_unsupported_allowed_signers_option_refuses_to_load(tmp_path):
    d = copy_signed(tmp_path)
    text = (d / "allowed_signers").read_text().replace('namespaces="biolean-ledger" ssh-ed25519', 'namespaces="biolean-ledger",valid-before="20300101" ssh-ed25519', 1)
    (d / "allowed_signers").write_text(text)
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context["file"] == "allowed_signers" and "valid-before" in e.message


def test_removed_key_fails_whole_ledger_until_its_file_is_deleted(tmp_path):
    # Catches an implementation that skips the unlisted file and loads the rest.
    d = copy_signed(tmp_path)
    (d / "allowed_signers").write_text(allowed_signers_line("a", A_BLOB))
    with pytest.raises(LedgerIntegrityError) as exc:
        verify_ledger(d)
    assert [e.code for e in exc.value.errors] == [LC.LEDGER_UNKNOWN_SIGNER]
    (d / f"ledger/{KEY16_B}.jsonl").unlink()
    state = verify_ledger(d)
    assert set(state.files) == {KEY16_A} and len(state.files[KEY16_A]) == 4


def test_truncated_tail_passes_integrity_and_fails_extends(tmp_path):
    d = copy_signed(tmp_path)
    full = copy_signed(tmp_path / "full")
    original = _lines(d)
    _write(d, original[:3])
    state = verify_ledger(d)
    assert len(state.files[KEY16_A]) == 3
    assert [e.code for e in check_extends(state, full)] == [LC.LEDGER_ROLLBACK]
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps(verify_ledger(full).heads()))
    [e] = check_extends(state, heads)
    assert e.code == LC.LEDGER_ROLLBACK and e.context["older_entries"] == 4 and e.context["entries"] == 3


def test_deleted_file_fails_extends(tmp_path):
    d = copy_signed(tmp_path)
    full = copy_signed(tmp_path / "full")
    (d / f"ledger/{KEY16_B}.jsonl").unlink()
    state = verify_ledger(d)
    [e] = check_extends(state, full)
    assert e.code == LC.LEDGER_ROLLBACK and e.context["file"] == f"ledger/{KEY16_B}.jsonl"


def test_revoked_key_file_deletion_passes_extends(tmp_path):
    d = copy_signed(tmp_path)
    full = copy_signed(tmp_path / "full")
    (d / f"ledger/{KEY16_B}.jsonl").unlink()
    (d / "allowed_signers").write_text(allowed_signers_line("a", A_BLOB))
    state = verify_ledger(d)
    assert check_extends(state, full) == []


def test_divergent_chain_substituted_fails_extends(tmp_path):
    # Same key, same count, a different entry at that position. Catches a count-only check.
    d = copy_signed(tmp_path)
    full = copy_signed(tmp_path / "full")
    fork = (LFIX / "signed-variants" / "fork.jsonl").read_bytes().split(b"\n")[:-1]
    _write(d, fork[:1] + fork[3:4])          # entries 1 and 4 (4's prev is 1's hash): a valid 2-entry chain
    state = verify_ledger(d)
    assert len(state.files[KEY16_A]) == 2
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps({KEY16_A: {"entries": 2, "head": verify_ledger(full).files[KEY16_A][1].hash}}))
    assert [e.code for e in check_extends(state, heads)] == [LC.LEDGER_ROLLBACK]
    assert [e.code for e in check_extends(state, full)] == [LC.LEDGER_ROLLBACK]


def test_signed_entry_with_bad_character_fails_integrity_not_crash(tmp_path):
    d = copy_signed(tmp_path)
    (d / FILE_A).write_bytes((LFIX / "signed-variants" / "surrogate.jsonl").read_bytes())
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context["line"] == 1 and "U+D800" in e.message


def test_check_annotation_id_recomputed(tmp_path):
    d = copy_signed(tmp_path)
    (d / FILE_A).write_bytes((LFIX / "signed-variants" / "bad-annotation-id.jsonl").read_bytes())
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_INVALID_ENTRY and e.field == "/check/annotation_id" and e.context["line"] == 1


def test_chain_from_another_ledger_is_wrong_ledger(tmp_path):
    d = copy_signed(tmp_path)
    (d / "ledger.json").write_text(json.dumps({"ledger": "f" * 32}))
    errs = errors_of(d)
    assert {e.code for e in errs} == {LC.LEDGER_WRONG_LEDGER} and {e.context["line"] for e in errs} == {1}


def test_key16_collision_refused(tmp_path):
    d = copy_signed(tmp_path)
    text = (d / "allowed_signers").read_text()
    (d / "allowed_signers").write_text(text + allowed_signers_line("again", A_BLOB))
    assert errors_of(d)[0].code == LC.LEDGER_MALFORMED


def test_s_plus_l_signature_is_rejected_here_though_openssh_accepts_it(tmp_path):
    from methods_graph.biolean.ed25519 import L
    d = copy_signed(tmp_path)
    original = _lines(d)
    obj, _ = parse_line(original[0] + b"\n")
    blob = bytearray(base64.b64decode(obj["sig"]))
    s = int.from_bytes(blob[-32:], "little") + L
    blob[-32:] = s.to_bytes(32, "little")
    _write(d, [canon(dict(obj, sig=base64.b64encode(bytes(blob)).decode()))] + original[1:])
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_BAD_SIGNATURE and "verify" in e.message


def test_verify_from_cache_is_reported_and_bypassable(tmp_path):
    d = copy_signed(tmp_path)
    cache = tmp_path / "cache"
    s1 = verify_ledger(d, cache_dir=cache, use_cache=True)
    assert s1.files_verified_from_cache == 0 and len(list(cache.iterdir())) == 2
    s2 = verify_ledger(d, cache_dir=cache, use_cache=True)
    assert s2.files_verified_from_cache == 2 and s2.heads() == s1.heads()
    assert verify_ledger(d, cache_dir=cache, use_cache=False).files_verified_from_cache == 0
    assert verify_ledger(d).files_verified_from_cache == 0


def test_cache_hit_does_not_cover_a_renamed_copy(tmp_path):
    d = copy_signed(tmp_path)
    cache = tmp_path / "cache"
    verify_ledger(d, cache_dir=cache, use_cache=True)
    (d / f"ledger/{KEY16_B}.jsonl").write_bytes((d / FILE_A).read_bytes())
    with pytest.raises(LedgerIntegrityError) as exc:
        verify_ledger(d, cache_dir=cache, use_cache=True)
    assert exc.value.errors[0].code == LC.LEDGER_SIGNER_MISMATCH


def test_cache_path_outside_ledger_dir(tmp_path, monkeypatch):
    d = copy_signed(tmp_path / "L")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))                    # restored after the test, like conftest's
    verify_ledger(d, use_cache=True)
    assert (home / ".cache" / "biolean-ledger").is_dir()
    assert not any(p.name == ".cache" for p in d.rglob("*"))
```

- [ ] **Step 2: Write the failing load tests (signature-free part)**

`tests/test_biolean_ledger_load.py`:

```python
"""Base binding, staleness, supersession, duplicate content, contested (spec section 3), over
hand-built ledger states. Task 8 adds load_with_ledger end to end over the signed fixture."""
import pytest

from methods_graph.biolean.gaf import annotation_id, parse_gaf
from methods_graph.biolean.ledger.check import check_axiom
from methods_graph.biolean.ledger.errors import LedgerCode as LC, LedgerIntegrityError
from methods_graph.biolean.ledger.integrity import LedgerEntry, LedgerState
from methods_graph.biolean.ledger.load import bind_entries, ledger_report, superseded_by
from methods_graph.biolean.props import Prop
from methods_graph.biolean.store import StaticFactStore, load_base
from tests.biolean_ledger_fixture import (
    BASE_FILES, BY_A, BY_B, KEY16_A, KEY16_B, LEDGER_ID, LFIX, RELEASE, TS, base_row, context, ledger_base, new_fact)

BASE = ledger_base()
BASE_STORE = StaticFactStore(BASE.terms, BASE.edges, BASE.annotations)
MADE_UP = {"obo": "0" * 64, "gaf": "1" * 64, "eco": "2" * 64, "release": RELEASE}


def axiom_entry(fact, *, key16=KEY16_A, base=None, prev="", contested_by=()):
    row = list(fact)
    row[14] = row[14] or "biolean:" + key16
    return {"v": 1, "kind": "axiom", "ledger": LEDGER_ID, "fact": row,
            "base": base or {**BASE.digests, "release": RELEASE},
            "check": {"kernel": "0.1.0", "annotation_id": annotation_id(row), "contested_by": list(contested_by),
                      "counters": {"new_subject": 0}},
            "prev": prev, "by": BY_A if key16 == KEY16_A else BY_B, "ts": TS, "sig": "x"}


def state(tmp_path, files):
    """files: {key16: [entry dicts]} -> a LedgerState as verify_ledger would build it."""
    return LedgerState(tmp_path, LEDGER_ID, [], "0" * 64,
                       {k: [LedgerEntry(f"ledger/{k}.jsonl", i, e, f"hash{i}") for i, e in enumerate(es, 1)]
                        for k, es in files.items()})


def bind(tmp_path, files, base=BASE, base_store=BASE_STORE):
    st = state(tmp_path, files)
    bound = bind_entries(st, base, base_store)
    full = StaticFactStore(base.terms, base.edges, base.annotations + [b.annotation for b in bound if b.status == "admitted"])
    return bound, ledger_report(st, bound, full), full


def modified_base(tmp_path, *, obo_edit=None, gaf_extra=None):
    d = tmp_path / "base2"
    d.mkdir()
    for name in BASE_FILES.values():
        text = (LFIX / name).read_text(encoding="utf-8")
        if name == "ledger.obo" and obo_edit:
            text = text.replace(*obo_edit)
        if name == "ledger.gaf" and gaf_extra:
            text += "\t".join(gaf_extra) + "\n"
        (d / name).write_text(text, encoding="utf-8")
    base = load_base(d, **BASE_FILES)
    return base, StaticFactStore(base.terms, base.edges, base.annotations)


def test_bind_admits_a_valid_entry_on_its_own_base_and_counts_rechecked_on_another(tmp_path):
    [b], report, full = bind(tmp_path, {KEY16_A: [axiom_entry(new_fact())]})
    assert b.status == "admitted" and b.rechecked_ok is False and b.annotation.assigned_by == "biolean:" + KEY16_A
    assert (report["admitted"], report["rechecked_ok"], report["stale"], report["entries"]) == (1, 0, 0, 1)
    assert full.matching(Prop("UniProtKB:P10002", "involved_in", "GO:0000003", "NCBITaxon:9606", False))[0].id == b.annotation.id
    [b], report, _ = bind(tmp_path, {KEY16_A: [axiom_entry(new_fact(), base=MADE_UP)]})
    assert b.status == "admitted" and b.rechecked_ok is True and report["rechecked_ok"] == 1


def test_hand_signed_entry_skipping_append_is_invalid_on_matching_base(tmp_path):
    # Break: skip the section 2 re-run when the entry's base digests equal the loaded base's.
    e = axiom_entry(new_fact(assigned_by="biolean:" + KEY16_B))          # in A's file
    with pytest.raises(LedgerIntegrityError) as exc:
        bind(tmp_path, {KEY16_A: [e]})
    [err] = exc.value.errors
    assert err.code == LC.LEDGER_INVALID_ENTRY and err.context["code"] == LC.LEDGER_ASSIGNED_BY
    assert err.context["file"] == f"ledger/{KEY16_A}.jsonl" and err.context["line"] == 1


def test_forged_base_does_not_downgrade_invalid_to_stale(tmp_path):
    # Break: send every failure on a non-matching base to `stale`.
    e = axiom_entry(new_fact(db_reference="PMID:0"), base=MADE_UP)
    with pytest.raises(LedgerIntegrityError) as exc:
        bind(tmp_path, {KEY16_A: [e]})
    assert exc.value.errors[0].context["code"] == LC.LEDGER_BAD_REFERENCE


def test_forged_base_invalid_payload_names_the_base_independent_code(tmp_path):
    # Break: keep `first = res.errors[0]`: context.code is OBSOLETE_TERM (step 3 runs before step 5),
    # a code that would have meant `stale` on this base, so the payload contradicts the rule it enforces.
    e = axiom_entry(new_fact(go_id="GO:0000010", db_reference="PMID:0"), base=MADE_UP)   # obsolete term + bad reference
    with pytest.raises(LedgerIntegrityError) as exc:
        bind(tmp_path, {KEY16_A: [e]})
    [err] = exc.value.errors
    assert err.code == LC.LEDGER_INVALID_ENTRY and err.context["same_base"] is False
    assert (err.context["code"], err.field) == (LC.LEDGER_BAD_REFERENCE, "/fact/5")


def test_different_base_recheck_counts_stale_and_lists_ids(tmp_path):
    base2, store2 = modified_base(tmp_path, obo_edit=("name: process grandchild\nnamespace: biological_process\n",
                                                      "name: process grandchild\nnamespace: biological_process\nis_obsolete: true\n"))
    assert store2.term("GO:0000003").obsolete
    e = axiom_entry(new_fact(), base=MADE_UP)                              # admitted elsewhere, obsolete here
    [b], report, full = bind(tmp_path, {KEY16_A: [e]}, base2, store2)
    assert b.status == "stale" and b.code == LC.OBSOLETE_TERM
    assert report["stale"] == 1 and report["admitted"] == 0
    assert report["stale_entries"] == [{"annotation_id": e["check"]["annotation_id"], "code": LC.OBSOLETE_TERM,
                                        "file": f"ledger/{KEY16_A}.jsonl", "line": 1}]
    assert full.matching(Prop("UniProtKB:P10002", "involved_in", "GO:0000003", "NCBITaxon:9606", False)) == ()
    # the same entry on the base it names is INVALID, not stale
    with pytest.raises(LedgerIntegrityError):
        bind(tmp_path, {KEY16_A: [axiom_entry(new_fact(), base={**base2.digests, "release": RELEASE})]}, base2, store2)


def test_superseded_by_base_is_excluded_and_counted(tmp_path):
    # Mutation: compare annotation ids (they differ in column 15, so nothing would ever supersede).
    fact = new_fact()
    caught_up = list(fact)
    caught_up[9], caught_up[10], caught_up[13], caught_up[14] = "gene two", "G2|GENE2", "20261001", "UniProt"
    base2, store2 = modified_base(tmp_path, gaf_extra=caught_up)
    e = axiom_entry(fact, base=MADE_UP)
    [b], report, full = bind(tmp_path, {KEY16_A: [e]}, base2, store2)
    assert b.status == "superseded_by_base" and b.base_annotation_id == annotation_id(caught_up)
    assert report["superseded_by_base"] == 1 and report["superseded_entries"] == [
        {"annotation_id": e["check"]["annotation_id"], "base_annotation_id": annotation_id(caught_up),
         "file": f"ledger/{KEY16_A}.jsonl", "line": 1}]
    rows = full.matching(Prop("UniProtKB:P10002", "involved_in", "GO:0000003", "NCBITaxon:9606", False))
    assert [r.id for r in rows] == [annotation_id(caught_up)]
    assert superseded_by(b.annotation, store2) == annotation_id(caught_up)
    assert superseded_by(b.annotation, BASE_STORE) is None


def test_superseded_wins_over_stale(tmp_path):
    fact = new_fact()
    caught_up = list(fact)
    caught_up[14] = "UniProt"
    base2, store2 = modified_base(tmp_path, gaf_extra=caught_up,
                                  obo_edit=("name: process grandchild\nnamespace: biological_process\n",
                                            "name: process grandchild\nnamespace: biological_process\nis_obsolete: true\n"))
    [b], report, _ = bind(tmp_path, {KEY16_A: [axiom_entry(fact, base=MADE_UP)]}, base2, store2)
    assert b.status == "superseded_by_base" and report["stale"] == 0


def test_base_row_differing_only_in_reference_never_supersedes(tmp_path):
    # Fails against any superseded key looser than step 8's (Prop + code, say).
    row = base_row(1)
    row[5], row[14] = "PMID:200", ""
    e = axiom_entry(row, base=MADE_UP)
    [b], report, _ = bind(tmp_path, {KEY16_A: [e]})
    assert b.status == "admitted" and report["superseded_by_base"] == 0


def test_same_fact_from_two_signers_loads_both_and_is_counted(tmp_path):
    ea = axiom_entry(new_fact(), key16=KEY16_A)
    eb = axiom_entry(new_fact(), key16=KEY16_B)
    bound, report, full = bind(tmp_path, {KEY16_A: [ea], KEY16_B: [eb]})
    assert [b.status for b in bound] == ["admitted", "admitted"]
    ids = sorted([ea["check"]["annotation_id"], eb["check"]["annotation_id"]])
    assert report["duplicate_content"] == 1 and report["duplicate_content_entries"][0]["annotation_ids"] == ids
    assert isinstance(report["duplicate_content_entries"][0]["content_key"], list)
    assert len(full.matching(Prop("UniProtKB:P10002", "involved_in", "GO:0000003", "NCBITaxon:9606", False))) == 2


def test_load_report_contested_is_recomputed(tmp_path):
    # Break: read check.contested_by (the earlier entry recorded [] when it was appended).
    pos = axiom_entry(new_fact(), key16=KEY16_A, contested_by=())
    neg = axiom_entry(new_fact(qualifier="NOT|involved_in", db_reference="PMID:77"), key16=KEY16_B)
    bound, report, _ = bind(tmp_path, {KEY16_A: [pos], KEY16_B: [neg]})
    assert report["contested"] == 2
    assert report["contested_entries"] == sorted([pos["check"]["annotation_id"], neg["check"]["annotation_id"]])
    _, report, _ = bind(tmp_path, {KEY16_A: [pos]})
    assert report["contested"] == 0 and report["contested_entries"] == []


def test_ledger_facts_enter_store_through_parse_gaf(tmp_path):
    e = axiom_entry(new_fact(taxon="taxon:9606|taxon:562"))
    st = state(tmp_path, {KEY16_A: [e]})
    bound = bind_entries(st, BASE, BASE_STORE)
    assert bound[0].gaf_report["multi_taxon"] == 1 and bound[0].gaf_report["annotations"] == 1
    assert bound[0].annotation.interacting_taxon == "NCBITaxon:562"


def test_line_separator_in_column_cannot_inject_a_row(tmp_path):
    # Break: check_axiom step 7a joining the row into one text and splitting it
    # (`parse_gaf("\t".join(final).splitlines(), ...)`). str.splitlines splits on U+2028, so a
    # splitting loader sees a different row (form "a", a different annotation id) plus a dropped
    # fragment, and neither matches what was signed.
    fact = new_fact(gene_product_form_id="a\u2028b", assigned_by="biolean:" + KEY16_A)
    anns, rep = parse_gaf(["\t".join(fact)], BASE.eco_map, BASE.primary_id, BASE.term)
    assert len(anns) == 1 and anns[0].form == "a\u2028b" and anns[0].id == annotation_id(fact) and rep["rows"] == 1
    split, rep2 = parse_gaf("\t".join(fact).splitlines(), BASE.eco_map, BASE.primary_id, BASE.term)
    assert [a.form for a in split] == ["a"] and split[0].id != annotation_id(fact) and rep2["bad_column_count"] == 1
    # the loader's own feed, called directly: at bind, step 1a's LEDGER_BAD_CHARACTER is errors[0] and
    # would hide a split, so the recheck result is what pins step 7a
    res = check_axiom(fact, context(KEY16_A), mode="recheck")
    assert [e.code for e in res.errors] == [LC.LEDGER_BAD_CHARACTER]
    assert res.annotation is not None and res.annotation.id == annotation_id(fact)
    assert res.annotation.form == "a\u2028b" and res.gaf_report["rows"] == 1
    with pytest.raises(LedgerIntegrityError) as exc:
        bind(tmp_path, {KEY16_A: [axiom_entry(fact)]})
    assert exc.value.errors[0].context["code"] == LC.LEDGER_BAD_CHARACTER


def test_derived_entries_are_recorded_and_add_nothing_to_the_store(tmp_path):
    d = {"v": 1, "kind": "derived", "ledger": LEDGER_ID,
         "derivation": {"goal": {}, "steps": [], "root": "s1"},
         "conclusion": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000002",
                        "taxon": "NCBITaxon:9606", "negated": False},
         "base": {**BASE.digests, "release": RELEASE}, "check": {"kernel": "0.1.0", "axioms": [], "conflicts": []},
         "prev": "", "by": BY_A, "ts": TS, "sig": "x"}
    [b], report, full = bind(tmp_path, {KEY16_A: [d]})
    assert b.status == "recorded" and b.annotation is None
    assert (report["derived"], report["admitted"], report["entries"]) == (1, 0, 1)
    assert len(full.annotations("UniProtKB:P10003")) == len(BASE_STORE.annotations("UniProtKB:P10003"))


# ---------------------------------------------------------------------------
# end to end over the signed fixture ledger
# ---------------------------------------------------------------------------
from methods_graph.biolean.ledger.load import load_with_ledger, recheck_derived
from methods_graph.biolean.store import load_store
from methods_graph.biolean.tactics import prove
from tests.biolean_ledger_fixture import KEY16_A as _A, LFIX as _LFIX, signed_store


def test_load_store_with_ledger_admits_the_fixture_entries_and_reports(tmp_path):
    ledger, store_dir = signed_store(tmp_path)
    store, report = load_store(store_dir, gaf="goa_human.gaf", ledger_dir=ledger, use_cache=False)
    block = report["ledger"]
    assert (block["files"], block["entries"], block["axioms"], block["derived"], block["admitted"]) == (2, 5, 4, 1, 4)
    assert (block["stale"], block["superseded_by_base"], block["duplicate_content"], block["rechecked_ok"]) == (0, 0, 0, 0)
    assert block["contested"] == 1 and block["derived_rechecked"] is None
    assert report["ledger_gaf"]["annotations"] == 4 and report["gaf"]["annotations"] == 10
    assert len(store.subjects()) == len(BASE_STORE.subjects()) + 1              # P10006 is new
    assert set(block["heads"]) == {_A, KEY16_B}


def test_same_base_recheck_counts_ok(tmp_path):
    ledger, store_dir = signed_store(tmp_path)
    _, report, loaded = load_with_ledger(store_dir, ledger, gaf="goa_human.gaf", use_cache=False)
    assert report["ledger"]["rechecked_ok"] == 0 and all(not b.rechecked_ok for b in loaded.admitted)


def test_prove_cites_ledger_fact_and_carries_doi(tmp_path):
    ledger, store_dir = signed_store(tmp_path)
    store, _, loaded = load_with_ledger(store_dir, ledger, gaf="goa_human.gaf", use_cache=False)
    d = prove(Prop("UniProtKB:P10006", "involved_in", "GO:0000001", "NCBITaxon:9606", False), store)
    assert d is not None and [s["rule"] for s in d["steps"]] == ["axiom", "is_a", "is_a"]
    from methods_graph.biolean.kernel import check
    v = check(d, store)
    assert v["verdict"] == "ACCEPTED"
    [ax] = v["axioms"]
    assert ax["annotation"] in loaded.sources and any(r.startswith("DOI:") for r in ax["references"])
    assert store.matching(Prop("UniProtKB:P10006", "involved_in", "GO:0000003", "NCBITaxon:9606", False))[0].assigned_by == "biolean:" + _A


def test_verify_recheck_counts_derived(tmp_path):
    ledger, store_dir = signed_store(tmp_path)
    store, _, loaded = load_with_ledger(store_dir, ledger, gaf="goa_human.gaf", use_cache=False)
    out = recheck_derived(loaded, store)
    assert out == {"derived_rechecked": 1, "derived_failed": 0, "derived_failed_entries": []}
    # against a store missing the cited row, the derived entry fails and the kernel errors are listed
    out = recheck_derived(loaded, StaticFactStore(BASE.terms, BASE.edges, []))     # no rows at all
    assert out["derived_failed"] == 1 and out["derived_failed_entries"][0]["errors"][0]["code"] == LC.LEDGER_DERIVATION_REJECTED


def test_hand_signed_variants_load_as_specified(tmp_path):
    ledger, store_dir = signed_store(tmp_path)
    for name, code in (("assigned-by-b.jsonl", LC.LEDGER_ASSIGNED_BY), ("made-up-base.jsonl", LC.LEDGER_BAD_REFERENCE)):
        (ledger / f"ledger/{_A}.jsonl").write_bytes((_LFIX / "signed-variants" / name).read_bytes())
        with pytest.raises(LedgerIntegrityError) as exc:
            load_with_ledger(store_dir, ledger, gaf="goa_human.gaf", use_cache=False)
        assert exc.value.errors[0].code == LC.LEDGER_INVALID_ENTRY and exc.value.errors[0].context["code"] == code, name
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_ledger_integrity.py tests/test_biolean_ledger_load.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.ledger.integrity'`.

- [ ] **Step 4: Implement `integrity.py`**

`src/methods_graph/biolean/ledger/integrity.py`:

```python
"""Per-file integrity (spec §3), ``verify --extends``, and the verification cache.

A ledger is either intact or it is not: ``verify_ledger`` raises ``LedgerIntegrityError``
with every error it found (each carrying ``file`` and ``line`` in ``context``) and nothing
loads. Steps, per file: 0 signers pin; 1 names and the trusted list; 2 canonical line, field
schema, characters; 3 ``by`` against the embedded key and the file name; 4 known signer;
5 signature; 6 chain; 7 the recomputed annotation id, not repeated within the file (and no
    ``computed`` entry in v1).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from methods_graph.biolean.gaf import annotation_id
from methods_graph.biolean.ledger.errors import LedgerCode, LedgerError, LedgerIntegrityError
from methods_graph.biolean.ledger.format import (
    FILE_RE, HEX64_RE, LEDGER_ID_RE, canon, character_errors, entry_hash, parse_line, shape_errors, unsigned)
from methods_graph.biolean.sshsig import (
    NAMESPACE, AllowedSignersError, Signer, SshsigError, find_signer, fingerprint, key_digest,
    parse_allowed_signers, parse_sshsig, verify_sshsig)

# Bump on any change to ed25519.py, sshsig.py, or steps 1-6 below: the cache key carries it.
LEDGER_VERIFIER_VERSION = 1
_KEEP_CODES = frozenset({LedgerCode.LEDGER_VERSION, LedgerCode.LEDGER_WRONG_LEDGER})
_KEY16_RE = re.compile(r"^[0-9a-f]{16}\Z")


@dataclass(frozen=True)
class LedgerEntry:
    file: str                       # "ledger/<key16>.jsonl"
    line: int                       # 1-based
    entry: dict[str, Any]
    hash: str

    @property
    def key16(self) -> str:
        return self.file[len("ledger/"):len("ledger/") + 16]


@dataclass
class LedgerState:
    ledger_dir: Path
    ledger_id: str
    signers: list[Signer]
    allowed_signers_sha256: str
    files: dict[str, list[LedgerEntry]] = field(default_factory=dict)
    files_verified_from_cache: int = 0
    cache_mark_failures: int = 0            # verified files whose cache mark could not be written

    def heads(self) -> dict[str, dict[str, Any]]:
        return {k: {"entries": len(v), "head": v[-1].hash if v else ""} for k, v in sorted(self.files.items())}

    def entries(self) -> list[LedgerEntry]:
        return [e for k in sorted(self.files) for e in self.files[k]]

    def listed_key16s(self) -> set[str]:
        return {s.key16 for s in self.signers}


def _err(code: str, message: str, *, file: str, line: int | None = None, field_: str | None = None,
         got: Any = None, fix: Any = None, options=(), extra: dict[str, Any] | None = None) -> LedgerError:
    context: dict[str, Any] = {"file": file, "line": line}
    if extra:
        context.update(extra)
    return LedgerError(code, message, field_, got=got, fix=fix, options=tuple(options), context=context)


def _path_is(check: Callable[[], bool]) -> bool:
    """``check`` is a bound ``Path.is_file`` / ``is_dir`` / ``is_symlink``, given ``os.path``
    semantics on every supported Python: an OSError means "not that kind of file", never an
    exception. Python 3.12 raises PermissionError there on EACCES (a directory that cannot be
    searched); 3.13+ returns False."""
    try:
        return check()
    except OSError:
        return False


def read_ledger_id(ledger_dir: Path) -> str:
    path = Path(ledger_dir) / "ledger.json"
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:      # RecursionError: a deeply nested ledger.json
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, f"cannot read ledger.json: {exc}", file="ledger.json")])
    if not (isinstance(obj, dict) and set(obj) == {"ledger"} and isinstance(obj["ledger"], str)
            and LEDGER_ID_RE.match(obj["ledger"])):
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, 'ledger.json must be {"ledger": "<32 hex>"}',
                                         file="ledger.json", got=obj)])
    return obj["ledger"]


def read_allowed_signers(ledger_dir: Path) -> tuple[bytes, list[Signer]]:
    path = Path(ledger_dir) / "allowed_signers"
    try:
        data = path.read_bytes()
        signers = parse_allowed_signers(data.decode("utf-8"))
    except OSError as exc:
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, f"cannot read allowed_signers: {exc}", file="allowed_signers")])
    except UnicodeDecodeError as exc:
        line = data.count(b"\n", 0, exc.start) + 1     # lines end at "\n" only, as parse_allowed_signers reads them
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, f"allowed_signers is not UTF-8: {exc}",
                                         file="allowed_signers", line=line)])
    except AllowedSignersError as exc:
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, exc.reason, file="allowed_signers", line=exc.line)])
    return data, signers


# ---------------------------------------------------------------------------
# the cache: "steps 1-6 passed for these exact bytes" on this machine only
# ---------------------------------------------------------------------------

def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "biolean-ledger"


def cache_key(ledger_id: str, name: str, data: bytes, signers_sha256: str) -> str:
    material = "\n".join([ledger_id, name, hashlib.sha256(data).hexdigest(), signers_sha256,
                          str(LEDGER_VERIFIER_VERSION)]).encode("ascii")
    return hashlib.sha256(material).hexdigest()


def _cache_hit(cache_dir: Path, key: str) -> bool:
    """A mark that cannot be stat'ed is a miss, never a hit and never an exception."""
    return _path_is((cache_dir / key).is_file)


def _cache_mark(cache_dir: Path, key: str) -> bool:
    """Mark a verified file; False when the mark cannot be written (``cache_dir`` is a file, a
    read-only parent). The file verified all the same, so the caller counts the failure and
    goes on: a cache is an optimisation and never fails a ledger."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / key).write_bytes(b"")
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# one file
# ---------------------------------------------------------------------------

def _verify_file(name: str, data: bytes, ledger_id: str, signers: list[Signer], *, skip_signatures: bool,
                 ) -> tuple[list[LedgerEntry], list[LedgerError]]:
    file = f"ledger/{name}"
    k = name[:16]
    entries: list[LedgerEntry] = []
    if data == b"":
        return entries, []
    if not data.endswith(b"\n"):
        return entries, [_err(LedgerCode.LEDGER_MALFORMED, "final line has no newline", file=file, line=data.count(b"\n") + 1)]
    prev = ""
    by: str | None = None
    seen_ids: dict[str, int] = {}                  # step 7: a fact may not repeat within one file
    for n, raw in enumerate(data.split(b"\n")[:-1], 1):
        # step 2
        obj, reason = parse_line(raw + b"\n")
        if reason is not None:
            return entries, [_err(LedgerCode.LEDGER_MALFORMED, reason, file=file, line=n)]
        faults = shape_errors(obj, ledger_id=ledger_id, unknown_kind_code=LedgerCode.LEDGER_MALFORMED)
        faults += character_errors(obj)
        if faults:
            out = []
            for f in faults:
                code = f.code if f.code in _KEEP_CODES else LedgerCode.LEDGER_MALFORMED
                # §7: an integrity code carries no value fix; LEDGER_VERSION keeps its `1` (refinement 14),
                # an unknown kind keeps its options (refinement 16).
                out.append(_err(code, f.message, file=file, line=n, field_=f.field, got=f.got,
                                fix=f.fix if code in _KEEP_CODES else None, options=f.options, extra=f.context))
            return entries, out
        # step 3
        try:
            parsed = parse_sshsig(obj["sig"])
        except SshsigError as exc:
            return entries, [_err(LedgerCode.LEDGER_BAD_SIGNATURE, str(exc), file=file, line=n, field_="/sig")]
        digest = key_digest(parsed.public_key_blob)
        embedded = "sha256:" + digest
        fp = fingerprint(parsed.public_key_blob)
        if obj["by"] != embedded or digest[:16] != k or (by is not None and obj["by"] != by):
            return entries, [_err(LedgerCode.LEDGER_SIGNER_MISMATCH,
                                  f"by {obj['by']} must equal the signing key {embedded} ({fp}), match the file name, "
                                  f"and be the same on every line of {file}",
                                  file=file, line=n, field_="/by", got=obj["by"],
                                  extra={"embedded_key": embedded, "fingerprint": fp})]
        by = obj["by"]
        # step 4
        signer = find_signer(signers, parsed.public_key_blob)
        if signer is None or not signer.permits(NAMESPACE):
            return entries, [_err(LedgerCode.LEDGER_UNKNOWN_SIGNER,
                                  f"key {embedded} ({fp}) is not in allowed_signers with {NAMESPACE} permitted",
                                  file=file, line=n, field_="/by", got=obj["by"],
                                  extra={"embedded_key": embedded, "fingerprint": fp})]
        # step 5
        if not skip_signatures:
            try:
                verify_sshsig(obj["sig"], canon(unsigned(obj)))
            except SshsigError as exc:
                return entries, [_err(LedgerCode.LEDGER_BAD_SIGNATURE, str(exc), file=file, line=n, field_="/sig")]
        # step 6
        if obj["prev"] != prev:
            extra: dict[str, Any] = {"expected_prev": prev}
            fork = next((e.line for e in entries if e.hash == obj["prev"]), None)
            if fork is not None:
                extra["fork_of_line"] = fork
            return entries, [_err(LedgerCode.LEDGER_CHAIN_BROKEN,
                                  "prev does not name the previous entry" + (" (a fork)" if fork else ""),
                                  file=file, line=n, field_="/prev", got=obj["prev"], extra=extra)]
        h = entry_hash(obj)
        # step 7
        if obj["kind"] == "axiom":
            recomputed = annotation_id(obj["fact"])
            if recomputed != obj["check"]["annotation_id"]:
                return entries, [_err(LedgerCode.LEDGER_INVALID_ENTRY, "check.annotation_id does not match fact",
                                      file=file, line=n, field_="/check/annotation_id", got=obj["check"]["annotation_id"],
                                      extra={"annotation_id": recomputed})]
            first = seen_ids.get(recomputed)
            if first is not None:                  # append refuses this as LEDGER_DUPLICATE; hand-signed files may not
                return entries, [_err(LedgerCode.LEDGER_INVALID_ENTRY, f"fact repeats line {first} of this file",
                                      file=file, line=n, field_="/fact", got=obj["fact"],
                                      extra={"first_line": first, "annotation_id": recomputed})]
            seen_ids[recomputed] = n
        elif obj["kind"] == "computed":
            return entries, [_err(LedgerCode.LEDGER_INVALID_ENTRY, "v1 never writes a computed entry",
                                  file=file, line=n, field_="/kind", got="computed")]
        entries.append(LedgerEntry(file, n, obj, h))
        prev = h
    return entries, []


# ---------------------------------------------------------------------------
# the whole directory
# ---------------------------------------------------------------------------

def verify_ledger(
    ledger_dir: Path, *, expected_signers_sha256: str | None = None, cache_dir: Path | None = None,
    use_cache: bool = False,
) -> LedgerState:
    """Spec §3 integrity over every ``ledger/*.jsonl``. Raises LedgerIntegrityError, and nothing
    else on hostile input (an unreadable file or directory is LEDGER_MALFORMED); nothing loads
    then. ``use_cache`` skips step 5 for a file whose bytes, name, signers and verifier version
    were verified before on this machine (never used by ``ledger verify``); a mark that cannot be
    written is counted in ``cache_mark_failures``, never raised."""
    ledger_dir = Path(ledger_dir)
    ledger_id = read_ledger_id(ledger_dir)
    signers_bytes, signers = read_allowed_signers(ledger_dir)
    signers_sha = hashlib.sha256(signers_bytes).hexdigest()
    if expected_signers_sha256 is not None and signers_sha != expected_signers_sha256:
        raise LedgerIntegrityError([_err(
            LedgerCode.LEDGER_SIGNERS_MISMATCH,
            "allowed_signers does not match the pinned digest; no entry was read",
            file="allowed_signers", got=signers_sha,
            extra={"expected": expected_signers_sha256, "actual": signers_sha})])
    sub = ledger_dir / "ledger"
    if not _path_is(sub.is_dir):
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, "ledger/ directory is missing", file="ledger")])
    if use_cache and cache_dir is None:
        cache_dir = default_cache_dir()
    try:
        names = sorted(os.listdir(sub))
    except OSError as exc:
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, f"cannot list ledger/: {exc}", file="ledger")])
    errors: list[LedgerError] = []
    files: dict[str, list[LedgerEntry]] = {}
    hits = 0
    mark_failures = 0
    for name in names:
        path = sub / name
        if not FILE_RE.match(name) or _path_is(path.is_symlink) or not _path_is(path.is_file):
            errors.append(_err(LedgerCode.LEDGER_MALFORMED, f"unexpected entry under ledger/: {name}", file=f"ledger/{name}"))
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            errors.append(_err(LedgerCode.LEDGER_MALFORMED, f"cannot read ledger/{name}: {exc}", file=f"ledger/{name}"))
            continue
        key = cache_key(ledger_id, name, data, signers_sha)
        hit = bool(use_cache and cache_dir is not None and _cache_hit(cache_dir, key))
        entries, errs = _verify_file(name, data, ledger_id, signers, skip_signatures=hit)
        if errs:
            errors.extend(errs)
            continue
        if hit:
            hits += 1
        elif use_cache and cache_dir is not None and not _cache_mark(cache_dir, key):
            mark_failures += 1
        files[name[:16]] = entries
    if errors:
        errors.sort(key=lambda e: (e.context["file"], e.context.get("line") or 0))
        raise LedgerIntegrityError(errors)
    return LedgerState(ledger_dir, ledger_id, signers, signers_sha, files, hits, mark_failures)


def integrity_report(state: LedgerState) -> dict[str, Any]:
    """The ``ledger`` report block without a base: base-dependent counters are None."""
    kinds = Counter(e.entry["kind"] for e in state.entries())
    return {
        "files": len(state.files), "entries": sum(kinds.values()),
        "axioms": kinds["axiom"], "derived": kinds["derived"], "computed": kinds["computed"],
        "admitted": None, "rechecked_ok": None, "stale": None, "stale_entries": None,
        "superseded_by_base": None, "superseded_entries": None,
        "duplicate_content": None, "duplicate_content_entries": None,
        "contested": None, "contested_entries": None,
        "heads": state.heads(), "allowed_signers_sha256": state.allowed_signers_sha256,
        "files_verified_from_cache": state.files_verified_from_cache,
        "cache_mark_failures": state.cache_mark_failures,
        "derived_rechecked": None, "derived_failed": None, "derived_failed_entries": None,
    }


# ---------------------------------------------------------------------------
# --extends
# ---------------------------------------------------------------------------

def _older_head(data: bytes) -> tuple[int, str | None]:
    lines = data.split(b"\n")[:-1] if data.endswith(b"\n") else data.split(b"\n")
    lines = [l for l in lines if l]
    if not lines:
        return 0, ""
    obj, reason = parse_line(lines[-1] + b"\n")
    return len(lines), (entry_hash(obj) if reason is None and isinstance(obj, dict) else None)


def _rollback(state: LedgerState, k: str, message: str, older_entries: int, older_head: str | None) -> LedgerError:
    cur = state.files.get(k, [])
    return _err(LedgerCode.LEDGER_ROLLBACK, message, file=f"ledger/{k}.jsonl",
                extra={"older_entries": older_entries, "older_head": older_head,
                       "entries": len(cur), "head": cur[-1].hash if cur else ""})


def _read_or_value_error(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{path}: cannot read: {type(exc).__name__}: {exc}") from exc


def _heads_map_ok(heads: Any) -> bool:
    """Every key a key16; ``entries`` a non-negative JSON integer; ``head`` "" exactly when
    ``entries`` is 0, else 64 lowercase hex (an entry hash)."""
    if not isinstance(heads, dict):
        return False
    for k, v in heads.items():
        if not (_KEY16_RE.match(k) and isinstance(v, dict) and set(v) == {"entries", "head"}):
            return False
        n, head = v["entries"], v["head"]
        if not (type(n) is int and n >= 0 and isinstance(head, str)):
            return False
        if (head != "") if n == 0 else not HEX64_RE.match(head):
            return False
    return True


def check_extends(state: LedgerState, older: Path) -> list[LedgerError]:
    """Spec §3 ``verify --extends``: the current ledger must extend ``older`` (a ledger directory
    or a heads map). Deleting a revoked key's file is the one allowed shrink. Raises ValueError,
    and nothing else, when ``older`` is neither, cannot be read, or is not a valid heads map."""
    older = Path(older)
    listed = state.listed_key16s()
    errors: list[LedgerError] = []
    if _path_is(older.is_dir):
        sub = older / "ledger"
        if not _path_is(sub.is_dir):
            raise ValueError(f"{older}: no ledger/ directory")
        try:
            names = sorted(os.listdir(sub))
        except OSError as exc:
            raise ValueError(f"{sub}: cannot list: {type(exc).__name__}: {exc}") from exc
        for name in names:
            if not FILE_RE.match(name):
                continue
            k = name[:16]
            old = _read_or_value_error(sub / name)
            n_old, head_old = _older_head(old)
            cur_path = state.ledger_dir / "ledger" / name
            if not _path_is(cur_path.is_file):         # a stat failure reads as missing: a listed key fails closed
                if k in listed:
                    errors.append(_rollback(state, k, "file is missing but its key is still listed", n_old, head_old))
                continue
            if not _read_or_value_error(cur_path).startswith(old):
                errors.append(_rollback(state, k, "current file is not a byte extension of the older file", n_old, head_old))
        return errors
    if _path_is(older.is_file):
        try:
            heads = json.loads(older.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError) as exc:
            raise ValueError(f"{older}: not a heads map: {type(exc).__name__}: {exc}") from exc
        if not _heads_map_ok(heads):
            raise ValueError(f'{older}: not a heads map: {{"<key16>": {{"entries": n >= 0, '
                             f'"head": "" when n is 0, else 64 hex}}}}')
        for k in sorted(heads):
            n_old, head_old = heads[k]["entries"], heads[k]["head"]
            cur = state.files.get(k)
            if cur is None:
                if k in listed:
                    errors.append(_rollback(state, k, "file is missing but its key is still listed", n_old, head_old))
                continue
            if len(cur) < n_old:
                errors.append(_rollback(state, k, "fewer entries than the older state", n_old, head_old))
            elif n_old > 0 and cur[n_old - 1].hash != head_old:
                errors.append(_rollback(state, k, "the older head is not at its position in the current chain", n_old, head_old))
        return errors
    raise ValueError(f"{older}: not a ledger directory or a heads.json file")
```

- [ ] **Step 5: Implement `load.py`**

`src/methods_graph/biolean/ledger/load.py`:

```python
"""Loading a ledger beside a base (spec §3): base binding, staleness, supersession, duplicate
content, contested, the ``ledger`` report block, and ``verify --recheck`` for derived entries."""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from methods_graph.biolean.gaf import parse_gaf
from methods_graph.biolean.kernel import check
from methods_graph.biolean.ledger.check import (
    CheckContext, check_axiom, check_derived, content_key, content_key_json)
from methods_graph.biolean.ledger.errors import BASE_INDEPENDENT_CODES, LedgerCode, LedgerError, LedgerIntegrityError
from methods_graph.biolean.ledger.integrity import LedgerEntry, LedgerState, integrity_report, verify_ledger
from methods_graph.biolean.props import Annotation, Prop
from methods_graph.biolean.store import BaseLoad, FactStore, StaticFactStore, load_base

ADMITTED, STALE, SUPERSEDED, RECORDED = "admitted", "stale", "superseded_by_base", "recorded"

# What reading a present base file can raise: gzip.BadGzipFile is an OSError, a truncated gzip is
# EOFError, a corrupt deflate stream is zlib.error, a non-UTF-8 OBO or ECO file is UnicodeDecodeError.
BASE_READ_ERRORS = (OSError, EOFError, UnicodeDecodeError, zlib.error)


def load_base_or_fail(snapshot_dir: Path, *, obo: str, gaf: str, eco: str) -> BaseLoad:
    """`load_base`, with a present but unreadable base file reported as LEDGER_MALFORMED (exit 2,
    JSON) instead of a traceback (spec §7; plan refinement 18). A missing file is the CLI's usage error."""
    try:
        return load_base(snapshot_dir, obo=obo, gaf=gaf, eco=eco)
    except BASE_READ_ERRORS as exc:
        raise LedgerIntegrityError([LedgerError(LedgerCode.LEDGER_MALFORMED,
                                                f"cannot read the store under {snapshot_dir}: {exc}", None,
                                                context={"file": str(snapshot_dir), "line": None})]) from exc


@dataclass
class BoundEntry:
    entry: LedgerEntry
    status: str
    annotation: Annotation | None
    code: str | None                  # the first §2 code, for a stale entry
    base_annotation_id: str | None    # for a superseded entry
    rechecked_ok: bool                # admitted on a base other than the one it names
    gaf_report: dict[str, int] | None


@dataclass
class LoadedLedger:
    state: LedgerState
    base: BaseLoad
    bound: list[BoundEntry]
    report: dict[str, Any]

    @property
    def admitted(self) -> list[BoundEntry]:
        return [b for b in self.bound if b.status == ADMITTED]

    @property
    def sources(self) -> dict[str, str]:
        return {b.annotation.id: f"{b.entry.file}:{b.entry.line}" for b in self.admitted if b.annotation is not None}


def _prop(a: Annotation) -> Prop:
    return Prop(a.subject, a.qualifier, a.term, a.taxon, a.negated)


def superseded_by(annotation: Annotation, base_store: FactStore) -> str | None:
    """The smallest base annotation id with the same content key (spec §1), or None."""
    key = content_key(annotation)
    ids = sorted(a.id for a in base_store.matching(_prop(annotation)) if content_key(a) == key)
    return ids[0] if ids else None


def bind_entries(state: LedgerState, base: BaseLoad, base_store: FactStore) -> list[BoundEntry]:
    """Spec §3 base binding: re-run §2 steps 1-7a on every axiom entry against the loaded base.
    Invalid (integrity failure) when the base matches or the failing check is base-independent;
    otherwise superseded (tested first), stale, or admitted."""
    errors: list[LedgerError] = []
    bound: list[BoundEntry] = []
    for e in state.entries():
        if e.entry["kind"] != "axiom":
            bound.append(BoundEntry(e, RECORDED, None, None, None, False, None))
            continue
        ctx = CheckContext(store=base_store, eco_map=base.eco_map, primary_id=base.primary_id,
                           term=base.term, key16=e.key16)
        res = check_axiom(e.entry["fact"], ctx, mode="recheck")
        same_base = {k: e.entry["base"][k] for k in ("obo", "gaf", "eco")} == base.digests
        if res.errors and (same_base or any(x.code in BASE_INDEPENDENT_CODES for x in res.errors)):
            # Name the check that makes the entry invalid: on its own base any failure does; on another
            # base only a base-independent one (spec §3), since the rest would have meant `stale`.
            first = res.errors[0] if same_base else next(x for x in res.errors if x.code in BASE_INDEPENDENT_CODES)
            errors.append(LedgerError(LedgerCode.LEDGER_INVALID_ENTRY, f"{first.code}: {first.message}", first.field,
                                      got=first.got, context={"file": e.file, "line": e.line, "code": first.code,
                                                              "same_base": same_base}))
            continue
        ann = res.annotation
        sup = superseded_by(ann, base_store) if ann is not None else None
        if sup is not None:
            bound.append(BoundEntry(e, SUPERSEDED, ann, None, sup, False, res.gaf_report))
        elif res.errors:
            bound.append(BoundEntry(e, STALE, ann, res.errors[0].code, None, False, res.gaf_report))
        else:
            bound.append(BoundEntry(e, ADMITTED, ann, None, None, not same_base, res.gaf_report))
    if errors:
        raise LedgerIntegrityError(errors)
    return bound


def _ledger_gaf_report(bound: list[BoundEntry]) -> dict[str, int]:
    total = parse_gaf([], {}, lambda g: None, lambda g: None)[1]        # every key, all zero
    for b in bound:
        if b.status == ADMITTED and b.gaf_report:
            for k, v in b.gaf_report.items():
                total[k] += v
    return total


def contested_entries(bound: list[BoundEntry], full_store: FactStore) -> list[str]:
    """Admitted axiom entries whose Prop has non-empty kernel conflicts over the loaded store
    (base plus every admitted ledger fact). Recomputed; never read from check.contested_by."""
    out = []
    for b in bound:
        if b.status != ADMITTED or b.annotation is None:
            continue
        goal = _prop(b.annotation).to_dict()
        verdict = check({"goal": goal, "steps": [{"id": "s1", "rule": "axiom", "conclusion": goal}], "root": "s1"},
                        full_store)
        if verdict["conflicts"]:
            out.append(b.annotation.id)
    return sorted(out)


def ledger_report(state: LedgerState, bound: list[BoundEntry], full_store: FactStore) -> dict[str, Any]:
    admitted = [b for b in bound if b.status == ADMITTED]
    groups: dict[tuple, list[str]] = {}
    for b in admitted:
        groups.setdefault(content_key(b.annotation), []).append(b.annotation.id)
    dup = sorted(({"content_key": content_key_json(next(b.annotation for b in admitted if b.annotation.id == ids[0])),
                   "annotation_ids": sorted(ids)} for ids in groups.values() if len(ids) > 1),
                 key=lambda d: d["annotation_ids"])
    stale = [b for b in bound if b.status == STALE]
    sup = [b for b in bound if b.status == SUPERSEDED]
    contested = contested_entries(bound, full_store)
    report = integrity_report(state)
    report.update({
        "admitted": len(admitted), "rechecked_ok": sum(1 for b in admitted if b.rechecked_ok),
        "stale": len(stale),
        "stale_entries": [{"annotation_id": b.entry.entry["check"]["annotation_id"], "code": b.code,
                           "file": b.entry.file, "line": b.entry.line} for b in stale],
        "superseded_by_base": len(sup),
        "superseded_entries": [{"annotation_id": b.entry.entry["check"]["annotation_id"],
                                "base_annotation_id": b.base_annotation_id,
                                "file": b.entry.file, "line": b.entry.line} for b in sup],
        "duplicate_content": len(dup), "duplicate_content_entries": dup,
        "contested": len(contested), "contested_entries": contested,
    })
    return report


def load_with_ledger(
    snapshot_dir: Path, ledger_dir: Path, *, obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz",
    eco: str = "gaf-eco-mapping.txt", expected_signers_sha256: str | None = None,
    cache_dir: Path | None = None, use_cache: bool = True,
) -> tuple[StaticFactStore, dict[str, dict[str, Any]], LoadedLedger]:
    """Base, then integrity, then base binding, then the store over base plus admitted facts.
    Raises LedgerIntegrityError (exit 2 at the CLI), including for a base file that is present but
    cannot be read; a missing base file is the CLI's usage error (refinement 18)."""
    base = load_base_or_fail(snapshot_dir, obo=obo, gaf=gaf, eco=eco)
    base_store = StaticFactStore(base.terms, base.edges, base.annotations)
    state = verify_ledger(ledger_dir, expected_signers_sha256=expected_signers_sha256,
                          cache_dir=cache_dir, use_cache=use_cache)
    bound = bind_entries(state, base, base_store)
    admitted = [b.annotation for b in bound if b.status == ADMITTED and b.annotation is not None]
    # A duplicate id here would be a defect: column 15 separates ledger ids from base ids and
    # signers from each other, and integrity step 7 refuses a repeated row within one file.
    full = StaticFactStore(base.terms, base.edges, base.annotations + admitted)
    block = ledger_report(state, bound, full)
    report: dict[str, dict[str, Any]] = {**base.report, "ledger_gaf": _ledger_gaf_report(bound), "ledger": block}
    return full, report, LoadedLedger(state, base, bound, block)


def recheck_derived(loaded: LoadedLedger, store: FactStore) -> dict[str, Any]:
    """``verify --recheck``: re-prove every derived entry (spec §2 derived rule) over ``store``."""
    rechecked = 0
    failed: list[dict[str, Any]] = []
    for b in loaded.bound:
        if b.entry.entry["kind"] != "derived":
            continue
        rechecked += 1
        ctx = CheckContext(store=store, eco_map=loaded.base.eco_map, primary_id=loaded.base.primary_id,
                           term=loaded.base.term, key16=b.entry.key16)
        res = check_derived({"derivation": b.entry.entry["derivation"], "conclusion": b.entry.entry["conclusion"]}, ctx)
        if res.errors:
            failed.append({"file": b.entry.file, "line": b.entry.line, "hash": b.entry.hash,
                           "errors": [e.to_dict() for e in res.errors]})
    return {"derived_rechecked": rechecked, "derived_failed": len(failed), "derived_failed_entries": failed}
```

- [ ] **Step 6: Extend `load_store` and add `conftest.py`**

In `src/methods_graph/biolean/store.py`, replace `load_store` with:

```python
def load_store(
    snapshot_dir: Path,
    *,
    obo: str = "go-basic.obo",
    gaf: str = "goa_human.gaf.gz",
    eco: str = "gaf-eco-mapping.txt",
    ledger_dir: Path | None = None,
    expected_signers_sha256: str | None = None,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> tuple[StaticFactStore, dict[str, dict[str, Any]]]:
    """Read the three files and build the store. Raises FileNotFoundError for a missing file.

    With ``ledger_dir`` the store is base plus admitted ledger facts and the report gains
    ``ledger_gaf`` and ``ledger`` (spec §3); ``LedgerIntegrityError`` is raised when the ledger
    is not intact. The import is function-level: ``kernel`` imports this module and the ledger
    imports ``kernel``, so a module-level import would be a cycle.
    """
    if ledger_dir is not None:
        from methods_graph.biolean.ledger.load import load_with_ledger

        store, report, _ = load_with_ledger(
            snapshot_dir, ledger_dir, obo=obo, gaf=gaf, eco=eco,
            expected_signers_sha256=expected_signers_sha256, cache_dir=cache_dir, use_cache=use_cache)
        return store, report
    base = load_base(snapshot_dir, obo=obo, gaf=gaf, eco=eco)
    return StaticFactStore(base.terms, base.edges, base.annotations), base.report
```

`tests/conftest.py`:

```python
"""Repo-wide fixtures. The ledger's verification cache defaults to ~/.cache/biolean-ledger/;
no ledger test may touch the real home directory, so HOME points at tmp_path for them."""
import pytest


@pytest.fixture(autouse=True)
def _ledger_tests_never_touch_home(request, tmp_path, monkeypatch):
    module = getattr(request, "module", None)
    if module is not None and "biolean_ledger" in module.__name__:
        monkeypatch.setenv("HOME", str(tmp_path))
```

- [ ] **Step 7: Run the tests**

Run: `$PYTEST tests/test_biolean_ledger_integrity.py tests/test_biolean_ledger_load.py tests/test_biolean_store.py -q`
Expected: all pass (13 integrity + 13 load + the store tests).

Mutation checks: (a) `verify_ledger`: move the pin comparison after the `for name in sorted(...)` loop: `test_signers_pin_mismatch_fails_before_any_entry_is_read` fails (two errors). (b) `check_extends`, heads branch: drop the `cur[n_old - 1].hash != head_old` clause: the "same count, other chain" case fails. (c) `bind_entries`: replace the invalid condition with `res.errors and not same_base` → `test_hand_signed_entry_skipping_append_is_invalid_on_matching_base` fails; with `res.errors and same_base` → `test_forged_base_does_not_downgrade_invalid_to_stale` fails. (d) `superseded_by` comparing `a.id == annotation.id`: `test_superseded_by_base_is_excluded_and_counted` fails. (e) `contested_entries` returning ids whose `check.contested_by` is non-empty: `test_load_report_contested_is_recomputed` fails. (f) `cache_key` without `name`: the cache-key test fails. (g) `bind_entries`: restore `first = res.errors[0]`: `test_forged_base_invalid_payload_names_the_base_independent_code` fails with `context.code == OBSOLETE_TERM`. (h) `check_axiom` step 7a (Task 6) feeding `parse_gaf` the joined row split with `splitlines()`: `test_line_separator_in_column_cannot_inject_a_row` fails (`LEDGER_MALFORMED` joins the errors, `annotation` is None, `rows` is 2). (i) `_verify_file` fault loop: pass `fix=f.fix` through for every code: `test_shape_and_character_faults_at_integrity_keep_version_and_wrong_ledger_codes` fails on the surrogate case (`fix == ""`). The `seen_ids` branch of `_verify_file` step 7 is mutation-checked in Task 8 Step 8 (g), because its test needs the signed fixtures. Fix-round checks (ruling N, after the implementer's own extra mutants): move the pin check after the read loop while still raising: `test_signers_pin_mismatch_reads_no_file_and_marks_no_cache` fails (a cache directory appears); follow symlinks (drop the `is_symlink` refusal): `test_bad_file_names_and_symlinks_are_malformed` fails (the link now targets an empty file outside ledger/, which would verify); leave `context.line` None for a non-UTF-8 allowed_signers, or count every newline, or drop the `+ 1`: `test_allowed_signers_not_utf8_names_the_line_of_the_first_bad_byte` fails. Post-review checks (rulings O–Q): let `_cache_mark`'s OSError escape: `test_cache_mark_failure_is_counted_not_raised` raises; drop `RecursionError` from `read_ledger_id`'s catch: `test_deep_ledger_json_is_malformed_not_a_crash` raises; drop the OSError catches around `read_bytes` / `os.listdir`: `test_unreadable_ledger_file_is_malformed_not_a_crash` / `test_unreadable_ledger_directory_is_malformed_not_a_crash` raise PermissionError; let `check_extends` propagate OSError/RecursionError: `test_check_extends_turns_unreadable_or_deep_input_into_value_error` fails; make `_heads_map_ok` return True: `test_check_extends_validates_the_heads_map` fails (a negative `entries` with a valid head is one of its cases); drop `if k in listed` in the directory branch: `test_deleted_file_fails_extends_unless_its_key_was_removed` fails. Round-2 checks (ruling R, Python 3.12 raises PermissionError from pathlib stat helpers on EACCES): restore a bare `Path.is_symlink()` / `is_file()` / `is_dir()` at any of the eight `_path_is` sites: `test_unstattable_paths_under_the_ledger_are_malformed_not_a_crash`, `test_unstattable_cache_entry_is_a_miss_not_a_crash` or `test_check_extends_unstattable_paths_raise_value_error_or_fail_closed` raises (each monkeypatches the pathlib method to raise, so the check runs on every version).

- [ ] **Step 8: Commit**

```bash
git add src/methods_graph/biolean/ledger/integrity.py src/methods_graph/biolean/ledger/load.py src/methods_graph/biolean/store.py tests/conftest.py tests/test_biolean_ledger_integrity.py tests/test_biolean_ledger_load.py
git commit -m "feat(biolean-ledger): per-file integrity, --extends, base binding and the load report

verify_ledger runs spec §3 steps 0-7 over every ledger/*.jsonl and raises on
any failure with file and line. bind_entries re-runs §2 on every axiom entry:
invalid when the base matches or the fault is base-independent, else
superseded, stale or admitted. load_store(ledger_dir=...) delegates through a
function-level import.

mutation checked: pin after the read gives two errors; a count-only extends
check misses a substituted chain; skipping the re-run on a matching base
admits a hand-signed row."
```

---

### Task 8: `ledger/append.py` (`init`, `append`, signing, self-verify), `make_fixtures.py`, the signed fixtures, and the signature-dependent tests

**Files:**
- Create: `src/methods_graph/biolean/ledger/append.py`
- Modify: `tests/biolean_ledger_fixture.py` (fake runner, scenarios, signed copies)
- Create: `tests/fixtures/biolean/ledger/make_fixtures.py` (never collected: its name is not `test_*`)
- Create (generated by `make_fixtures.py`): `tests/fixtures/biolean/ledger/signed/`, `signed-variants/`, `sigs/`
- Test: `tests/test_biolean_ledger_append.py`; append to `tests/test_biolean_ledger_integrity.py` and `tests/test_biolean_ledger_load.py`

**Interfaces:**
- Consumes: `load.load_with_ledger`, `check.*`, `format.*`, `integrity.*`, `sshsig.*`, `store.base_digests`, `store.read_release`.
- Produces (`methods_graph.biolean.ledger.append`):
  - `SignerKey(path: Path, pub_path: Path, blob: bytes, digest: str, key16: str, fingerprint: str, comment: str)`.
  - `read_signer(key: Path) -> SignerKey` — `--key` is a `.pub` or has `<key>.pub` beside it; else `LedgerIntegrityError([LEDGER_UNSUPPORTED_KEY])`.
  - `base_object(store_dir, *, obo, gaf, eco) -> dict` — the §1 `base` object.
  - `init_ledger(ledger_dir, *, store_dir, key, principal=None, obo, gaf, eco, ledger_id=None, allow_fixture_keys=False) -> dict`.
  - `sign(canonical: bytes, key: Path, runner) -> str` — the `sig` value, via `runner(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "biolean-ledger"], input=canonical, capture_output=True, check=True)`; `LedgerIntegrityError([LEDGER_SIGNING_FAILED])` on any failure.
  - `AppendResult(verdict, errors, deferred, entry, hash, file, line)`; `to_json()` gives the §7 payload.
  - `append_entry(ledger_dir, *, kind, body, key, ts, runner, store_dir, obo, gaf, eco, cache_dir=None, use_cache=True, body_error=None) -> AppendResult` — raises `LedgerIntegrityError` for every exit-2 condition; returns `REJECTED` (exit 3) without writing; returns `ACCEPTED` after writing one line.
- Produces (`tests/biolean_ledger_fixture.py` additions): `SIGS`, `fake_runner`, `copy_signed(dest) -> Path`, `signed_store(tmp_path, *, replay=False) -> tuple[Path, Path]` (ledger dir, store dir), `Scenario`, `SIGNED_SEQUENCE`, `SCENARIOS`, `run_scenario(name, tmp_path, *, runner=fake_runner) -> tuple[AppendResult, Path, Path]` (`raw_entry(...)` lives in `make_fixtures.py`, not in the fixture module).

**How signing works in tests (spec §9, "No subprocess").** `fake_runner` asserts the argv is exactly `["ssh-keygen", "-Y", "sign", "-f", <key>, "-n", "biolean-ledger"]` with `input=` bytes, `capture_output=True`, `check=True` and no `text=`, then returns `stdout` = the armor stored at `sigs/<sha256 of input>.sig`. `make_fixtures.py` produces those files by running every scenario once with a recording runner around the real `subprocess.run`. Because `ts` is injected and Ed25519 is deterministic, the bytes signed in a test equal the bytes signed when the fixture was made, byte for byte; the self-verify in `append_entry` then passes. A missing file means a scenario, the envelope, `methods_graph.__version__` or the fixture base changed: the fake raises `AssertionError` naming the file, and the fix is `python tests/fixtures/biolean/ledger/make_fixtures.py` then commit.

- [ ] **Step 1: Write the failing append tests**

`tests/test_biolean_ledger_append.py`:

```python
"""append/init end to end with the fake runner (real ssh-keygen armor made once by make_fixtures.py)."""
import json

import pytest

from methods_graph.biolean.gaf import annotation_id
from methods_graph.biolean.ledger.append import append_entry, base_object, init_ledger, read_signer
from methods_graph.biolean.ledger.errors import LedgerCode as LC, LedgerIntegrityError
from methods_graph.biolean.ledger.format import canon, entry_hash, parse_line, shape_errors
from methods_graph.biolean.ledger.integrity import verify_ledger
from methods_graph.biolean.sshsig import verify_sshsig
from tests.biolean_ledger_fixture import (
    BY_A, BY_B, DIGEST_A, KEY16_A, KEY16_B, KEY_A, KEY_B, LEDGER_ID, LFIX, PUB_A, RELEASE, SCENARIOS,
    SIGNED_SEQUENCE, TS, copy_ledger_store, copy_signed, fake_runner, new_fact, run_scenario, signed_store)


def test_init_writes_allowed_signers_base_json_ledger_json_and_ledger_dir(tmp_path, capsys):
    store = copy_ledger_store(tmp_path / "store")
    out = init_ledger(tmp_path / "L", store_dir=store, key=PUB_A, principal="manu", gaf="goa_human.gaf", ledger_id=LEDGER_ID,
                      allow_fixture_keys=True)
    d = tmp_path / "L"
    assert (d / "ledger").is_dir() and json.loads((d / "ledger.json").read_text()) == {"ledger": LEDGER_ID}
    assert (d / "allowed_signers").read_text() == f'manu namespaces="biolean-ledger" {PUB_A.read_text().strip()}\n'
    base = json.loads((d / "base.json").read_text())
    assert base == base_object(store, gaf="goa_human.gaf") and base["release"] == RELEASE and len(base["obo"]) == 64
    assert out["by"] == BY_A and out["key16"] == KEY16_A and out["fingerprint"].startswith("SHA256:")
    assert out["file"] == f"ledger/{KEY16_A}.jsonl" and out["ledger"] == LEDGER_ID
    assert verify_ledger(d).files == {}
    with pytest.raises(LedgerIntegrityError, match="exists"):
        init_ledger(d, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)


def test_init_defaults_the_principal_to_the_key_comment_and_mints_a_random_id(tmp_path):
    store = copy_ledger_store(tmp_path / "store")
    out = init_ledger(tmp_path / "L", store_dir=store, key=KEY_B, gaf="goa_human.gaf", allow_fixture_keys=True)   # private path: uses b.pub beside it
    assert (tmp_path / "L" / "allowed_signers").read_text().startswith("biolean-fixture-B namespaces=")
    assert len(out["ledger"]) == 32 and out["ledger"] != LEDGER_ID
    out2 = init_ledger(tmp_path / "M", store_dir=store, key=KEY_B, gaf="goa_human.gaf", allow_fixture_keys=True)
    assert out2["ledger"] != out["ledger"]


def test_unsupported_key_type_refused_before_signing(tmp_path):
    # Break: run ssh-keygen -y, or read the type after signing.
    store = copy_ledger_store(tmp_path / "store")
    b64 = PUB_A.read_text().split()[1]
    for kind in ("sk-ssh-ed25519@openssh.com", "ssh-ed25519-cert-v01@openssh.com", "ssh-rsa"):
        pub = tmp_path / f"{kind}.pub"
        pub.write_text(f"{kind} {b64} c\n")
        with pytest.raises(LedgerIntegrityError) as exc:
            read_signer(pub)
        assert exc.value.errors[0].code == LC.LEDGER_UNSUPPORTED_KEY and kind in exc.value.errors[0].message
        with pytest.raises(LedgerIntegrityError) as exc:
            init_ledger(tmp_path / "L", store_dir=store, key=pub, gaf="goa_human.gaf")
        assert exc.value.errors[0].code == LC.LEDGER_UNSUPPORTED_KEY
    with pytest.raises(LedgerIntegrityError) as exc:
        read_signer(tmp_path / "nokey")
    assert exc.value.errors[0].code == LC.LEDGER_UNSUPPORTED_KEY
    signer = read_signer(KEY_A)
    assert (signer.digest, signer.key16, signer.comment, signer.pub_path) == (DIGEST_A, KEY16_A, "biolean-fixture-A", PUB_A)


def test_init_refuses_the_fixture_keys_unless_told_otherwise(tmp_path):
    # Break: drop the FIXTURE_KEY_DIGESTS check; the fixture keys could then start a real ledger.
    store = copy_ledger_store(tmp_path / "store")
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(tmp_path / "L", store_dir=store, key=PUB_A, gaf="goa_human.gaf")
    assert exc.value.errors[0].code == LC.LEDGER_UNSUPPORTED_KEY and "fixture" in exc.value.errors[0].message
    assert not (tmp_path / "L" / "ledger.json").exists()
    assert init_ledger(tmp_path / "L", store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)["key16"] == KEY16_A


def test_init_refuses_a_key16_collision(tmp_path):
    store = copy_ledger_store(tmp_path / "store")
    d = tmp_path / "L"
    (d / "ledger").mkdir(parents=True)
    (d / f"ledger/{KEY16_A}.jsonl").write_bytes(json.dumps({"by": BY_B}).encode() + b"\n")   # A's key16, another signer
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(d, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    assert exc.value.errors[0].code == LC.LEDGER_KEY16_COLLISION and exc.value.errors[0].context["file"] == f"ledger/{KEY16_A}.jsonl"


def test_append_accepts_the_example_fact_and_writes_one_canonical_signed_line(tmp_path):
    res, ledger, store = run_scenario("fresh-axiom", tmp_path)
    assert res.verdict == "ACCEPTED" and res.errors == [] and res.deferred == []
    assert res.file == f"ledger/{KEY16_A}.jsonl" and res.line == 1
    data = (ledger / res.file).read_bytes()
    obj, reason = parse_line(data)
    assert reason is None and obj == res.entry and data == canon(res.entry) + b"\n"
    assert res.hash == entry_hash(res.entry) and len(res.hash) == 64
    assert shape_errors(res.entry, ledger_id=LEDGER_ID) == []
    assert res.entry["prev"] == "" and res.entry["by"] == BY_A and res.entry["ts"] == TS
    assert res.entry["fact"][14] == "biolean:" + KEY16_A and res.entry["check"]["annotation_id"] == annotation_id(res.entry["fact"])
    assert res.entry["base"] == json.loads((ledger / "base.json").read_text())
    assert verify_sshsig(res.entry["sig"], canon({k: v for k, v in res.entry.items() if k != "sig"}))
    payload = res.to_json()
    assert set(payload) == {"verdict", "entry", "hash", "file", "line"}
    state = verify_ledger(ledger)
    assert state.heads() == {KEY16_A: {"entries": 1, "head": res.hash}}


def test_append_chains_prev_and_rejects_without_writing(tmp_path):
    res, ledger, store = run_scenario("signed-append-a", tmp_path)          # a 4th entry by A onto signed/
    assert res.verdict == "ACCEPTED" and res.line == 5                       # A's file: 3 axioms + 1 derived + this
    heads_before = verify_ledger(copy_signed(tmp_path / "pristine")).heads()
    assert res.entry["prev"] == heads_before[KEY16_A]["head"]
    before = (ledger / res.file).read_bytes()
    rej = append_entry(ledger, kind="axiom", body=new_fact(go_id="GO:0009999"), key=KEY_A, ts=TS, runner=fake_runner,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert rej.verdict == "REJECTED" and rej.entry is None and rej.hash is None
    assert [(e.code, e.field) for e in rej.errors] == [(LC.UNKNOWN_TERM, "/fact/4")]
    assert rej.deferred == [{"step": 4, "waits_on": [5]}, {"step": 8, "waits_on": [5]}]
    assert set(rej.to_json()) == {"verdict", "errors", "deferred"}
    assert (ledger / res.file).read_bytes() == before


def test_append_object_form_and_at_file_bodies(tmp_path):
    res, ledger, store = run_scenario("fresh-axiom-object", tmp_path)
    assert res.verdict == "ACCEPTED" and res.entry["fact"] == run_scenario("fresh-axiom", tmp_path / "x")[0].entry["fact"]


def test_append_self_verify_refuses_and_writes_nothing(tmp_path):
    # Break: skip the self-verify (the known-message armor would then be written).
    ledger, store = signed_store(tmp_path)
    known = (LFIX / "known" / "a-one.sig").read_bytes()

    def wrong_runner(argv, *, input, capture_output, check):
        assert argv[:4] == ["ssh-keygen", "-Y", "sign", "-f"]
        return type("R", (), {"stdout": known, "stderr": b"", "returncode": 0})()

    before = (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes()
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(db_reference="PMID:8888"), key=KEY_A, ts=TS, runner=wrong_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert exc.value.errors[0].code == LC.LEDGER_SIGNING_FAILED
    assert (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes() == before


def test_append_runner_failure_names_the_agent_route(tmp_path):
    import subprocess
    ledger, store = signed_store(tmp_path)

    def failing(argv, *, input, capture_output, check):
        raise subprocess.CalledProcessError(255, argv, stderr=b"incorrect passphrase")

    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(db_reference="PMID:8888"), key=KEY_A, ts=TS, runner=failing,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    e = exc.value.errors[0]
    assert e.code == LC.LEDGER_SIGNING_FAILED and "ssh-agent" in e.message and "incorrect passphrase" in e.message


def test_append_refuses_an_unlisted_signer_and_a_key16_collision(tmp_path):
    ledger, store = signed_store(tmp_path)
    (ledger / "allowed_signers").write_text((ledger / "allowed_signers").read_text().replace("fixture-b", "# fixture-b"))
    # removing B's line makes the whole ledger fail integrity (B's file is still there)
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(), key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert exc.value.errors[0].code == LC.LEDGER_UNKNOWN_SIGNER
    (ledger / f"ledger/{KEY16_B}.jsonl").unlink()
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(), key=KEY_B, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert exc.value.errors[0].code == LC.LEDGER_UNKNOWN_SIGNER and "SHA256:" in exc.value.errors[0].message
    # key16 collision: a file under A's key16 whose entries name another full digest
    ledger2, store2 = signed_store(tmp_path / "two")
    text = (ledger2 / f"ledger/{KEY16_A}.jsonl").read_bytes()
    forged = text.replace(BY_A.encode(), (BY_A[:-4] + "0000").encode())
    (ledger2 / f"ledger/{KEY16_A}.jsonl").write_bytes(forged)
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger2, kind="axiom", body=new_fact(), key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store2, gaf="goa_human.gaf", use_cache=False)
    assert exc.value.errors[0].code in (LC.LEDGER_SIGNER_MISMATCH, LC.LEDGER_KEY16_COLLISION)


def test_base_mismatch_refuses_append(tmp_path):
    ledger, store = signed_store(tmp_path)
    obo = store / "go-basic.obo"
    obo.write_text(obo.read_text() + "\n[Term]\nid: GO:0000099\nname: extra\nnamespace: biological_process\n")
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(), key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    e = exc.value.errors[0]
    assert e.code == LC.LEDGER_BASE_MISMATCH and set(e.context) == {"obo", "gaf", "eco"} and e.field == "/base"


def test_append_derived_stores_the_elaborated_derivation(tmp_path):
    res, ledger, store = run_scenario("signed-derived-elaborated", tmp_path)
    assert res.verdict == "ACCEPTED" and res.entry["kind"] == "derived"
    assert res.entry["derivation"]["goal"]["subject"] == "UniProtKB:P10003"
    assert res.entry["conclusion"]["subject"] == "UniProtKB:P10003"
    assert set(res.entry["check"]) == {"kernel", "axioms", "conflicts"} and len(res.entry["check"]["axioms"]) == 1


def test_append_computed_is_schema_checked_then_refused(tmp_path):
    ledger, store = signed_store(tmp_path)
    body = SCENARIOS["fresh-axiom"].body   # a fact, not a computed body: LEDGER_BAD_BODY first
    res = append_entry(ledger, kind="computed", body=body, key=KEY_A, ts=TS, runner=fake_runner,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert res.verdict == "REJECTED" and [e.code for e in res.errors] == [LC.LEDGER_BAD_BODY, LC.NOT_YET_DISCHARGEABLE]
    good = {"method": "m:bcftools plugin fill-tags", "dataset": {"id": "GEO:GSE1", "sha256": "ab" * 32},
            "graph_hash": "sha256:" + "cd" * 32,
            "preconditions": [{"id": "replicates>=3", "status": "met", "diagnostic": "n=4"}],
            "run": {"command": "nextflow run x", "container": "quay.io/x", "exit_code": 0},
            "conclusion": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000003",
                           "taxon": "NCBITaxon:9606", "negated": False}}
    res = append_entry(ledger, kind="computed", body=good, key=KEY_A, ts=TS, runner=fake_runner,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert res.verdict == "REJECTED" and [(e.code, e.field) for e in res.errors] == [(LC.NOT_YET_DISCHARGEABLE, None)]
    assert res.deferred == []


def test_signed_fixture_ledger_is_reproducible_from_its_sequence(tmp_path):
    # Replaying SIGNED_SEQUENCE through the fake runner reproduces signed/ byte for byte, which
    # proves the checked-in fixtures match the current envelope, base and kernel version.
    ledger, store = signed_store(tmp_path, replay=True)
    for name in (f"ledger/{KEY16_A}.jsonl", f"ledger/{KEY16_B}.jsonl", "allowed_signers", "base.json", "ledger.json"):
        assert (ledger / name).read_bytes() == (LFIX / "signed" / name).read_bytes(), name


# ---------------------------------------------------------------------------
# the allowed_signers label; bodies nested too deep or holding a bad character
# ---------------------------------------------------------------------------
import copy

from methods_graph.biolean.ledger.format import MAX_DEPTH


def _pub_with_comment(tmp_path, name, comment):
    pub = tmp_path / f"{name}.pub"
    pub.write_text(f"ssh-ed25519 {PUB_A.read_text().split()[1]} {comment}\n")
    return pub


def test_init_falls_back_to_key16_when_the_key_comment_is_not_a_principal(tmp_path):
    # Break: drop the key16 fallback (AllowedSignersError escapes init on "user@host name"), or keep
    # a comment the allowed_signers reader refuses (the double quote): either way init raises.
    store = copy_ledger_store(tmp_path / "store")
    b64 = PUB_A.read_text().split()[1]
    out = init_ledger(tmp_path / "L1", store_dir=store, key=_pub_with_comment(tmp_path, "spaced", "user@host name"),
                      gaf="goa_human.gaf", allow_fixture_keys=True)
    assert out["principal"] == KEY16_A and out["key16"] == KEY16_A
    text = (tmp_path / "L1" / "allowed_signers").read_text()
    assert text == f'{KEY16_A} namespaces="biolean-ledger" ssh-ed25519 {b64} user@host name\n'
    assert verify_ledger(tmp_path / "L1").files == {}                         # the line reads back
    out = init_ledger(tmp_path / "L2", store_dir=store, key=_pub_with_comment(tmp_path, "quoted", 'say "hi"'),
                      gaf="goa_human.gaf", allow_fixture_keys=True)
    assert out["principal"] == KEY16_A
    text = (tmp_path / "L2" / "allowed_signers").read_text()
    assert text == f'{KEY16_A} namespaces="biolean-ledger" ssh-ed25519 {b64}\n'
    assert verify_ledger(tmp_path / "L2").files == {}


def test_init_refuses_an_explicit_principal_the_reader_would_not_hand_back(tmp_path):
    # Break: let a refused explicit principal fall back to the comment or key16 (init then succeeds
    # under a name nobody asked for), or let AllowedSignersError escape (a traceback, not exit 2);
    # drop the UTF-8 check ("a\udcff" is what argparse gives for a non-UTF-8 byte): UnicodeEncodeError.
    store = copy_ledger_store(tmp_path / "store")
    for bad in ("", "two words", "#hash", "a,b", 'q"t', "nul\x00x", "tab\tx", "a\udcff"):
        with pytest.raises(LedgerIntegrityError) as exc:
            init_ledger(tmp_path / "L", store_dir=store, key=PUB_A, principal=bad, gaf="goa_human.gaf",
                        allow_fixture_keys=True)
        [e] = exc.value.errors
        assert e.code == LC.LEDGER_UNSUPPORTED_KEY and e.got == bad and "principal" in e.message, repr(bad)
        assert not (tmp_path / "L").exists(), repr(bad)                     # refused before anything is written


def _nested(depth):
    """A list ``depth`` containers deep, built without recursion."""
    node = []
    for _ in range(depth - 1):
        node = [node]
    return node


def test_append_body_nested_deeper_than_max_depth_is_a_bad_body(tmp_path):
    # Break: drop the nesting_depth check in append_entry: the canon() round trip after it still
    # refuses these bodies, but as "not a JSON value", so the message no longer says why. Drop both:
    # the 65-deep derived body is accepted by the kernel (it ignores an unknown top-level key) and
    # canon() raises ValueError on the entry; the 65-deep computed body gets LEDGER_BAD_COMPUTED;
    # the 100,000-deep fact comes back as LEDGER_BAD_COLUMNS with the whole body in `got`.
    ledger, store = signed_store(tmp_path)
    before = (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes()

    def append(kind, body):
        return append_entry(ledger, kind=kind, body=body, key=KEY_A, ts=TS, runner=fake_runner,
                            store_dir=store, gaf="goa_human.gaf", use_cache=False)

    derived = copy.deepcopy(SIGNED_SEQUENCE[4][2])
    derived["derivation"]["note"] = _nested(MAX_DEPTH - 1)                 # body, derivation, 63 lists: 65 levels
    res = append("derived", derived)
    assert res.verdict == "REJECTED"
    deep = f"the body is nested deeper than {MAX_DEPTH} levels"
    assert [(e.code, e.field, e.got, e.message) for e in res.errors] == [(LC.LEDGER_BAD_BODY, "/derivation", None, deep)]
    res = append("computed", {"dataset": _nested(MAX_DEPTH)})               # 65 levels
    assert [(e.code, e.field) for e in res.errors] == [(LC.LEDGER_BAD_BODY, None), (LC.NOT_YET_DISCHARGEABLE, None)]
    assert res.errors[0].message == deep
    res = append("computed", {"dataset": _nested(MAX_DEPTH - 1)})           # exactly 64: schema-checked as usual
    codes = [e.code for e in res.errors]
    assert LC.LEDGER_BAD_BODY not in codes and LC.LEDGER_BAD_COMPUTED in codes and codes[-1] == LC.NOT_YET_DISCHARGEABLE
    res = append("axiom", _nested(100_000))
    assert [(e.code, e.field, e.got, e.message) for e in res.errors] == [(LC.LEDGER_BAD_BODY, "/fact", None, deep)]
    json.dumps(res.to_json(), sort_keys=True)                                # printable: the body is not echoed back
    assert (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes() == before


def test_append_body_with_a_bad_character_is_rejected_before_the_runner(tmp_path):
    # Break: drop the character check on derived and computed bodies. The kernel takes any string
    # step id, so the derived entry reaches the signer (and, signed, would be written and then fail
    # verify for the whole ledger at line 5); the computed body loses its LEDGER_BAD_CHARACTER.
    ledger, store = signed_store(tmp_path)
    before = (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes()

    def unreachable(argv, **kwargs):
        raise AssertionError("a body with a bad character reached the signer")

    derived = copy.deepcopy(SIGNED_SEQUENCE[4][2])
    derived["derivation"]["steps"][0]["id"] = "s1\ud800"
    derived["derivation"]["steps"][1]["premises"] = ["s1\ud800"]
    res = append_entry(ledger, kind="derived", body=derived, key=KEY_A, ts=TS, runner=unreachable,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert res.verdict == "REJECTED"
    assert [(e.code, e.field, e.got, e.fix) for e in res.errors] == [
        (LC.LEDGER_BAD_CHARACTER, "/derivation/steps/0/id", "U+D800", "s1"),
        (LC.LEDGER_BAD_CHARACTER, "/derivation/steps/1/premises/0", "U+D800", "s1")]
    good = {"method": "m:bcftools", "dataset": {"id": "GEO:GSE1", "sha256": "ab" * 32},
            "graph_hash": "sha256:" + "cd" * 32,
            "preconditions": [{"id": "replicates>=3", "status": "met", "diagnostic": "n=4e\u0301"}],
            "run": {"command": "nextflow run x", "container": "quay.io/x", "exit_code": 0},
            "conclusion": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000003",
                           "taxon": "NCBITaxon:9606", "negated": False}}
    res = append_entry(ledger, kind="computed", body=good, key=KEY_A, ts=TS, runner=unreachable,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert [(e.code, e.field, e.fix) for e in res.errors] == [
        (LC.LEDGER_BAD_CHARACTER, "/preconditions/0/diagnostic", "n=4\u00e9"), (LC.NOT_YET_DISCHARGEABLE, None, None)]
    assert (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes() == before
    assert len(verify_ledger(ledger).entries()) == 5


def test_hostile_files_are_ledger_errors_not_tracebacks(tmp_path):
    # Break: read the .pub catching only OSError (UnicodeDecodeError escapes); read the existing
    # key16 file as `json.loads(first).get("by")` (AttributeError on a JSON list, IsADirectoryError
    # on a directory); read base.json catching only OSError and ValueError (RecursionError escapes).
    store = copy_ledger_store(tmp_path / "store")
    pub = tmp_path / "binary.pub"
    pub.write_bytes(b"ssh-ed25519 \xff\xfe\n")
    with pytest.raises(LedgerIntegrityError) as exc:
        read_signer(pub)
    assert exc.value.errors[0].code == LC.LEDGER_UNSUPPORTED_KEY
    for name, plant in (("list", lambda p: p.write_bytes(b"[1]\n")), ("directory", lambda p: p.mkdir())):
        d = tmp_path / name
        (d / "ledger").mkdir(parents=True)
        plant(d / f"ledger/{KEY16_A}.jsonl")
        with pytest.raises(LedgerIntegrityError) as exc:
            init_ledger(d, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
        [e] = exc.value.errors
        assert (e.code, e.got) == (LC.LEDGER_KEY16_COLLISION, None), name
    ledger, store = signed_store(tmp_path / "deep")
    (ledger / "base.json").write_text("[" * 1_000_000 + "]" * 1_000_000)          # json.loads overflows on 3.12-3.14
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(), key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.context["file"] == "base.json"


# ---------------------------------------------------------------------------
# bodies that are not JSON values; the key half of the self-verify; init's writes
# ---------------------------------------------------------------------------
import base64
import dataclasses
import pathlib

from methods_graph.biolean.ledger import append as append_mod
from methods_graph.biolean.ledger.errors import LedgerError


def test_append_body_that_is_not_a_json_value_is_a_bad_body(tmp_path):
    # Break: drop the canon(body) round trip. Infinity and NaN (what json.loads reads for 1e999 and
    # NaN) and a 5,000-digit int in a derived body pass the kernel, then canon(entry) raises
    # ValueError; an int-keyed fact dict from the Python API raises TypeError in fact_from_body.
    ledger, store = signed_store(tmp_path)
    before = (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes()

    def append(kind, body):
        return append_entry(ledger, kind=kind, body=body, key=KEY_A, ts=TS, runner=fake_runner,
                            store_dir=store, gaf="goa_human.gaf", use_cache=False)

    for note in (float("inf"), float("-inf"), float("nan"), 10 ** 5000):
        derived = copy.deepcopy(SIGNED_SEQUENCE[4][2])
        derived["derivation"]["note"] = note
        res = append("derived", derived)
        assert [(e.code, e.field, e.got) for e in res.errors] == [(LC.LEDGER_BAD_BODY, "/derivation", None)], type(note)
        json.dumps(res.to_json(), allow_nan=False)                           # strict JSON: nothing echoed back
    res = append("computed", {"method": float("nan")})
    assert [(e.code, e.field) for e in res.errors] == [(LC.LEDGER_BAD_BODY, None), (LC.NOT_YET_DISCHARGEABLE, None)]
    for body in (dict(enumerate(new_fact())), new_fact(db_reference=float("nan"))):
        res = append("axiom", body)
        assert [(e.code, e.field, e.got) for e in res.errors] == [(LC.LEDGER_BAD_BODY, "/fact", None)], type(body)
    assert (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes() == before


def test_append_self_verify_refuses_a_signature_by_another_key(tmp_path, monkeypatch):
    # Break: skip the key comparison after verify_sshsig (`if False:`). A signature that verifies,
    # but under another key than the one --key names (here the verifier is made to report B's
    # key), is then written to A's file.
    ledger, store = signed_store(tmp_path)
    before = (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes()
    real, signer_b = append_mod.verify_sshsig, read_signer(KEY_B)
    monkeypatch.setattr(append_mod, "verify_sshsig", lambda sig, message: real(sig, message) and signer_b.blob)
    scn = SCENARIOS["signed-append-a"]
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind=scn.kind, body=scn.body, key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_SIGNING_FAILED and "ssh-agent" in e.message
    assert signer_b.fingerprint in e.message and read_signer(KEY_A).fingerprint in e.message
    assert (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes() == before


def test_init_builds_and_checks_everything_before_mkdir(tmp_path, monkeypatch):
    # Break: move base_object after mkdir (a bad store leaves a directory behind); drop the
    # read-back of the allowed_signers line (init writes a line that does not permit the ledger
    # namespace); keep a comment that is not UTF-8 text (UnicodeEncodeError at the write).
    store = copy_ledger_store(tmp_path / "store")
    b64 = PUB_A.read_text().split()[1]
    signer = dataclasses.replace(read_signer(PUB_A), comment="c\udcff")
    assert append_mod._signers_entry(signer, None) == (
        KEY16_A, f'{KEY16_A} namespaces="biolean-ledger" ssh-ed25519 {b64}\n'.encode("ascii"))

    def bad_store(*args, **kwargs):
        raise LedgerIntegrityError([LedgerError(LC.LEDGER_MALFORMED, "cannot read the store", None)])

    with monkeypatch.context() as m:
        m.setattr(append_mod, "base_object", bad_store)
        with pytest.raises(LedgerIntegrityError):
            init_ledger(tmp_path / "B", store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    assert not (tmp_path / "B").exists()
    real = append_mod.allowed_signers_line
    monkeypatch.setattr(append_mod, "allowed_signers_line", lambda principal, blob, comment="": real(
        principal, blob, comment).replace('namespaces="biolean-ledger"', 'namespaces="other"'))
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(tmp_path / "N", store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    assert exc.value.errors[0].code == LC.LEDGER_UNSUPPORTED_KEY and "read back" in exc.value.errors[0].message
    assert not (tmp_path / "N").exists()


def test_unwritable_ledger_paths_are_malformed_not_tracebacks(tmp_path, monkeypatch):
    # Break: drop the OSError catch around init's mkdir (FileExistsError: the ledger path is a
    # file) or around append's write (PermissionError, after signing).
    store = copy_ledger_store(tmp_path / "store")
    afile = tmp_path / "afile"
    afile.write_text("x")
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(afile, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": str(afile), "line": None}
    ledger, store = signed_store(tmp_path / "S")
    target = ledger / f"ledger/{KEY16_A}.jsonl"
    before = target.read_bytes()
    real_open = pathlib.Path.open

    def refuse_append(self, mode="r", *args, **kwargs):
        if mode == "ab":
            raise PermissionError(13, "Permission denied", str(self))
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", refuse_append)
    scn = SCENARIOS["signed-append-a"]
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind=scn.kind, body=scn.body, key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": f"ledger/{KEY16_A}.jsonl", "line": 5}
    assert target.read_bytes() == before


def test_init_survives_a_stat_that_raises(tmp_path, monkeypatch):
    # Break: a bare Path.exists() in init_ledger. Python 3.12 raises PermissionError on EACCES (a
    # directory that cannot be searched); 3.13+ returns False. The ledger.json check treats a
    # failed stat as absent (mkdir then reports the path); the key16-file check fails closed.
    store = copy_ledger_store(tmp_path / "store")
    new, old = tmp_path / "new", tmp_path / "old"
    (old / "ledger").mkdir(parents=True)
    blocked = {new / "ledger.json", new, old / f"ledger/{KEY16_A}.jsonl"}
    real_exists, real_mkdir = pathlib.Path.exists, pathlib.Path.mkdir

    def exists(self, *args, **kwargs):
        if self in blocked:
            raise PermissionError(13, "Permission denied", str(self))
        return real_exists(self, *args, **kwargs)

    def mkdir(self, *args, **kwargs):
        if self in blocked:
            raise PermissionError(13, "Permission denied", str(self))
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "exists", exists)
    monkeypatch.setattr(pathlib.Path, "mkdir", mkdir)
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(new, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": str(new), "line": None}
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(old, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": f"ledger/{KEY16_A}.jsonl", "line": None}
    monkeypatch.undo()
    assert not new.exists() and sorted(p.name for p in old.iterdir()) == ["ledger"]     # nothing written


def test_init_names_why_a_key_does_not_read_back(tmp_path):
    # Break: drop the AllowedSignersError reason from the read-back refusal. A small-order key
    # passes parse_public_key_line, and only the allowed_signers reader refuses it.
    store = copy_ledger_store(tmp_path / "store")
    blob = b"".join(len(part).to_bytes(4, "big") + part for part in (b"ssh-ed25519", bytes([1]) + bytes(31)))
    pub = tmp_path / "small.pub"
    pub.write_text(f"ssh-ed25519 {base64.b64encode(blob).decode('ascii')} small@host\n")
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(tmp_path / "L", store_dir=store, key=pub, gaf="goa_human.gaf")
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_UNSUPPORTED_KEY and "small-order" in e.message
    assert not (tmp_path / "L").exists()
```

- [ ] **Step 2: Write the signature-dependent integrity and load tests**

Append to `tests/test_biolean_ledger_integrity.py`:

```python
# Folded into the whole-file block of `tests/test_biolean_ledger_integrity.py` above: after Task 8 the committed module already holds
# these additions (synced from commit 6e54f45); the tests are named in the mutation list below.
```

Append to `tests/test_biolean_ledger_load.py`:

```python
# Folded into the whole-file block of `tests/test_biolean_ledger_load.py` above: after Task 8 the committed module already holds
# these additions (synced from commit 6e54f45); the tests are named in the mutation list below.
```

- [ ] **Step 3: Extend the fixture module**

Append to `tests/biolean_ledger_fixture.py`:

```python
# Folded into the whole-file block of `tests/biolean_ledger_fixture.py` above: after Task 8 the committed module already holds
# these additions (synced from commit 6e54f45); the tests are named in the mutation list below.
```

The `import shutil` and `from methods_graph.biolean.gaf import GAF_COLUMNS` at the top of the module (Task 6) already cover `copy_signed` and the object-form scenario. `init_ledger` refuses the fixture keys through `FIXTURE_KEY_DIGESTS`; the fixtures bypass it with `allow_fixture_keys=True`, a keyword the CLI never passes.

- [ ] **Step 4: Write `make_fixtures.py`**

`tests/fixtures/biolean/ledger/make_fixtures.py`:

```python
"""Regenerate every signed fixture with the real ssh-keygen. Run from the repo root:

    .venv/bin/python tests/fixtures/biolean/ledger/make_fixtures.py

Not a test (the suite never runs it). Ed25519 and sshsig carry no randomness, so unchanged
inputs give byte-identical output. Re-run after any change to the entry envelope, the kernel
version, the fixture base, SIGNED_SEQUENCE or SCENARIOS, then commit the result.

Writes: signed/ (the fixture ledger), signed-variants/ (hand-signed lines that must fail in a
specific way), sigs/<sha256 of the bytes signed>.sig (real armor for every append a test makes).
Keys come from keys/ (never regenerated; their digests are pinned in code).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from methods_graph.biolean.gaf import annotation_id                                    # noqa: E402
from methods_graph.biolean.ledger.append import sign                                   # noqa: E402
from methods_graph.biolean.ledger.format import canon, entry_hash, parse_line            # noqa: E402
from tests.biolean_ledger_fixture import (                                             # noqa: E402
    BY_A, KEY16_A, KEY16_B, KEY_A, KEY_B, LEDGER_ID, SCENARIOS, TS, build_signed, copy_ledger_store, copy_signed,
    fresh_ledger, ledger_base, new_fact, RELEASE)

SIGS = HERE / "sigs"


def private_copies(tmp: Path) -> dict[Path, Path]:
    """ssh-keygen refuses a 0644 private key; git checkouts are 0644. Sign from 0600 copies."""
    tmp.mkdir(parents=True, exist_ok=True)
    out = {}
    for key in (KEY_A, KEY_B):
        dst = tmp / key.name
        shutil.copy(key, dst)
        shutil.copy(key.with_name(key.name + ".pub"), tmp / (key.name + ".pub"))
        os.chmod(dst, stat.S_IRUSR | stat.S_IWUSR)
        out[key] = dst
    return out


def recording_runner(keymap: dict[Path, Path]):
    def runner(argv, *, input, capture_output, check):
        assert argv[:4] == ["ssh-keygen", "-Y", "sign", "-f"]
        real = list(argv)
        real[4] = str(keymap[Path(argv[4])])
        result = subprocess.run(real, input=input, capture_output=capture_output, check=check)
        SIGS.mkdir(exist_ok=True)
        (SIGS / (hashlib.sha256(input).hexdigest() + ".sig")).write_bytes(result.stdout)
        return result
    return runner


def raw_entry(fact, *, key16=KEY16_A, base=None, prev="", contested_by=(), ann_id=None):
    """An axiom entry built outside append. ``ann_id`` overrides check.annotation_id for a row
    that annotation_id() cannot hash (a lone surrogate); integrity refuses such a line before step 7."""
    row = list(fact)
    if row[14] == "":
        row[14] = "biolean:" + key16
    return {"v": 1, "kind": "axiom", "ledger": LEDGER_ID, "fact": row,
            "base": base or {**ledger_base().digests, "release": RELEASE},
            "check": {"kernel": "0.1.0", "annotation_id": ann_id or annotation_id(row), "contested_by": list(contested_by),
                      "counters": {"new_subject": 0}},
            "prev": prev, "by": BY_A, "ts": TS}


def raw_sign(entry: dict, key: Path, runner) -> bytes:
    """One canonical signed line for an entry built outside append (bypasses every check)."""
    e = dict(entry)
    e["sig"] = sign(canon(e), key, runner)
    return canon(e) + b"\n"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        keymap = private_copies(tmp / "keys")
        runner = recording_runner(keymap)
        if SIGS.exists():
            shutil.rmtree(SIGS)
        SIGS.mkdir()
        store = copy_ledger_store(tmp / "store")

        # 1. signed/: init + SIGNED_SEQUENCE
        signed = HERE / "signed"
        if signed.exists():
            shutil.rmtree(signed)
        build_signed(signed, store, runner=runner)
        for junk in signed.rglob("__pycache__"):
            shutil.rmtree(junk)

        # 2. sigs/ for every scenario (fresh and signed starts)
        for name, scn in sorted(SCENARIOS.items()):
            work = tmp / "scn" / name
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True)
            ledger = work / "ledger"
            if scn.start == "fresh":
                fresh_ledger(ledger, store)
            else:
                copy_signed(ledger)
            from methods_graph.biolean.ledger.append import append_entry
            res = append_entry(ledger, kind=scn.kind, body=scn.body, key=scn.key, ts=scn.ts, runner=runner,
                               store_dir=store, gaf="goa_human.gaf", use_cache=False)
            assert res.verdict == "ACCEPTED", (name, [e.to_dict() for e in res.errors])
            print(f"scenario {name}: {res.file}:{res.line} {res.hash[:16]}")

        # 3. signed-variants/: hand-signed lines
        variants = HERE / "signed-variants"
        if variants.exists():
            shutil.rmtree(variants)
        variants.mkdir()
        a_lines = (signed / f"ledger/{KEY16_A}.jsonl").read_bytes().split(b"\n")[:-1]
        entries = [parse_line(l + b"\n")[0] for l in a_lines]
        h1 = entry_hash(entries[0])
        # fork: A's three axioms plus a fourth whose prev is entry 1's hash
        fork_body = raw_entry(new_fact(db_object_id="P10005", db_object_symbol="G5", db_reference="PMID:777"), prev=h1)
        (variants / "fork.jsonl").write_bytes(b"".join(l + b"\n" for l in a_lines[:3]) + raw_sign(fork_body, KEY_A, runner))
        # column 15 names B's key16, signed by A, base matches
        (variants / "assigned-by-b.jsonl").write_bytes(raw_sign(raw_entry(new_fact(assigned_by="biolean:" + KEY16_B)), KEY_A, runner))
        # a base-independent fault (bad reference) with a made-up base
        made_up = {"obo": "0" * 64, "gaf": "1" * 64, "eco": "2" * 64, "release": RELEASE}
        (variants / "made-up-base.jsonl").write_bytes(raw_sign(raw_entry(new_fact(db_reference="PMID:0"), base=made_up), KEY_A, runner))
        # a lone surrogate in column 17
        (variants / "surrogate.jsonl").write_bytes(raw_sign(
            raw_entry(new_fact(gene_product_form_id="\ud800"), ann_id="gaf:0000000000000000"), KEY_A, runner))
        # check.annotation_id that does not match fact
        bad = raw_entry(new_fact(db_reference="PMID:778"))
        bad["check"]["annotation_id"] = "gaf:0000000000000000"
        (variants / "bad-annotation-id.jsonl").write_bytes(raw_sign(bad, KEY_A, runner))
        print(f"wrote {signed}, {variants}, {len(list(SIGS.iterdir()))} signatures under {SIGS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Implement `append.py`**

`src/methods_graph/biolean/ledger/append.py`:

```python
"""``init`` and ``append`` (spec §2, §4, §6, §7): the only code that writes a ledger.

``append_entry`` loads base plus ledger (integrity first), checks the body, builds the
envelope, signs through ``runner`` (``ssh-keygen -Y sign`` on stdin), verifies the signature
it got back with the in-repo verifier, and only then appends one canonical line. Signing is
the contributor's ``ssh-keygen``; there is no signing code here.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from methods_graph.biolean.ledger.check import (
    CheckContext, _not_yet, check_axiom, check_computed, check_derived, fact_from_body)
from methods_graph.biolean.ledger.errors import LedgerCode, LedgerError, LedgerIntegrityError
from methods_graph.biolean.ledger.format import (
    FORMAT_VERSION, MAX_DEPTH, canon, character_errors, entry_hash, nesting_depth, shape_errors)
from methods_graph.biolean.ledger.integrity import _path_is
from methods_graph.biolean.ledger.load import BASE_READ_ERRORS, load_with_ledger
from methods_graph.biolean.sshsig import (
    FIXTURE_KEY_DIGESTS, KEY_TYPE, NAMESPACE, AllowedSignersError, SshsigError, allowed_signers_line, dearmor,
    find_signer, fingerprint, key16 as _key16, key_digest, parse_allowed_signers, parse_public_key_line,
    verify_sshsig)
from methods_graph.biolean.store import base_digests, read_release

KINDS = ("axiom", "derived", "computed")
# Where a body-level LEDGER_BAD_BODY points, per kind (spec §7): a computed body is the entry's top level.
BODY_FIELD: dict[str, str | None] = {"axiom": "/fact", "derived": "/derivation", "computed": None}


@dataclass(frozen=True)
class SignerKey:
    path: Path              # what ssh-keygen gets: the private key, or a .pub whose key is in the agent
    pub_path: Path
    blob: bytes
    digest: str
    key16: str
    fingerprint: str
    comment: str

    @property
    def by(self) -> str:
        return "sha256:" + self.digest


def _fail(code: str, message: str, **kw: Any) -> LedgerIntegrityError:
    return LedgerIntegrityError([LedgerError(code, message, kw.pop("field", None), **kw)])


def read_signer(key: Path) -> SignerKey:
    """The public half of ``--key``: the file itself when it is a ``.pub``, else ``<key>.pub``
    beside it. Never runs ``ssh-keygen -y``. Refuses every type but ssh-ed25519 (spec §4). A path
    with no file name (``""`` from an unset shell variable, ``.``, ``/``) is LEDGER_UNSUPPORTED_KEY."""
    key = Path(key)
    try:
        pub = key if key.suffix == ".pub" else key.with_name(key.name + ".pub")
    except ValueError as exc:                      # with_name on an empty name
        raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY, f"--key {str(key)!r} names no key file: {exc}", got=str(key))
    try:
        text = pub.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY, f"cannot read the public key {pub}: {exc}", got=str(key))
    try:
        blob, comment = parse_public_key_line(text)
    except SshsigError as exc:
        raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY, f"{pub}: {exc}; only {KEY_TYPE} keys can sign", got=str(key))
    digest = key_digest(blob)
    return SignerKey(key, pub, blob, digest, _key16(blob), fingerprint(blob), comment)


def base_object(store_dir: Path, *, obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz",
                eco: str = "gaf-eco-mapping.txt") -> dict[str, Any]:
    """The §1 ``base`` object: three content digests plus the informational release. A present but
    unreadable base file is LEDGER_MALFORMED (refinement 18), as in `load_with_ledger`."""
    try:
        return {**base_digests(store_dir, obo=obo, gaf=gaf, eco=eco), "release": read_release(store_dir, obo=obo, gaf=gaf)}
    except BASE_READ_ERRORS as exc:
        raise _fail(LedgerCode.LEDGER_MALFORMED, f"cannot read the store under {store_dir}: {exc}",
                    context={"file": str(store_dir), "line": None}) from exc


def _utf8_encodable(s: str) -> bool:
    """False for a str holding a lone surrogate: what argparse gives for a non-UTF-8 argv byte."""
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _signers_entry(signer: SignerKey, principal: str | None) -> tuple[str, bytes]:
    """``(label, allowed_signers bytes)`` for ``init``, built and checked before anything is written.

    The label is ``principal or comment or key16``. An explicit principal that is not UTF-8 text,
    or that the allowed_signers reader would not hand back (``allowed_signers_line`` refuses it), is
    LEDGER_UNSUPPORTED_KEY; a comment that cannot serve as the label (``user@host name``, a double
    quote) gives way to key16, which always can. A comment the reader would refuse even after the
    key (a double quote, a NUL) or that is not UTF-8 text is left off the line: it labels nothing.
    The line must then read back through ``parse_allowed_signers`` as exactly this key and label.
    """
    comment = signer.comment
    try:
        allowed_signers_line(signer.key16, signer.blob, comment)       # key16 is always a valid principal
    except AllowedSignersError:
        comment = ""
    if not _utf8_encodable(comment):
        comment = ""
    if principal is not None:
        if not _utf8_encodable(principal):
            raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY,
                        f"principal {principal!r} is not UTF-8 text (a lone surrogate)", got=principal)
        try:
            label, line = principal, allowed_signers_line(principal, signer.blob, comment)
        except AllowedSignersError as exc:
            raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY,
                        f"principal {principal!r} cannot label an allowed_signers line: {exc.reason}", got=principal)
    else:
        label = comment or signer.key16
        try:
            line = allowed_signers_line(label, signer.blob, comment)
        except AllowedSignersError:
            label, line = signer.key16, allowed_signers_line(signer.key16, signer.blob, comment)
    why = ""
    try:
        back = parse_allowed_signers(line)
    except AllowedSignersError as exc:           # e.g. a small-order key, which parse_public_key_line admits
        back, why = [], f" ({exc})"
    if not (len(back) == 1 and back[0].blob == signer.blob and back[0].principals == (label,)
            and back[0].permits(NAMESPACE)):
        raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY,
                    f"the allowed_signers line for {label!r} does not read back as {signer.fingerprint}{why}", got=label)
    return label, line.encode("utf-8")


def _write_or_fail(path: Path, action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """One filesystem write. An OSError (the path is a file, a read-only parent) is LEDGER_MALFORMED
    naming ``path``: the ledger files cannot be written (spec §7), never a traceback."""
    try:
        return action(*args, **kwargs)
    except OSError as exc:
        raise _fail(LedgerCode.LEDGER_MALFORMED, f"cannot write {path}: {exc}",
                    context={"file": str(path), "line": None}) from exc


def init_ledger(
    ledger_dir: Path, *, store_dir: Path, key: Path, principal: str | None = None,
    obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz", eco: str = "gaf-eco-mapping.txt",
    ledger_id: str | None = None, allow_fixture_keys: bool = False,
) -> dict[str, Any]:
    """Write allowed_signers, base.json, ledger.json and ledger/ (spec §6, §7)."""
    signer = read_signer(key)
    if signer.digest in FIXTURE_KEY_DIGESTS and not allow_fixture_keys:
        raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY,
                    f"{signer.fingerprint} is a test fixture key and cannot start a ledger", got=str(key))
    ledger_dir = Path(ledger_dir)
    # Python 3.12's Path.exists raises PermissionError on EACCES (3.13+ returns False). A stat that
    # fails reads as absent here: mkdir and the writes below then report the unusable path.
    if _path_is((ledger_dir / "ledger.json").exists):
        raise _fail(LedgerCode.LEDGER_MALFORMED, f"{ledger_dir} already holds a ledger (ledger.json exists)")
    label, signers_bytes = _signers_entry(signer, principal)      # before mkdir: a refused principal writes nothing
    base = base_object(store_dir, obo=obo, gaf=gaf, eco=eco)      # before mkdir: a bad store writes nothing
    _write_or_fail(ledger_dir, ledger_dir.mkdir, parents=True, exist_ok=True)
    fname = f"ledger/{signer.key16}.jsonl"
    existing = ledger_dir / fname
    try:
        present = existing.exists()
    except OSError as exc:                         # cannot tell whether another key owns this file: fail closed
        raise _fail(LedgerCode.LEDGER_MALFORMED, f"cannot check {fname} for a key16 collision: {exc}",
                    context={"file": fname, "line": None}) from exc
    if present:
        try:
            first = json.loads(existing.read_bytes().split(b"\n", 1)[0])
        except (OSError, ValueError, RecursionError):
            first = None
        by = first.get("by") if isinstance(first, dict) else None
        if by != signer.by:
            raise _fail(LedgerCode.LEDGER_KEY16_COLLISION, f"{fname} exists and was signed by {by}, not {signer.by}",
                        got=by, context={"file": fname, "line": 1})
    lid = ledger_id or secrets.token_hex(16)
    for path, data in ((ledger_dir / "allowed_signers", signers_bytes),
                       (ledger_dir / "base.json", (json.dumps(base, sort_keys=True, indent=2) + "\n").encode("utf-8")),
                       (ledger_dir / "ledger.json", (json.dumps({"ledger": lid}) + "\n").encode("utf-8"))):
        _write_or_fail(path, path.write_bytes, data)
    _write_or_fail(ledger_dir / "ledger", (ledger_dir / "ledger").mkdir, exist_ok=True)
    signers_sha = hashlib.sha256(signers_bytes).hexdigest()
    return {"ledger": lid, "by": signer.by, "key16": signer.key16, "fingerprint": signer.fingerprint,
            "principal": label, "allowed_signers_sha256": signers_sha, "base": base, "file": fname}


def sign(canonical: bytes, key: Path, runner: Callable[..., Any]) -> str:
    """``sig`` for ``canonical``: ssh-keygen -Y sign, message on stdin, armor on stdout (spec §4)."""
    try:
        result = runner(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", NAMESPACE],
                        input=canonical, capture_output=True, check=True)
    except Exception as exc:                       # CalledProcessError, OSError (no ssh-keygen), anything the seam raises
        detail = getattr(exc, "stderr", b"")
        detail = detail.decode("utf-8", "replace").strip() if isinstance(detail, bytes) else str(detail)
        raise _fail(LedgerCode.LEDGER_SIGNING_FAILED,
                    f"ssh-keygen -Y sign failed: {exc}{(': ' + detail) if detail else ''}. "
                    "A passphrase-protected key must be loaded in ssh-agent, with --key naming its .pub file.",
                    got=str(key))
    try:
        return dearmor(result.stdout)
    except SshsigError as exc:
        raise _fail(LedgerCode.LEDGER_SIGNING_FAILED, f"ssh-keygen output is not an SSH signature: {exc}", got=str(key))


@dataclass
class AppendResult:
    verdict: str                       # ACCEPTED | REJECTED
    errors: list[LedgerError]
    deferred: list[dict[str, Any]]
    entry: dict[str, Any] | None
    hash: str | None
    file: str | None
    line: int | None

    def to_json(self) -> dict[str, Any]:
        if self.verdict == "ACCEPTED":
            return {"verdict": "ACCEPTED", "entry": self.entry, "hash": self.hash, "file": self.file, "line": self.line}
        return {"verdict": "REJECTED", "errors": [e.to_dict() for e in self.errors], "deferred": self.deferred}


def _rejected(errors: list[LedgerError], deferred: list[dict[str, Any]] | None = None) -> AppendResult:
    return AppendResult("REJECTED", errors, deferred or [], None, None, None, None)


def _not_a_json_value(body: Any, kind: str) -> LedgerError | None:
    """LEDGER_BAD_BODY (``got`` null) unless ``body``, at most MAX_DEPTH deep, is exactly a JSON value.
    ``canon`` refuses NaN and ±Infinity (what ``json.loads`` reads for ``NaN`` and ``1e999``) and an
    int past CPython's 4300-digit limit (ValueError), a set or keys of mixed types (TypeError); a
    non-string key or a tuple survives ``canon`` but not the round trip. Any of them would crash
    ``canon(entry)`` after the check, or reach a check that assumes JSON."""
    try:
        again = json.loads(canon(body))
    except (ValueError, TypeError) as exc:
        reason = str(exc)
    else:
        if again == body:
            return None
        reason = "it changes in a JSON round trip (a key that is not a string, a tuple)"
    return LedgerError(LedgerCode.LEDGER_BAD_BODY, f"the body is not a JSON value: {reason}", BODY_FIELD[kind], got=None)


def append_entry(
    ledger_dir: Path, *, kind: str, body: Any, key: Path, ts: str, runner: Callable[..., Any],
    store_dir: Path, obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz", eco: str = "gaf-eco-mapping.txt",
    cache_dir: Path | None = None, use_cache: bool = True, body_error: LedgerError | None = None,
) -> AppendResult:
    """Spec §2: integrity, signer, base, check, envelope, sign, self-verify, write.

    Raises LedgerIntegrityError for every exit-2 condition (unreadable ledger or store, integrity,
    unknown signer, key16 collision, base mismatch, signing failure). Returns REJECTED (exit 3)
    without writing, or ACCEPTED after appending exactly one line. ``body_error`` is the CLI's
    "the text is not JSON" `LEDGER_BAD_BODY`; it is reported here, after the exit-2 checks, so
    that a broken ledger or a wrong base still wins over a malformed body (spec §2 order).

    Before any check looks inside it, a body nested deeper than MAX_DEPTH, or one that is not
    exactly a JSON value (NaN, ±Infinity, a huge int, a key that is not a string), is that same
    LEDGER_BAD_BODY (``got`` null: the body is not echoed back), and a derived or computed body is
    held to §2 step 1a (`character_errors`, pointers into the body): the kernel takes any string
    as a step id, and a line verify's step 2 would refuse must never be signed. An axiom's
    columns get step 1a inside `check_axiom`, under the column rules. A ledger file that cannot be
    written is LEDGER_MALFORMED.
    """
    if kind not in KINDS:
        raise ValueError(kind)
    ledger_dir = Path(ledger_dir)
    signer = read_signer(key)
    store, _report, loaded = load_with_ledger(store_dir, ledger_dir, obo=obo, gaf=gaf, eco=eco,
                                              cache_dir=cache_dir, use_cache=use_cache)
    state = loaded.state
    listed = find_signer(state.signers, signer.blob)
    if listed is None or not listed.permits(NAMESPACE):
        raise _fail(LedgerCode.LEDGER_UNKNOWN_SIGNER,
                    f"key {signer.by} ({signer.fingerprint}) is not in allowed_signers with {NAMESPACE} permitted",
                    got=signer.by, context={"file": "allowed_signers", "line": None})
    fname = f"ledger/{signer.key16}.jsonl"
    existing = state.files.get(signer.key16, [])
    if existing and existing[0].entry["by"] != signer.by:
        raise _fail(LedgerCode.LEDGER_KEY16_COLLISION,
                    f"{fname} was signed by {existing[0].entry['by']}, not {signer.by}",
                    got=existing[0].entry["by"], context={"file": fname, "line": 1})
    try:
        declared = json.loads((ledger_dir / "base.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:      # RecursionError: a deeply nested base.json
        raise _fail(LedgerCode.LEDGER_MALFORMED, f"cannot read base.json: {exc}", context={"file": "base.json", "line": None})
    digests = loaded.base.digests
    if not (isinstance(declared, dict) and all(declared.get(k) == digests[k] for k in ("obo", "gaf", "eco"))):
        raise _fail(LedgerCode.LEDGER_BASE_MISMATCH,
                    "--store is not the base this ledger declares in base.json", field="/base", got=digests,
                    context={k: (declared.get(k) if isinstance(declared, dict) else None) for k in ("obo", "gaf", "eco")})
    base_obj = {**digests, "release": read_release(store_dir, obo=obo, gaf=gaf)}
    ctx = CheckContext(store=store, eco_map=loaded.base.eco_map, primary_id=loaded.base.primary_id,
                       term=loaded.base.term, key16=signer.key16, ledger_sources=loaded.sources)

    if body_error is None and nesting_depth(body) > MAX_DEPTH:
        body_error = LedgerError(LedgerCode.LEDGER_BAD_BODY, f"the body is nested deeper than {MAX_DEPTH} levels",
                                 BODY_FIELD[kind], got=None)
    if body_error is None:
        body_error = _not_a_json_value(body, kind)
    if body_error is not None:
        return _rejected([body_error, _not_yet()] if kind == "computed" else [body_error])
    if kind != "axiom":
        faults = character_errors(body)
        if faults:
            return _rejected(faults + [_not_yet()] if kind == "computed" else faults)

    fields: dict[str, Any]
    if kind == "axiom":
        fact, errs = fact_from_body(body)
        if errs:
            return _rejected(errs)
        res = check_axiom(fact, ctx)
        if not res.ok:
            return _rejected(res.errors, res.deferred)
        fields, check_block = {"fact": res.fact}, res.check
    elif kind == "derived":
        dres = check_derived(body, ctx)
        if not dres.ok:
            return _rejected(dres.errors)
        fields, check_block = {"derivation": dres.derivation, "conclusion": dres.conclusion}, dres.check
    else:
        return _rejected(check_computed(body, ctx))

    prev = existing[-1].hash if existing else ""
    entry: dict[str, Any] = {"v": FORMAT_VERSION, "kind": kind, "ledger": state.ledger_id, **fields,
                             "base": base_obj, "check": check_block, "prev": prev, "by": signer.by, "ts": ts}
    faults = shape_errors({**entry, "sig": ""}, ledger_id=state.ledger_id)
    if faults:                                     # a defect in this module, never the caller's body
        raise RuntimeError(f"append built a malformed entry: {[f.to_dict() for f in faults]}")
    canonical = canon(entry)
    sig = sign(canonical, signer.path, runner)
    try:
        blob = verify_sshsig(sig, canonical)
    except SshsigError as exc:
        raise _fail(LedgerCode.LEDGER_SIGNING_FAILED, f"the signature ssh-keygen returned does not verify: {exc}. "
                    "Check that --key names the intended key (or its .pub when the key is in ssh-agent).",
                    got=str(key))
    if blob != signer.blob:
        raise _fail(LedgerCode.LEDGER_SIGNING_FAILED,
                    f"ssh-keygen signed with {fingerprint(blob)}, not {signer.fingerprint}; nothing written. "
                    "Check that --key names the intended key (or its .pub when the key is in ssh-agent).",
                    got=str(key))
    entry["sig"] = sig
    line = canon(entry) + b"\n"
    try:
        with (ledger_dir / fname).open("ab") as fh:
            fh.write(line)
    except OSError as exc:
        raise _fail(LedgerCode.LEDGER_MALFORMED, f"cannot append to {fname}: {exc}",
                    context={"file": fname, "line": len(existing) + 1}) from exc
    return AppendResult("ACCEPTED", [], [], entry, entry_hash(entry), fname, len(existing) + 1)
```

`import hashlib` inside `init_ledger` is a smell: move it to the module's imports.

- [ ] **Step 6: Run the append tests against the planner's signatures**

Run: `$PYTEST tests/test_biolean_ledger_append.py -q -x`
Expected: all pass. `tests/fixtures/biolean/ledger/sigs/` (15 files) is already on disk from the planner's run (see Step 7), and a correct implementation signs byte-identical messages, so `fake_runner` finds every armor. This pass *is* the byte-compatibility check: if instead `fake_runner` raises `AssertionError: no fixture signature for these bytes (<sha256>.sig); ... run tests/fixtures/biolean/ledger/make_fixtures.py`, your envelope, `check` block or fixture base differs from the plan's code; diagnose that before regenerating anything, because the expectations in Tasks 8 and 9 were computed against these exact files. Only in a checkout without the planner's untracked output (a fresh clone) is that AssertionError the expected result of this step; to see the failure shape once, move `sigs/` aside, rerun, and restore it.

- [ ] **Step 7: Generate the fixtures**

Run: `.venv/bin/python tests/fixtures/biolean/ledger/make_fixtures.py`
Expected: prints one `scenario <name>: ledger/<key16>.jsonl:<line> <hash prefix>` line per scenario and `wrote .../signed, .../signed-variants, 15 signatures under .../sigs` (5 sequence entries, 7 scenarios and 5 variants sign 17 messages, of which two scenario messages coincide with sequence entries, so 15 distinct files).

Then: `ls tests/fixtures/biolean/ledger/signed/ledger` → `1438014318807ad1.jsonl` (4 lines) and `778b5c6aae736dad.jsonl` (1 line). `wc -l` them. Run it a second time and `git status --porcelain tests/fixtures` must show no change between runs (determinism).

The planner already ran this script against the plan's code in a scratch copy and left its output (untracked) under `tests/fixtures/biolean/ledger/{signed,signed-variants,sigs}/` together with the fixture base files. If your run changes any of those bytes, your implementation differs from the plan's code somewhere in the envelope, the `check` block or the fixture base: find out why before committing, because the test expectations in Tasks 8 and 9 were computed against these exact files.

- [ ] **Step 8: Run all ledger tests**

Run: `$PYTEST tests/test_biolean_ledger_append.py tests/test_biolean_ledger_integrity.py tests/test_biolean_ledger_load.py -q`
Expected: all pass.

Mutation checks: (a) `append_entry`: delete the `verify_sshsig` self-verify block: `test_append_self_verify_refuses_and_writes_nothing` fails (the known-message armor is written). (b) `fake_runner`: accept a file argument (`argv[7:]`) and have `sign` pass `str(path)` instead of `input=`: the fake's argv assertion fails. (c) `read_signer`: accept any key type: `test_unsupported_key_type_refused_before_signing` fails. (d) `_verify_file`: skip unlisted files instead of failing: `test_removed_key_fails_whole_ledger_until_its_file_is_deleted` fails. (e) `check_extends`: count-only: `test_divergent_chain_substituted_fails_extends` fails. (f) `_verify_file` step 3: drop the `(by is not None and obj["by"] != by)` clause: `test_all_entries_in_a_file_share_by` fails with `LEDGER_BAD_SIGNATURE` at line 5. (g) `_verify_file` step 7: drop `seen_ids` (e.g. `first = None`): `test_repeated_row_in_one_file_is_invalid_not_a_crash` fails with `DID NOT RAISE LedgerIntegrityError` (the repeated pair passes integrity); every other ledger test still passes. Ruling checks (execution, commit 6e54f45): drop the `nesting_depth(body) > MAX_DEPTH` guard in `append_entry`: `test_append_body_nested_deeper_than_max_depth_is_a_bad_body` fails; skip `character_errors(body)` for derived/computed bodies: `test_append_body_with_a_bad_character_is_rejected_before_the_runner` fails (the plan's code signed and wrote a derived body with a surrogate step id, and the next verify refused the whole ledger); label fallback and explicit-principal refusal: `test_init_falls_back_to_key16_when_the_key_comment_is_not_a_principal` and `test_init_refuses_an_explicit_principal_the_reader_would_not_hand_back`. Post-review checks (rulings S–V, commit 75c93a4): drop the `json.loads(canon(body))` guard: `test_append_body_that_is_not_a_json_value_is_a_bad_body` raises ValueError (NaN, inf, a 4301-digit int, an int-keyed dict); `if False:` for `blob != signer.blob`: `test_append_self_verify_refuses_a_signature_by_another_key` fails (verify_sshsig patched to return B's blob); drop the `_utf8_encodable` principal check or move `base_object` after `mkdir`: `test_init_builds_and_checks_everything_before_mkdir` fails; drop either OSError catch (mkdir on an existing file; the append write): `test_unwritable_ledger_paths_are_malformed_not_tracebacks` raises. Round-2 checks (ruling W, commit 42e0a2d): restore a bare `Path.exists()` at init, or make the key16-file stat fail open: `test_init_survives_a_stat_that_raises` raises or fails; drop the AllowedSignersError reason from the read-back message: `test_init_names_why_a_key_does_not_read_back` fails (a small-order .pub passes parse_public_key_line and is refused by parse_allowed_signers before mkdir).

- [ ] **Step 9: Commit (fixtures included)**

```bash
git add src/methods_graph/biolean/ledger/append.py tests/biolean_ledger_fixture.py tests/fixtures/biolean/ledger/make_fixtures.py tests/fixtures/biolean/ledger/signed tests/fixtures/biolean/ledger/signed-variants tests/fixtures/biolean/ledger/sigs tests/test_biolean_ledger_append.py tests/test_biolean_ledger_integrity.py tests/test_biolean_ledger_load.py
git commit -m "feat(biolean-ledger): init and append; signed fixtures made once with ssh-keygen

append loads base plus ledger, checks the body, signs through the runner seam
(ssh-keygen -Y sign on stdin), self-verifies with the in-repo verifier and
appends one canonical line. make_fixtures.py records every real signature
content-addressed under sigs/, so the suite spawns nothing.

mutation checked: dropping the self-verify writes the known-message armor;
a file argument to ssh-keygen fails the fake runner's argv assertion; dropping
seen_ids lets a repeated row pass integrity."
```

---

### Task 9: the CLI: `mg biolean ledger init|append|verify|show`, `--ledger` on `prove|check|goals`, `.gitignore`

**Files:**
- Modify: `src/methods_graph/cli.py:1168-1190` (`_BIOLEAN_FILES`, `_biolean_store`), `:1473-1528` (`cmd_biolean`), `:1938-1955` (parser)
- Modify: `.gitignore:19`
- Test: `tests/test_biolean_ledger_cli.py`

**Interfaces:**
- Consumes: `append.init_ledger`, `append.append_entry`, `integrity.verify_ledger`, `integrity.check_extends`, `integrity.integrity_report`, `load.load_with_ledger`, `load.recheck_derived`, `errors.LedgerIntegrityError`, `store.load_store(ledger_dir=…)`.
- Produces (in `cli.py`):
  - `_require_store(store_dir, parser) -> str` (the GAF file name; `parser.error` when a base file is missing).
  - `_biolean_store(store_dir, parser, *, ledger_dir=None, signers_sha256=None, cache_dir=None, use_cache=True)`.
  - `_ledger_now() -> str` (the clock; tests monkeypatch it), `_ledger_body(raw, parser, *, field) -> tuple[Any, LedgerError | None]` (inline JSON or `@path`; text that is not JSON comes back as a `LEDGER_BAD_BODY` error for `append_entry`), `_ledger_reference(derivation, store) -> None` (the `prove --ledger` post-processing), `_cmd_biolean_ledger(args, parser) -> int`.
  - Subcommands and flags exactly as spec §7 plus refinements 3, 5 and 6:
    - `ledger init --ledger DIR --store DIR --key PUB [--principal NAME]`
    - `ledger append --ledger DIR --store DIR --key KEY (--fact J | --derivation J | --computed J) [--no-cache] [--cache-dir DIR]`
    - `ledger verify --ledger DIR [--store DIR] [--recheck] [--no-cache] [--cache-dir DIR] [--extends PATH] [--signers-sha256 HEX]`
    - `ledger show --ledger DIR [--store DIR] [--by KEY16] [--kind axiom|derived|computed] [--contested] [--stale] [--recheck] [--signers-sha256 HEX] [--no-cache] [--cache-dir DIR]`
    - `check|prove|goals … [--ledger DIR] [--signers-sha256 HEX] [--no-cache] [--cache-dir DIR]`
    - `bench` gains nothing.
  - Exit codes: 0 accepted/ok; 3 rejected; 2 usage (argparse, stderr text), unreadable store/ledger, integrity, base mismatch, signers mismatch, rollback, signing failure (JSON on stdout).

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_ledger_cli.py`:

```python
"""`mg biolean ledger init|append|verify|show`, `--ledger` on prove|check|goals, exit codes, JSON contract."""
import hashlib
import json
import pathlib
from pathlib import Path

import pytest

from methods_graph import cli
from methods_graph.biolean.ledger.errors import LedgerCode as LC
from methods_graph.biolean.ledger.format import canon
from methods_graph.biolean.ledger.integrity import cache_key, verify_ledger
from methods_graph.biolean.props import Annotation, Term
from methods_graph.biolean.sshsig import fingerprint, parse_public_key_line
from methods_graph.biolean.store import StaticFactStore
from tests.biolean_ledger_fixture import (
    DIGEST_A, KEY16_A, KEY16_B, KEY_A, LEDGER_ID, PUB_A, PUB_B, SCENARIOS, TS, copy_ledger_store, copy_signed,
    fake_runner, fresh_ledger, new_fact, signed_store)

FP_A = fingerprint(parse_public_key_line(PUB_A.read_text())[0])
FP_B = fingerprint(parse_public_key_line(PUB_B.read_text())[0])

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _seams(monkeypatch):
    monkeypatch.setattr("subprocess.run", fake_runner)
    monkeypatch.setattr(cli, "_ledger_now", lambda: TS)
    from methods_graph.biolean import sshsig
    from methods_graph.biolean.ledger import append as append_mod
    monkeypatch.setattr(sshsig, "FIXTURE_KEY_DIGESTS", frozenset())        # init may use the fixture keys here
    monkeypatch.setattr(append_mod, "FIXTURE_KEY_DIGESTS", frozenset())


def _json(text):
    obj = json.loads(text)
    assert text == json.dumps(obj, sort_keys=True, indent=2) + "\n"
    return obj


def _lines(text):
    return [json.loads(line) for line in text.splitlines()]


def test_gitignore_ignores_a_ledger_clone_at_the_root():
    assert "/biolean-ledger/" in (ROOT / ".gitignore").read_text().splitlines()


def test_init_writes_files_and_prints_json(tmp_path, capsys):
    store = copy_ledger_store(tmp_path / "store")
    rc = cli.main(["biolean", "ledger", "init", "--ledger", str(tmp_path / "L"), "--store", str(store),
                   "--key", str(PUB_A), "--principal", "manu"])
    out = _json(capsys.readouterr().out)
    assert rc == 0 and out["key16"] == KEY16_A and out["by"] == "sha256:" + DIGEST_A and len(out["ledger"]) == 32
    assert (tmp_path / "L" / "ledger").is_dir() and (tmp_path / "L" / "base.json").exists()
    rc = cli.main(["biolean", "ledger", "init", "--ledger", str(tmp_path / "L"), "--store", str(store), "--key", str(PUB_A)])
    out = _json(capsys.readouterr().out)
    assert rc == 2 and out["errors"][0]["code"] == LC.LEDGER_MALFORMED


def test_append_accepts_and_rejects_with_exit_codes(tmp_path, capsys):
    store = copy_ledger_store(tmp_path / "store")
    ledger = fresh_ledger(tmp_path / "L", store)
    body = json.dumps(SCENARIOS["cli-fresh-axiom"].body)
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", body, "--no-cache"])
    out = _json(capsys.readouterr().out)
    assert rc == 0 and out["verdict"] == "ACCEPTED" and out["line"] == 1 and out["file"] == f"ledger/{KEY16_A}.jsonl"
    assert out["entry"]["ts"] == TS and len(out["hash"]) == 64
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", json.dumps(new_fact(go_id="GO:0009999")), "--no-cache"])
    out = _json(capsys.readouterr().out)
    assert rc == 3 and out["verdict"] == "REJECTED"
    assert [(e["code"], e["field"]) for e in out["errors"]] == [(LC.UNKNOWN_TERM, "/fact/4")]
    assert out["deferred"] == [{"step": 4, "waits_on": [5]}, {"step": 8, "waits_on": [5]}]
    assert set(out["errors"][0]) == {"code", "message", "field", "got", "fix", "options", "context"}
    # @file body, and the same fact again is LEDGER_DUPLICATE (terminal)
    p = tmp_path / "fact.json"
    p.write_text(body)
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", "@" + str(p), "--no-cache"])
    out = _json(capsys.readouterr().out)
    assert rc == 3 and out["errors"][0]["code"] == LC.LEDGER_DUPLICATE and out["errors"][0]["fix"] is None


def test_append_exit_2_conditions_print_json_errors_on_stdout(tmp_path, capsys):
    ledger, store = signed_store(tmp_path)
    (ledger / f"ledger/{KEY16_B}.jsonl").write_bytes(b"garbage\n")
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", json.dumps(new_fact()), "--no-cache"])
    captured = capsys.readouterr()
    out = _json(captured.out)
    assert rc == 2 and out["errors"][0]["code"] == LC.LEDGER_MALFORMED and "load_report" not in captured.err
    ledger, store = signed_store(tmp_path / "two")
    (store / "gaf-eco-mapping.txt").write_text("# changed\nIDA\tDefault\tECO:0000314\n")
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", json.dumps(new_fact()), "--no-cache"])
    assert rc == 2 and _json(capsys.readouterr().out)["errors"][0]["code"] == LC.LEDGER_BASE_MISMATCH
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", "not json", "--no-cache"])                # spec section 2 order: the base mismatch still wins
    assert rc == 2 and _json(capsys.readouterr().out)["errors"][0]["code"] == LC.LEDGER_BASE_MISMATCH
    with pytest.raises(SystemExit):
        cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A)])


def test_append_body_that_is_not_json_is_rejected_not_a_usage_error(tmp_path, capsys):
    # Break: `_ledger_body` calling `parser.error` on a JSONDecodeError (SystemExit 2, text on stderr).
    ledger, store = signed_store(tmp_path)
    for flag, field in (("--fact", "/fact"), ("--derivation", "/derivation"), ("--computed", None)):
        rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                       flag, "not json", "--no-cache"])
        out = _json(capsys.readouterr().out)
        assert rc == 3 and out["verdict"] == "REJECTED" and out["deferred"] == [], flag
        assert (out["errors"][0]["code"], out["errors"][0]["field"], out["errors"][0]["got"]) == (LC.LEDGER_BAD_BODY, field, "not json")
        assert [e["code"] for e in out["errors"][1:]] == ([LC.NOT_YET_DISCHARGEABLE] if flag == "--computed" else [])
    assert len(verify_ledger(ledger).entries()) == 5                                  # nothing was written


def test_append_body_too_deep_or_with_a_nan_literal_is_a_bad_body(tmp_path, capsys):
    # Break: drop the RecursionError catch in `_ledger_body` (the deep body raises out of main);
    # drop `parse_constant` (NaN and Infinity reach append_entry, which reports got null, not the text).
    # 1,000,000 deep, not 100,000: Python 3.14 bounds the JSON scanner by the C stack, not the
    # recursion limit, and reads 100,000 unclosed brackets to a plain JSONDecodeError.
    ledger, store = signed_store(tmp_path)
    for text in ("[" * 1_000_000, "NaN", '["x", Infinity]'):
        rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                       "--fact", text, "--no-cache"])
        out = _json(capsys.readouterr().out)
        assert rc == 3 and [(e["code"], e["field"], e["got"]) for e in out["errors"]] == [
            (LC.LEDGER_BAD_BODY, "/fact", text)], text[:20]
    assert len(verify_ledger(ledger).entries()) == 5


def test_append_body_file_that_cannot_be_read_is_a_usage_error(tmp_path, capsys):
    # Break: catch only OSError around the @path read (a non-UTF-8 file raises UnicodeDecodeError).
    ledger, store = signed_store(tmp_path)
    (tmp_path / "latin1.json").write_bytes(b'["\xe9"]')
    for bad in (tmp_path / "missing.json", tmp_path / "latin1.json"):
        with pytest.raises(SystemExit) as exc:
            cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                      "--fact", "@" + str(bad), "--no-cache"])
        assert exc.value.code == 2 and str(bad) in capsys.readouterr().err


def test_printed_json_is_ascii_even_when_an_error_carries_a_lone_surrogate(tmp_path, capsys):
    # Break: `ensure_ascii=False` in the ledger subcommand's JSON printer (the lone surrogate in
    # `field` cannot be written as UTF-8, so the print raises).
    ledger, store = signed_store(tmp_path)
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--derivation", json.dumps({"\ud800": "\ud800"}), "--no-cache"])
    text = capsys.readouterr().out
    assert text.isascii()
    out = _json(text)
    assert rc == 3 and [(e["code"], e["field"]) for e in out["errors"]] == [
        (LC.LEDGER_BAD_CHARACTER, ""), (LC.LEDGER_BAD_CHARACTER, "/\ud800")]      # the key, then the value under it


def test_key_that_names_no_file_is_unsupported_key_json_not_a_traceback(tmp_path, capsys):
    # Break: a bare `key.with_name(key.name + ".pub")` in read_signer (Path("") has an empty name:
    # ValueError escapes main). An unset shell variable gives --key "".
    ledger, store = signed_store(tmp_path)
    before = verify_ledger(ledger).heads()
    for key in ("", ".", "/"):
        for argv in (["biolean", "ledger", "init", "--ledger", str(tmp_path / "new"), "--store", str(store), "--key", key],
                     ["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", key,
                      "--fact", json.dumps(new_fact()), "--no-cache"]):
            rc = cli.main(argv)
            out = _json(capsys.readouterr().out)
            assert rc == 2 and [e["code"] for e in out["errors"]] == [LC.LEDGER_UNSUPPORTED_KEY], (key, argv[2])
    assert not (tmp_path / "new").exists() and verify_ledger(ledger).heads() == before


def test_show_by_takes_only_a_key16(tmp_path, capsys):
    # Break: drop the --by check (exit 0 and no rows: a by value or a fingerprint silently matches nothing).
    ledger, _ = signed_store(tmp_path)
    for bad in ("sha256:" + DIGEST_A, FP_A, KEY16_A.upper(), KEY16_A[:15], KEY16_A + "\n"):
        with pytest.raises(SystemExit) as exc:
            cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--by", bad])
        assert exc.value.code == 2 and "--by" in capsys.readouterr().err, bad


def test_show_reports_cache_marks_it_could_not_write_on_stderr(tmp_path, capsys):
    # Break: drop the stderr line (the count of failed marks is then never surfaced by show).
    ledger, store = signed_store(tmp_path)
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store), "--no-cache"]) == 0
    rows = capsys.readouterr().out
    good = tmp_path / "cache"
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store),
                     "--cache-dir", str(good)]) == 0
    captured = capsys.readouterr()
    assert captured.out == rows and captured.err == ""                     # marks written: nothing to say
    not_a_dir = tmp_path / "cache-file"
    not_a_dir.write_bytes(b"")
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store),
                     "--cache-dir", str(not_a_dir)]) == 0
    captured = capsys.readouterr()
    assert captured.out == rows and captured.err == "cache: 2 mark(s) could not be written\n"


def test_a_store_stat_that_raises_is_a_usage_error(tmp_path, capsys, monkeypatch):
    # Python 3.12 raises PermissionError from Path.exists on EACCES (3.13+ returns False). Break: a
    # bare exists() in `_require_store` or in `_biolean_gaf_name` (the PermissionError escapes main).
    ledger, store = signed_store(tmp_path)

    def denied(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(pathlib.Path, "exists", denied)
    for argv in (["biolean", "ledger", "verify", "--ledger", str(ledger), "--store", str(store)],
                 ["biolean", "prove", "UniProtKB:P10002 involved_in GO:0000003", "--store", str(store)]):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == 2 and "lacks" in capsys.readouterr().err, argv[1]


def test_verify_without_store_is_integrity_only_and_with_store_reports(tmp_path, capsys):
    ledger, store = signed_store(tmp_path)
    rc = cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger)])
    out = _json(capsys.readouterr().out)
    assert rc == 0 and out["ok"] is True
    assert out["ledger"]["entries"] == 5 and out["ledger"]["admitted"] is None and out["ledger"]["derived_rechecked"] is None
    rc = cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--store", str(store), "--recheck", "--no-cache"])
    out = _json(capsys.readouterr().out)
    assert rc == 0 and out["ledger"]["admitted"] == 4 and out["ledger"]["derived_rechecked"] == 1 and out["ledger"]["derived_failed"] == 0
    with pytest.raises(SystemExit) as exc:
        cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--recheck"])
    assert exc.value.code == 2
    actual = out["ledger"]["allowed_signers_sha256"]
    assert cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--signers-sha256", actual]) == 0
    capsys.readouterr()
    rc = cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--signers-sha256", "0" * 64])
    assert rc == 2 and _json(capsys.readouterr().out)["errors"][0]["code"] == LC.LEDGER_SIGNERS_MISMATCH
    full = copy_signed(tmp_path / "full")
    (ledger / f"ledger/{KEY16_B}.jsonl").unlink()
    rc = cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--extends", str(full)])
    out = _json(capsys.readouterr().out)
    assert rc == 2 and out["errors"][0]["code"] == LC.LEDGER_ROLLBACK
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps({KEY16_A: verify_ledger(ledger).heads()[KEY16_A]}))        # B's file is gone but B is listed...
    rc = cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--extends", str(heads)])
    assert rc == 0 and _json(capsys.readouterr().out)["ok"] is True                        # ...and a heads map that omits B says nothing about it


def test_extends_with_a_bad_path_is_a_usage_error(tmp_path, capsys):
    ledger, _ = signed_store(tmp_path)
    (tmp_path / "junk.json").write_text("[1]")
    for bad in (tmp_path / "junk.json", tmp_path / "missing"):
        with pytest.raises(SystemExit) as exc:
            cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--extends", str(bad)])
        assert exc.value.code == 2
        assert "extends" in capsys.readouterr().err


def test_unreadable_store_is_exit_2_json_not_a_traceback(tmp_path, capsys):
    # Break: drop the BASE_READ_ERRORS wrap in load_with_ledger (EOFError escapes as a traceback);
    # drop `zlib.error` from the tuple (the corrupt-deflate case escapes); call base_object after
    # mkdir in init_ledger (the failed init leaves a directory behind).
    import gzip
    ledger, store = signed_store(tmp_path)
    (store / "goa_human.gaf").unlink()
    good = gzip.compress(b"x" * 2000, mtime=0)
    for name, damage in (("truncated", b"\x1f\x8b\x08garbage"), ("corrupt deflate", good[:10] + b"\xff" * 20 + good[30:])):
        (store / "goa_human.gaf.gz").write_bytes(damage)
        for argv in (["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                      "--fact", json.dumps(new_fact()), "--no-cache"],
                     ["biolean", "ledger", "verify", "--ledger", str(ledger), "--store", str(store), "--no-cache"],
                     ["biolean", "ledger", "init", "--ledger", str(tmp_path / "new"), "--store", str(store), "--key", str(PUB_A)],
                     ["biolean", "prove", "UniProtKB:P10002 involved_in GO:0000003", "--store", str(store),
                      "--ledger", str(ledger), "--no-cache"]):
            rc = cli.main(argv)
            [err] = _json(capsys.readouterr().out)["errors"]
            assert rc == 2 and err["code"] == LC.LEDGER_MALFORMED and err["context"]["file"] == str(store), (name, argv[2])
    assert not (tmp_path / "new").exists()                                        # init wrote nothing


def test_verify_never_reads_the_cache_even_when_show_does(tmp_path, capsys):
    # Break: `use_cache=not args.no_cache` (or dropping the `cmd == "show"` guard) on either verify path.
    ledger, store = signed_store(tmp_path)
    path = ledger / f"ledger/{KEY16_A}.jsonl"
    lines = path.read_bytes().split(b"\n")[:-1]
    obj = json.loads(lines[0])
    sig = obj["sig"]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    obj["sig"] = sig[:200] + alphabet[(alphabet.index(sig[200]) + 1) % 64] + sig[201:]   # inside the signature bytes
    forged = b"".join(l + b"\n" for l in [canon(obj)] + lines[1:])                     # the hash excludes sig: chain intact
    path.write_bytes(forged)
    signers = hashlib.sha256((ledger / "allowed_signers").read_bytes()).hexdigest()
    cache = tmp_path / "cache"
    for c in (cache, tmp_path / ".cache" / "biolean-ledger"):    # --cache-dir, and the default under HOME (conftest)
        c.mkdir(parents=True, exist_ok=True)
        (c / cache_key(LEDGER_ID, path.name, forged, signers)).write_bytes(b"")      # a planted "verified" mark
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store),
                     "--cache-dir", str(cache)]) == 0                                  # show honours the mark
    capsys.readouterr()
    for extra in ([], ["--store", str(store)]):
        rc = cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--cache-dir", str(cache), *extra])
        assert rc == 2 and _json(capsys.readouterr().out)["errors"][0]["code"] == LC.LEDGER_BAD_SIGNATURE, extra


def test_show_filters_and_store_requirement(tmp_path, capsys):
    ledger, store = signed_store(tmp_path)
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger)]) == 0
    rows = _lines(capsys.readouterr().out)
    assert len(rows) == 5 and {r["status"] for r in rows} == {None} and all(r["rechecked"] is False for r in rows)
    assert set(rows[0]) == {"file", "line", "hash", "entry", "fingerprint", "status", "contested", "rechecked",
                            "recheck_errors"}
    assert [r["line"] for r in rows] == [1, 2, 3, 4, 1]
    assert [r["fingerprint"] for r in rows] == [FP_A] * 4 + [FP_B]        # spec section 1: the SHA256:<base64> form
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--by", KEY16_B]) == 0
    assert len(_lines(capsys.readouterr().out)) == 1
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--kind", "derived"]) == 0
    [row] = _lines(capsys.readouterr().out)
    assert row["entry"]["kind"] == "derived" and row["status"] is None
    for flag in ("--contested", "--stale", "--recheck"):
        with pytest.raises(SystemExit) as exc:
            cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), flag])
        assert exc.value.code == 2
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store), "--contested", "--no-cache"]) == 0
    [row] = _lines(capsys.readouterr().out)
    assert row["entry"]["fact"][1] == "P10001" and row["contested"] is True and row["status"] == "admitted"
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store), "--recheck", "--kind", "derived", "--no-cache"]) == 0
    [row] = _lines(capsys.readouterr().out)
    assert row["rechecked"] is True and row["recheck_errors"] == [] and row["status"] == "recorded"
    obo = store / "go-basic.obo"
    obo.write_text(obo.read_text().replace("name: process grandchild\nnamespace: biological_process\n",
                                           "name: process grandchild\nnamespace: biological_process\nis_obsolete: true\n"))
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store), "--stale", "--no-cache"]) == 0
    rows = _lines(capsys.readouterr().out)
    assert rows and all(r["status"] == "stale" for r in rows)


def test_prove_check_goals_accept_ledger_and_prove_carries_the_doi(tmp_path, capsys):
    ledger, store = signed_store(tmp_path)
    claim = "UniProtKB:P10006 involved_in GO:0000001"
    rc = cli.main(["biolean", "prove", claim, "--store", str(store)])
    assert rc == 3
    captured = capsys.readouterr()
    rc = cli.main(["biolean", "prove", claim, "--store", str(store), "--ledger", str(ledger), "--no-cache"])
    captured = capsys.readouterr()
    out = _json(captured.out)
    assert rc == 0 and out["derivation"]["steps"][0]["reference"].startswith("DOI:")
    assert json.loads(captured.err)["load_report"]["ledger"]["admitted"] == 4
    d = tmp_path / "d.json"
    d.write_text(json.dumps(out["derivation"]))
    rc = cli.main(["biolean", "check", str(d), "--store", str(store), "--ledger", str(ledger), "--no-cache"])
    v = _json(capsys.readouterr().out)
    assert rc == 0 and v["verdict"] == "ACCEPTED" and v["axioms"][0]["references"][0].startswith("DOI:")
    rc = cli.main(["biolean", "check", str(d), "--store", str(store)])
    assert rc == 3
    capsys.readouterr()
    rc = cli.main(["biolean", "goals", "UniProtKB:P10006", "--store", str(store), "--ledger", str(ledger), "--no-cache"])
    out = _json(capsys.readouterr().out)
    assert rc == 0 and [g["prop"]["term"] for g in out["goals"]] == ["GO:0000001", "GO:0000002", "GO:0000003"]
    # the signers pin reaches the load (break: drop expected_signers_sha256= at the load_store call)
    pin = hashlib.sha256((ledger / "allowed_signers").read_bytes()).hexdigest()
    rc = cli.main(["biolean", "prove", claim, "--store", str(store), "--ledger", str(ledger), "--no-cache",
                   "--signers-sha256", pin])
    assert rc == 0
    capsys.readouterr()
    rc = cli.main(["biolean", "prove", claim, "--store", str(store), "--ledger", str(ledger), "--no-cache",
                   "--signers-sha256", "0" * 64])
    captured = capsys.readouterr()
    assert rc == 2 and _json(captured.out)["errors"][0]["code"] == LC.LEDGER_SIGNERS_MISMATCH and captured.err == ""
    (ledger / f"ledger/{KEY16_B}.jsonl").write_bytes(b"garbage\n")
    rc = cli.main(["biolean", "prove", claim, "--store", str(store), "--ledger", str(ledger), "--no-cache"])
    captured = capsys.readouterr()
    assert rc == 2 and _json(captured.out)["errors"][0]["code"] == LC.LEDGER_MALFORMED and captured.err == ""


def _ann(i, assigned_by, refs):
    return Annotation(i, "UniProtKB:X", "X", "involved_in", False, "GO:1", "GO:1", tuple(sorted(refs)), "IDA",
                      "ECO:0000314", (), "P", "protein", "NCBITaxon:9606", "", "2020-01-01", assigned_by, "", "")


def test_prove_reference_is_set_only_when_every_matching_row_is_ledger_sourced():
    # Break: pick the reference from any ledger row even when a base row also matches (the kernel's
    # reference filter would then drop the base rows from `axioms`).
    terms = [Term("GO:1", "t", "biological_process", False, (), (), ())]
    step = {"id": "s1", "rule": "axiom", "conclusion": {"subject": "UniProtKB:X", "qualifier": "involved_in", "term": "GO:1",
                                                        "taxon": "NCBITaxon:9606", "negated": False}}
    mixed = StaticFactStore(terms, [], [_ann("gaf:a", "UniProt", ["PMID:1"]), _ann("gaf:b", "biolean:x", ["DOI:10.1/z"])])
    d = {"goal": step["conclusion"], "steps": [dict(step)], "root": "s1"}
    cli._ledger_reference(d, mixed)
    assert "reference" not in d["steps"][0]
    only_ledger = StaticFactStore(terms, [], [_ann("gaf:b", "biolean:x", ["PMID:9", "DOI:10.1/z", "DOI:10.1/a"]),
                                              _ann("gaf:c", "biolean:y", ["GO_REF:0000001"])])
    d = {"goal": step["conclusion"], "steps": [dict(step)], "root": "s1"}
    cli._ledger_reference(d, only_ledger)
    assert d["steps"][0]["reference"] == "DOI:10.1/a"                # smallest DOI of the row with the smallest id
    pmid_only = StaticFactStore(terms, [], [_ann("gaf:b", "biolean:x", ["PMID:9", "GO_REF:0000001"])])
    d = {"goal": step["conclusion"], "steps": [dict(step)], "root": "s1"}
    cli._ledger_reference(d, pmid_only)
    assert d["steps"][0]["reference"] == "PMID:9"


def test_bench_has_no_ledger_flag(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(["biolean", "bench", "coverage", "--items", str(tmp_path), "--ledger", str(tmp_path)])
    assert exc.value.code == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_ledger_cli.py -q`
Expected: FAIL at the autouse fixture: `AttributeError: module 'methods_graph.cli' has no attribute '_ledger_now'` and, for the gitignore test, an assertion.

- [ ] **Step 3: Implement**

`.gitignore`: after the `/biolean-bench/` line add:

```
# A clone of the ledger repo at the root (spec 2026-09-25 §6); data, not code.
/biolean-ledger/
```

In `src/methods_graph/cli.py`, replace `_biolean_store` (lines 1179–1188) with:

```python
def _require_store(store_dir: Path, parser: argparse.ArgumentParser) -> str:
    """The GAF file name under --store, or exit 2 naming what is missing."""
    gaf = _biolean_gaf_name(store_dir)
    missing = [name for name in (*_BIOLEAN_FILES, gaf) if not (store_dir / name).exists()]
    if missing:
        parser.error(f"biolean: --store {store_dir} lacks {', '.join(missing)}; "
                     f"run `mg biolean fetch --out {store_dir}`")
    return gaf


def _biolean_store(
    store_dir: Path, parser: argparse.ArgumentParser, *, ledger_dir: Path | None = None,
    signers_sha256: str | None = None, cache_dir: Path | None = None, use_cache: bool = True,
):
    """Load the Biolean store (base, or base plus a ledger). Raises LedgerIntegrityError; the
    caller prints it as JSON and returns 2, never through parser.error (spec §3)."""
    from methods_graph.biolean.store import load_store

    gaf = _require_store(store_dir, parser)
    if ledger_dir is None:
        return load_store(store_dir, gaf=gaf)
    return load_store(store_dir, gaf=gaf, ledger_dir=ledger_dir, expected_signers_sha256=signers_sha256,
                      cache_dir=cache_dir, use_cache=use_cache)


def _ledger_now() -> str:
    """The clock, as one function so tests can inject a fixed ts (spec §1)."""
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ledger_body(raw: str, parser: argparse.ArgumentParser, *, field: str | None):
    """A body flag's value: inline JSON text, or @<path> to read a file (plan refinement 3).

    Returns ``(body, None)``, or ``(None, error)`` when the text is not JSON: that is the body's
    fault (spec §2 ``LEDGER_BAD_BODY``, exit 3), which `append_entry` reports after the integrity,
    signer and base checks so an exit-2 condition still wins. An unreadable ``@path`` is a usage error.
    """
    from methods_graph.biolean.ledger.errors import LedgerCode, LedgerError

    text = raw
    if raw.startswith("@"):
        try:
            text = Path(raw[1:]).read_text(encoding="utf-8")
        except OSError as exc:
            parser.error(f"biolean ledger: cannot read {raw[1:]}: {exc}")
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, LedgerError(LedgerCode.LEDGER_BAD_BODY, f"the body is not JSON: {exc}", field, got=text)


def _ledger_reference(derivation: dict, store) -> None:
    """`prove --ledger` (spec §7): when every row matching s1's conclusion is ledger-sourced, set
    s1's reference to the smallest DOI:, else PMID:, else GO_REF: of the row with the smallest
    annotation id. When any base row also matches, leave it unset: the kernel's reference filter
    would otherwise drop the base rows from `axioms`."""
    from methods_graph.biolean.props import Prop

    steps = derivation.get("steps") or []
    if not steps or steps[0].get("rule") != "axiom":
        return
    prop = Prop.from_dict(steps[0].get("conclusion"))
    if prop is None:
        return
    rows = store.matching(prop)
    if not rows or not all(r.assigned_by.startswith("biolean:") for r in rows):
        return
    first = min(rows, key=lambda r: r.id)
    for prefix in ("DOI:", "PMID:", "GO_REF:"):
        refs = [r for r in first.references if r.startswith(prefix)]
        if refs:
            steps[0]["reference"] = refs[0]            # references are stored sorted
            return


def _cmd_biolean_ledger(args, parser: argparse.ArgumentParser) -> int:
    """`mg biolean ledger init|append|verify|show`. 0 ok/ACCEPTED, 3 REJECTED, 2 usage or
    integrity (JSON on stdout for everything but argparse usage errors)."""
    import subprocess

    from methods_graph.biolean.ledger.append import append_entry, init_ledger
    from methods_graph.biolean.ledger.errors import LedgerIntegrityError
    from methods_graph.biolean.ledger.integrity import check_extends, integrity_report, verify_ledger
    from methods_graph.biolean.ledger.load import load_with_ledger, recheck_derived
    from methods_graph.biolean.sshsig import fingerprint

    def emit(obj) -> None:
        print(json.dumps(obj, sort_keys=True, indent=2))

    cmd = args.ledger_cmd
    needs_store = cmd in ("init", "append") or (cmd in ("verify", "show") and args.store is not None)
    if cmd == "verify" and args.recheck and args.store is None:
        parser.error("biolean ledger verify: --recheck needs --store")
    if cmd == "show" and args.store is None and (args.contested or args.stale or args.recheck):
        parser.error("biolean ledger show: --contested, --stale and --recheck need --store")
    gaf = _require_store(args.store, parser) if needs_store else None
    try:
        if cmd == "init":
            emit(init_ledger(args.ledger, store_dir=args.store, key=args.key, principal=args.principal, gaf=gaf))
            return 0
        if cmd == "append":
            kind, raw = next((k, v) for k, v in (("axiom", args.fact), ("derived", args.derivation),
                                                 ("computed", args.computed)) if v is not None)
            body, body_error = _ledger_body(raw, parser, field={"axiom": "/fact", "derived": "/derivation",
                                                                "computed": None}[kind])
            res = append_entry(args.ledger, kind=kind, body=body, key=args.key, ts=_ledger_now(),
                               runner=subprocess.run, store_dir=args.store, gaf=gaf,
                               cache_dir=args.cache_dir, use_cache=not args.no_cache, body_error=body_error)
            emit(res.to_json())
            return 0 if res.verdict == "ACCEPTED" else 3
        # verify and show
        if args.store is None:
            state = verify_ledger(args.ledger, expected_signers_sha256=args.signers_sha256,
                                  cache_dir=args.cache_dir, use_cache=False)   # never reads it (spec §3)
            block, loaded, store = integrity_report(state), None, None
        else:
            store, _report, loaded = load_with_ledger(
                args.store, args.ledger, gaf=gaf, expected_signers_sha256=args.signers_sha256,
                cache_dir=args.cache_dir, use_cache=(cmd == "show" and not args.no_cache))
            state, block = loaded.state, dict(loaded.report)
            if args.recheck:
                block.update(recheck_derived(loaded, store))
        if cmd == "verify":
            if args.extends is not None:
                try:
                    rollback = check_extends(state, args.extends)
                except ValueError as exc:
                    parser.error(f"biolean ledger verify: --extends {exc}")
                if rollback:
                    emit({"errors": [e.to_dict() for e in rollback]})
                    return 2
            emit({"ok": True, "ledger": block})
            return 0
        # show
        status = {(b.entry.file, b.entry.line): b for b in loaded.bound} if loaded is not None else {}
        contested = set(block.get("contested_entries") or [])
        failed = {(f["file"], f["line"]): f["errors"] for f in (block.get("derived_failed_entries") or [])}
        fp_by_key16 = {s.key16: fingerprint(s.blob) for s in state.signers}   # integrity step 3 ties file to key
        for e in state.entries():
            if args.by is not None and e.key16 != args.by:
                continue
            if args.kind is not None and e.entry["kind"] != args.kind:
                continue
            b = status.get((e.file, e.line))
            st = b.status if b is not None else None
            is_axiom = e.entry["kind"] == "axiom"
            contested_flag = None if (b is None or not is_axiom) else (
                st == "admitted" and b.annotation is not None and b.annotation.id in contested)
            if args.contested and not contested_flag:
                continue
            if args.stale and st != "stale":
                continue
            rechecked = bool(args.recheck) and e.entry["kind"] == "derived"
            print(json.dumps({"file": e.file, "line": e.line, "hash": e.hash, "entry": e.entry,
                              "fingerprint": fp_by_key16[e.key16], "status": st,
                              "contested": contested_flag, "rechecked": rechecked,
                              "recheck_errors": (failed.get((e.file, e.line), []) if rechecked else None)},
                             sort_keys=True))
        return 0
    except LedgerIntegrityError as exc:
        emit(exc.to_json())
        return 2
```

In `cmd_biolean` (line 1485 onward), dispatch `ledger` before the store load and wrap the load:

```python
    if args.biolean_cmd == "bench":
        return _cmd_biolean_bench(args, parser)
    if args.biolean_cmd == "ledger":
        return _cmd_biolean_ledger(args, parser)

    from methods_graph.biolean.elaborate import elaborate, elaborate_and_check
    from methods_graph.biolean.ledger.errors import LedgerIntegrityError
    from methods_graph.biolean.props import Prop
    from methods_graph.biolean.render import render_verdict
    from methods_graph.biolean.tactics import goals_for, prove

    try:
        store, report = _biolean_store(args.store, parser, ledger_dir=args.ledger, signers_sha256=args.signers_sha256,
                                       cache_dir=args.cache_dir, use_cache=not args.no_cache)
    except LedgerIntegrityError as exc:
        print(json.dumps(exc.to_json(), sort_keys=True, indent=2))
        return 2
    print(json.dumps({"load_report": report}, sort_keys=True), file=sys.stderr)
```

and in the `prove` branch, after `derivation = prove(target, store) if target is not None else None` and the `None` handling, before printing:

```python
        if args.ledger is not None:
            _ledger_reference(derivation, store)
```

In the parser (after `bl_goals.add_argument("--aspect", ...)`, line 1954):

```python
    for p in (bl_check, bl_prove, bl_goals):
        p.add_argument("--ledger", type=Path, default=None,
                       help="a ledger directory; the store is then base plus admitted ledger facts")
        p.add_argument("--signers-sha256", default=None, help="pin: the sha256 of the ledger's allowed_signers")
        p.add_argument("--no-cache", action="store_true", help="never read or write the verification cache")
        p.add_argument("--cache-dir", type=Path, default=None, help="verification cache (default ~/.cache/biolean-ledger)")

    bl_ledger = bl_sub.add_parser("ledger", help="signed, hash-chained, kernel-checked fact ledger")
    bl_ledger_sub = bl_ledger.add_subparsers(dest="ledger_cmd", required=True)
    l_init = bl_ledger_sub.add_parser("init", help="create a ledger: allowed_signers, base.json, ledger.json, ledger/")
    l_init.add_argument("--ledger", type=Path, required=True)
    l_init.add_argument("--store", type=Path, default=Path("snapshots/go"))
    l_init.add_argument("--key", type=Path, required=True, help="the owner's ssh-ed25519 public key (.pub)")
    l_init.add_argument("--principal", default=None, help="label for the allowed_signers line (default: the key comment)")
    l_append = bl_ledger_sub.add_parser("append", help="check, sign and append one entry")
    l_append.add_argument("--ledger", type=Path, required=True)
    l_append.add_argument("--store", type=Path, default=Path("snapshots/go"))
    l_append.add_argument("--key", type=Path, required=True,
                          help="an unencrypted ssh-ed25519 private key, or its .pub when the key is in ssh-agent")
    body = l_append.add_mutually_exclusive_group(required=True)
    body.add_argument("--fact", metavar="JSON|@FILE", help="a 17-column GAF row (list, or object keyed by column name)")
    body.add_argument("--derivation", metavar="JSON|@FILE", help='{"derivation": ..., "conclusion"?: ...}')
    body.add_argument("--computed", metavar="JSON|@FILE", help="a Phase B computed body (schema-checked, then refused)")
    l_append.add_argument("--no-cache", action="store_true")
    l_append.add_argument("--cache-dir", type=Path, default=None)
    l_verify = bl_ledger_sub.add_parser("verify", help="integrity; with --store also staleness and supersession")
    l_verify.add_argument("--ledger", type=Path, required=True)
    l_verify.add_argument("--store", type=Path, default=None)
    l_verify.add_argument("--recheck", action="store_true", help="re-prove every derived entry (needs --store)")
    l_verify.add_argument("--no-cache", action="store_true", help="accepted for CI symmetry; verify never reads the cache")
    l_verify.add_argument("--cache-dir", type=Path, default=None)
    l_verify.add_argument("--extends", type=Path, default=None, help="an older ledger directory or a heads.json")
    l_verify.add_argument("--signers-sha256", default=None)
    l_show = bl_ledger_sub.add_parser("show", help="print entries as JSON lines")
    l_show.add_argument("--ledger", type=Path, required=True)
    l_show.add_argument("--store", type=Path, default=None)
    l_show.add_argument("--by", default=None, metavar="KEY16")
    l_show.add_argument("--kind", choices=["axiom", "derived", "computed"], default=None)
    l_show.add_argument("--contested", action="store_true", help="admitted axiom entries with kernel conflicts (needs --store)")
    l_show.add_argument("--stale", action="store_true", help="entries excluded as stale (needs --store)")
    l_show.add_argument("--recheck", action="store_true", help="re-prove derived entries (needs --store)")
    l_show.add_argument("--signers-sha256", default=None)
    l_show.add_argument("--no-cache", action="store_true")
    l_show.add_argument("--cache-dir", type=Path, default=None)
```

- [ ] **Step 4: Run the tests**

Run: `$PYTEST tests/test_biolean_ledger_cli.py tests/test_biolean_cli.py tests/test_biolean_bench_cli.py -q`
Expected: all pass; the existing CLI tests are unchanged (the `--ledger` default is `None`, so `_biolean_store` takes the base-only path).

Mutation checks: (a) in `cmd_biolean`, catch `LedgerIntegrityError` and call `parser.error(...)`: `test_prove_check_goals_accept_ledger_and_prove_carries_the_doi` fails on the last block (SystemExit instead of 2 with JSON). (b) `_ledger_reference` choosing the reference from any ledger row: `test_prove_reference_is_set_only_when_every_matching_row_is_ledger_sourced` fails. (c) `verify` reading the cache (`use_cache=not args.no_cache` on either verify path): `test_verify_never_reads_the_cache_even_when_show_does` fails, the planted mark admitting the forged file. (d) `_ledger_body` calling `parser.error` on a `JSONDecodeError`: `test_append_body_that_is_not_json_is_rejected_not_a_usage_error` fails (SystemExit instead of 3); `append_entry` reporting `body_error` before the base check: `test_append_exit_2_conditions_print_json_errors_on_stdout` fails on its not-json call (3 instead of 2). (e) `show` printing `by` instead of the fingerprint, or dropping the key: `test_show_filters_and_store_requirement` fails. (f) drop the `BASE_READ_ERRORS` wrap in `load_with_ledger` (Task 7): `test_unreadable_store_is_exit_2_json_not_a_traceback` fails with a raw `EOFError`; drop `zlib.error` from the tuple: its corrupt-deflate case fails; `base_object` after `mkdir` in `init_ledger` (Task 8): its final assertion fails. Execution note: the `cli.py` snippets in this task are documentation as of commit edd9d4c — the committed `src/methods_graph/cli.py` is the source of truth (the sandbox copies it). Ruling checks added in execution: catch `RecursionError` in `_ledger_body` and pass `parse_constant` (a 1,000,000-deep body and `NaN` are LEDGER_BAD_BODY, never a traceback); `ensure_ascii=False` anywhere → the surrogate-field output test fails; `read_signer` on `--key ""` / `.` / `/`: `test_key_that_names_no_file_is_unsupported_key_json_not_a_traceback` raises with the bare `with_name`; a wrong `--signers-sha256` on prove is pinned in `test_prove_check_goals_accept_ledger_and_prove_carries_the_doi`; `show --by` takes only a key16 (`test_show_by_takes_only_a_key16`); `show` reports cache marks it could not write on stderr (`test_show_reports_cache_marks_it_could_not_write_on_stderr`); a store stat that raises is a usage error (`test_a_store_stat_that_raises_is_a_usage_error`).

- [ ] **Step 5: Run the whole suite, with and without the API key**

Run: `env -u OPENAI_API_KEY $PYTEST -q`
Expected: everything passes (about 1,150 tests; 1 skipped locally without `quration`).

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/cli.py .gitignore tests/test_biolean_ledger_cli.py
git commit -m "feat(biolean-ledger): mg biolean ledger init|append|verify|show; --ledger on prove|check|goals

Nested subparser dispatched before the store load. Every non-usage failure
prints {\"errors\": [...]} as JSON on stdout and returns 2, never through
parser.error. prove --ledger cites a ledger-sourced axiom's DOI.

mutation checked: routing integrity errors through parser.error breaks the
JSON contract test; choosing a reference from any ledger row when a base row
also matches fails the prove-reference test."
```

---

### Task 10: the north-star test, the docs, and the spec banner

**Files:**
- Modify: `tests/test_biolean_ledger_check.py` (append `test_rejection_fix_is_substitutable`)
- Create: `docs/biolean/ledger.md`
- Modify: `docs/biolean/README.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md`, `docs/README.md`, `CLAUDE.md`, `docs/superpowers/specs/2026-09-25-biolean-ledger-design.md` (status banner), this plan's banner

**Interfaces:** consumes everything; produces nothing new in code.

- [ ] **Step 1: Write the north-star test**

Append to `tests/test_biolean_ledger_check.py`:

```python
# ---------------------------------------------------------------------------
# the north star (spec section 7 table, section 9): fix is substitutable, options are complete
# ---------------------------------------------------------------------------
import pytest

from methods_graph.biolean.ledger.append import append_entry
from methods_graph.biolean.ledger.errors import LedgerIntegrityError
from methods_graph.biolean.ledger.format import shape_errors
from methods_graph.biolean.ledger.integrity import verify_ledger
from tests.biolean_ledger_fixture import KEY16_A, KEY_A, LFIX, TS, copy_signed, fake_runner, signed_store
from tests.test_biolean_ledger_format import entry as shape_entry

VALUE_FIX_ROWS = {
    LC.LEDGER_ALT_ID: new_fact(go_id="GO:0000102"),
    LC.OBSOLETE_TERM: new_fact(go_id="GO:0000010"),
    LC.LEDGER_ASPECT_MISMATCH: new_fact(aspect="F"),
    LC.LEDGER_ASSIGNED_BY: new_fact(assigned_by="UniProt"),
    LC.LEDGER_BAD_TAXON: new_fact(taxon="9606"),
    LC.LEDGER_BAD_DATE: new_fact(date="2026-09-25"),
    LC.LEDGER_BAD_CHARACTER: new_fact(gene_product_form_id="x\r"),
    LC.LEDGER_BAD_OBJECT_TYPE: new_fact(db_object_type=""),
}
OPTIONS_ROWS = {
    LC.UNKNOWN_QUALIFIER: new_fact(qualifier="bogus", go_id="GO:0000021", aspect="F"),      # an F term: 2 options, not 13
    LC.QUALIFIER_ASPECT_MISMATCH: new_fact(qualifier="enables"),
    LC.OBSOLETE_TERM: new_fact(go_id="GO:0000014"),                                        # several replaced_by
    "OBSOLETE_TERM/consider": new_fact(go_id="GO:0000012"),                                # only consider
    LC.LEDGER_ALT_ID: new_fact(go_id="GO:0000112"),                                        # alt of an obsolete with consider only
    LC.LEDGER_ECO_UNMAPPED: new_fact(evidence_code="XYZ"),
}
NULL_ROWS = {
    LC.UNKNOWN_TERM: new_fact(go_id="GO:0009999"),
    "OBSOLETE_TERM/none": new_fact(go_id="GO:0000013"),
    LC.LEDGER_BAD_SUBJECT: new_fact(db="1x"),
    LC.LEDGER_BAD_REFERENCE: new_fact(db_reference="PMID:0"),
    LC.LEDGER_REFERENCE_REQUIRED: new_fact(db_reference="foo:1"),
    "LEDGER_BAD_TAXON/none": new_fact(taxon="taxon:abc"),
    "LEDGER_BAD_DATE/none": new_fact(date="yesterday"),
    "LEDGER_BAD_OBJECT_TYPE/none": new_fact(db_object_id="P99999", db_object_type=""),
    LC.LEDGER_BAD_COLUMNS: new_fact()[:16],
    "LEDGER_BAD_COLUMNS/unknown-key": {**dict(zip(GAF_COLUMNS, new_fact())), "extra": "x"},   # fact_from_body's path
    LC.LEDGER_DUPLICATE: base_row(1)[:14] + [BY_A_COL, "", ""],
}


def _negated(fact):
    return fact[3].startswith("NOT|")


def test_rejection_fix_is_substitutable(tmp_path):
    """Every code in the section 7 table, from a row that triggers only that code and matches no base row.
    A value fix, written at `field`, gives ACCEPTED on re-check with the submitted polarity; each
    option does the same; the null rows return fix None. Must fail under: LEDGER_BAD_COLUMNS
    returning the names as fix; a column-4 option without NOT|; UNKNOWN_QUALIFIER returning all 13
    for an F term; a non-live id in OBSOLETE_TERM options."""
    for code, fact in VALUE_FIX_ROWS.items():
        res = run(fact)
        [e] = [x for x in res.errors if x.code == code]
        assert len(res.errors) == 1, (code, codes(res))
        assert e.fix is not None and not isinstance(e.fix, list) and e.options == (), code
        fixed = pointer_set({"fact": fact}, e.field, e.fix)["fact"]
        again = run(fixed)
        assert again.ok and _negated(again.fact) == _negated(fact), (code, codes(again))
    # the same, negated: every value fix keeps the NOT| prefix out of its way
    for code, fact in VALUE_FIX_ROWS.items():
        neg = list(fact)
        neg[3] = "NOT|" + neg[3]
        res = run(neg)
        [e] = [x for x in res.errors if x.code == code]
        again = run(pointer_set({"fact": neg}, e.field, e.fix)["fact"])
        assert again.ok and again.annotation.negated is True, code
    for label, fact in OPTIONS_ROWS.items():
        code = label.split("/")[0]
        res = run(fact)
        [e] = [x for x in res.errors if x.code == code]
        assert len(res.errors) == 1 and e.fix is None and e.options, (label, codes(res))
        assert list(e.options) == sorted(set(e.options))
        for option in e.options:
            again = run(pointer_set({"fact": fact}, e.field, option)["fact"])
            assert again.ok and _negated(again.fact) == _negated(fact), (label, option, codes(again))
    for label, body in NULL_ROWS.items():                       # through fact_from_body first, as append_entry does
        code = label.split("/")[0]
        fact, body_errs = fact_from_body(body)
        found = body_errs if fact is None else run(fact).errors
        errs = [x for x in found if x.code == code]
        assert errs and all(x.fix is None and x.options == () for x in errs), (label, [(x.code, x.field) for x in found])
    # the qualifier options with NOT| in play
    res = run(new_fact(qualifier="NOT|enables"))
    [e] = res.errors
    assert all(o.startswith("NOT|") for o in e.options) and len(e.options) == 7
    # shape-level codes
    [e] = [x for x in shape_errors(shape_entry(v=True)) if x.field == "/v"]
    assert e.fix == 1 and shape_errors(pointer_set(shape_entry(v=True), "/v", e.fix)) == []
    [e] = shape_errors(shape_entry(kind="rule"))
    assert e.fix is None and e.options == ("axiom", "computed", "derived")
    # derived: the conclusion fix is the elaborated goal
    res = check_derived({"derivation": good_derivation(), "conclusion": prop("GO:0000001")}, CTX)
    [e] = res.errors
    assert check_derived({"derivation": good_derivation(), "conclusion": e.fix}, CTX).ok
    for d in (dict(good_derivation(), root="s1"),):
        d["steps"].append({"id": "s9", "rule": "sorry", "conclusion": prop("GO:0000002"),
                           "provenance": {"method": "m:x", "inputs": ["GEO:1"], "parameters": {}, "claim": "c"}})
        errs = check_derived({"derivation": d}, CTX).errors
        assert errs and all(x.fix is None for x in errs)
    bad = good_derivation()
    bad["steps"][1]["edge"] = ["GO:0000003", "GO:0000001"]
    errs = check_derived({"derivation": bad}, CTX).errors
    assert [x.code for x in errs] == [LC.LEDGER_DERIVATION_REJECTED] and all(x.fix is None for x in errs)
    used = good_derivation()                                    # a sorry on the used chain: null, no options
    used["steps"].append({"id": "s9", "rule": "sorry", "conclusion": prop("GO:0000002"),
                          "provenance": {"method": "m:x", "inputs": ["GEO:1"], "parameters": {}, "claim": "c"}})
    used["root"] = "s9"
    [e] = check_derived({"derivation": used}, CTX).errors
    assert e.code == LC.LEDGER_SORRY_USED and e.fix is None and e.options == ()
    # computed and body: terminal or null
    errs = check_computed(good_computed(), CTX)
    assert [x.code for x in errs] == [LC.NOT_YET_DISCHARGEABLE]
    assert all(x.fix is None or x.field == "/conclusion/taxon" for x in errs)
    [e, _] = check_computed({**good_computed(), "graph_hash": "cd" * 32}, CTX)
    assert (e.code, e.field, e.fix, e.options) == (LC.LEDGER_BAD_COMPUTED, "/graph_hash", None, ())
    _, [e] = fact_from_body("x")
    assert e.fix is None
    # integrity-level codes (exit 2) carry no fix
    ledger, store = signed_store(tmp_path)
    (ledger / f"ledger/{KEY16_B}.jsonl").write_bytes(b"garbage\n")
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(), key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert [(x.code, x.context["file"]) for x in exc.value.errors] == [(LC.LEDGER_MALFORMED, f"ledger/{KEY16_B}.jsonl")]
    assert all(x.fix is None and x.context and "file" in x.context for x in exc.value.errors)
    ledger, store = signed_store(tmp_path / "two")             # the base mismatch: null, its context the digests
    (store / "gaf-eco-mapping.txt").write_text("# changed\nIDA\tDefault\tECO:0000314\n")
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(), key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_BASE_MISMATCH and e.fix is None and e.options == () and set(e.context) == {"obo", "gaf", "eco"}
    ledger = copy_signed(tmp_path / "three")                   # a shape/character fault at integrity: null, no options
    (ledger / f"ledger/{KEY16_A}.jsonl").write_bytes((LFIX / "signed-variants" / "surrogate.jsonl").read_bytes())
    with pytest.raises(LedgerIntegrityError) as exc:
        verify_ledger(ledger)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.fix is None and e.options == () and e.context["line"] == 1
```

Run: `$PYTEST tests/test_biolean_ledger_check.py -q -k substitutable`
Expected: PASS. Mutation checks, each restored after: (a) `fact_from_body`/step 1 returning `fix=list(GAF_COLUMNS)` for `LEDGER_BAD_COLUMNS`: fails at the null-rows loop; the unknown-key half is pinned by the `NULL_ROWS` row `"LEDGER_BAD_COLUMNS/unknown-key"`, which the committed loop feeds through `fact_from_body` first, as `append_entry` does. (b) `qualifier_options(aspect)` without the prefix: fails at the `NOT|enables` assertion (the negated loop yields no qualifier options, so it does not see this mutation). (c) `qualifier_options(None, ...)` in step 4 for a resolved term: fails on the F-term options case. (d) `_obsolete` offering `term.consider` unfiltered: fails on the `GO:0000012` case (`GO:0000999` is not a term). (e) `LEDGER_BAD_COMPUTED` at `/graph_hash` or `LEDGER_BASE_MISMATCH` shipping a value `fix` or non-empty `options`, or `LEDGER_SORRY_USED` shipping non-empty `options`: fails at that case and at no other ledger test; `LEDGER_SORRY_USED` shipping a value `fix` fails here and at `test_derived_with_used_sorry_refused` (Task 6), which already pins `fix is None`.

- [ ] **Step 2: Write `docs/biolean/ledger.md`**

Execution note: the markdown below is documentation as of commit 5083c13 — the committed `docs/biolean/ledger.md` is the source of truth (it has since gained the final-review fix wave), as for `cli.py` in Task 9.

```markdown
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

An entry is a GAF 2.2 row plus an envelope (`v, kind, ledger, base, check, prev, by, ts, sig`).
Each line is `canon(entry) + "\n"` with `canon = json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=True, allow_nan=False)`. The entry hash is sha256 over the canonical bytes without
`sig`; the signature (`ssh-keygen -Y sign`, namespace `biolean-ledger`) covers the same bytes.
`key16` is the first 16 hex of the sha256 of the signer's raw public-key blob; `by` is the full
digest with a `sha256:` prefix. Contributors read their key as `ssh-keygen -lf key.pub`
(`SHA256:<base64>`); every error that names a key prints both forms.

## 2. Commands

```bash
alias mg='.venv/bin/python -m methods_graph.cli'
mg biolean ledger init    --ledger DIR --store snapshots/go --key ~/.ssh/id_ed25519.pub [--principal NAME]
mg biolean ledger append  --ledger DIR --store snapshots/go --key ~/.ssh/id_ed25519 --fact '<json>'      # or @file
mg biolean ledger append  ... --derivation '{"derivation": {...}, "conclusion": {...}}'
mg biolean ledger append  ... --computed '<json>'                                                        # schema-checked, then refused (Phase B)
mg biolean ledger verify  --ledger DIR [--store DIR] [--recheck] [--extends OLDER_DIR|heads.json] [--signers-sha256 HEX] [--no-cache]
mg biolean ledger show    --ledger DIR [--store DIR] [--by KEY16] [--kind axiom|derived|computed] [--contested] [--stale] [--recheck]
mg biolean prove|check|goals ... --ledger DIR [--signers-sha256 HEX] [--no-cache] [--cache-dir DIR]
```

- `--key` for `append` is an unencrypted ed25519 private key, or its `.pub` when the private half is
  loaded in `ssh-agent`. A passphrase-protected private key file cannot be used directly: the entry
  goes to `ssh-keygen` on stdin, so it would read the passphrase from the entry and fail.
- `init` refuses a key that is not `ssh-ed25519` (`sk-` and certificate types included) and the
  two test fixture keys.
- `bench` never takes `--ledger`: items and scores are over the frozen base only.
- Every ledger call re-parses the base (about 13 s on `snapshots/go`) and verifies every signature
  (about 3 ms each). `load_store` caches "integrity passed for these bytes" per file under
  `~/.cache/biolean-ledger/`, keyed by ledger id, file name, file digest, `allowed_signers` digest
  and the verifier version. `ledger verify` never reads the cache; CI passes `--no-cache`.

## 3. Exit codes and output

| Exit | Meaning | Output |
|---|---|---|
| 0 | accepted / ok | `append`: `{"verdict": "ACCEPTED", "entry", "hash", "file", "line"}`; `verify`: `{"ok": true, "ledger": <report block>}` |
| 3 | rejected: the body is wrong and fixable | `{"verdict": "REJECTED", "errors": [...], "deferred": [...]}`; nothing written |
| 2 | usage error, including a `--store` missing one of its three base files | argparse text on stderr |
| 2 | unreadable (present but unparseable) store or ledger, integrity failure, base mismatch, signers mismatch, rollback, signing failure | `{"errors": [...]}` on stdout; nothing loads, nothing is written |

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
| `LEDGER_BAD_CHARACTER` | a surrogate, control, format or separator character, non-NFC text, or non-ASCII in an identifier column | the cleaned value |
| `LEDGER_BAD_SUBJECT` | column 1 not `^[A-Za-z][A-Za-z0-9_.-]*$`, or column 2 empty / whitespace / `|` | null |
| `UNKNOWN_TERM`, `LEDGER_ALT_ID`, `OBSOLETE_TERM` | column 5 is unknown, an alt id, or obsolete | alt id: the live primary or its replacement; obsolete: the single live `replaced_by`, else options |
| `LEDGER_ASPECT_MISMATCH` | column 9 differs from the term's namespace aspect | the letter |
| `UNKNOWN_QUALIFIER`, `QUALIFIER_ASPECT_MISMATCH` | column 4 unknown or illegal for the term's aspect | options: the legal qualifiers, with `NOT|` when the row had it |
| `LEDGER_ECO_UNMAPPED` | column 7 has no ECO mapping in the base | options: the mapped codes |
| `LEDGER_BAD_REFERENCE`, `LEDGER_REFERENCE_REQUIRED` | a `DOI:`/`PMID:`/`GO_REF:` value is malformed; none is present | null |
| `LEDGER_BAD_TAXON`, `LEDGER_BAD_DATE`, `LEDGER_BAD_OBJECT_TYPE` | column 13 not `taxon:<digits>`; column 14 not `YYYYMMDD`; column 12 empty | the rewritten value when derivable, else null with `context.form` |
| `LEDGER_ASSIGNED_BY` | column 15 is neither empty nor `biolean:<your key16>` | `biolean:<key16>` |
| `LEDGER_DUPLICATE` | the content key equals a base row's or another entry's | null; `context.existing` |
| `LEDGER_DERIVATION_REJECTED`, `LEDGER_SORRY_USED`, `LEDGER_SORRY_UNUSED`, `LEDGER_CONCLUSION_MISMATCH` | derived bodies | null, except the conclusion fix (the elaborated goal) |
| `LEDGER_BAD_COMPUTED`, `NOT_YET_DISCHARGEABLE` | computed bodies | null, except `/conclusion/taxon` (fix: the `NCBITaxon:<digits>` form when derivable, else `context.form`) and `/preconditions/<i>/status` (options: `met`, `unknown`, `unmet`) |
| `LEDGER_BAD_KIND` | `kind` is not `axiom`, `derived` or `computed` | null; options: the three kinds |
| `LEDGER_BASE_MISMATCH` | `--store` is not the base `base.json` declares | null; `context` the declared `obo`, `gaf`, `eco` digests |
| `LEDGER_VERSION` | `v` is not the JSON integer 1 | `1` |
| `LEDGER_MALFORMED`, `LEDGER_WRONG_LEDGER`, `LEDGER_SIGNER_MISMATCH`, `LEDGER_UNKNOWN_SIGNER`, `LEDGER_BAD_SIGNATURE`, `LEDGER_CHAIN_BROKEN`, `LEDGER_INVALID_ENTRY`, `LEDGER_ROLLBACK`, `LEDGER_SIGNERS_MISMATCH`, `LEDGER_UNSUPPORTED_KEY`, `LEDGER_KEY16_COLLISION`, `LEDGER_SIGNING_FAILED` | integrity and environment (exit 2) | null; `context.file`, `context.line` (a `LEDGER_MALFORMED` for an unknown `kind` keeps the three kinds as options) |

## 5. What verify proves, and what it does not

`verify` proves every entry present was signed by a key on `allowed_signers` with the namespace
permitted, that each file is one unbroken chain, that each `check.annotation_id` matches its
row, and that no fact repeats within a file. It does not prove completeness: a truncated file, a deleted file and an older version all
verify. `--extends <older dir | heads.json>` adds that check (`LEDGER_ROLLBACK`). Without
`--signers-sha256`, the trusted list is whatever was last pushed. Removing a key from
`allowed_signers` makes the whole ledger fail until that key's file is deleted too: revocation is
one commit that does both, and it is loud by design.

With `--store`, `verify` re-runs the append check on every entry against that base. An entry that
fails a base-independent check, or fails on the base it names, is `LEDGER_INVALID_ENTRY` (exit 2).
One that fails only because the base moved is `stale` (excluded, counted, listed). One whose
content the base now carries is `superseded_by_base` (excluded, counted, listed). The report
block:

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
sit beside the kernel and import no network or bench module (`test_ledger_and_verifier_modules_import_no_network_or_bench_module`).
Signing is the contributor's `ssh-keygen`; the repo has no signing code. Any change to
`ed25519.py` needs review against RFC 8032 §5.1.3 and §5.1.7; the vectors do not exercise every
path.

## 7. Contributing to a ledger repo

Clone, `append` locally (one machine per key, or pull before you append: two machines appending
under one key produce a fork, which is an integrity failure), push, open a PR. CI runs
`verify --ledger . --store <base> --signers-sha256 <target branch's digest> --recheck --extends
<merge base> --no-cache`. Changes to `allowed_signers`, `base.json` and `ledger.json` need owner
review on the host. The base pair must be available on the runner; today it cannot be re-fetched
(decision O-02), which blocks a federated ledger until the pair is published beside it.

## 8. Fixtures and tests

`tests/fixtures/biolean/ledger/`: a two-namespace ontology, a ten-row GAF, a four-code ECO
mapping, two ed25519 test keys (`keys/`, trusted by nothing, refused by `init`), four real
`ssh-keygen` signatures over known messages (`known/`), the RFC 8032 vectors, a signed fixture
ledger (`signed/`), hand-signed lines that must fail in specific ways (`signed-variants/`), and
one real signature per append a test makes (`sigs/`, content-addressed by the bytes signed).
`make_fixtures.py` makes all of them with the real `ssh-keygen`; the suite never spawns it.
Re-run it after any change to the envelope, the kernel version, the fixture base or a scenario.
```

- [ ] **Step 3: Update the other docs**

`docs/biolean/README.md`: in the header block add `**Ledger:** [ledger.md](ledger.md) (signed, hash-chained facts that extend the base; `mg biolean ledger`).` In §3's module table add rows: `ed25519.py` (verify-only Ed25519; trusted), `sshsig.py` (sshsig, allowed_signers; trusted), `ledger/` (format, check, integrity, load, append; trusted: it decides what enters the store). In §11 (CLI) add one line: "`ledger init|append|verify|show`, and `--ledger` on `check|prove|goals`: [ledger.md](ledger.md)." In §4 under `load_store` note the `ledger_dir=` keyword and the `ledger` / `ledger_gaf` report blocks.

`docs/ARCHITECTURE.md`: in the Biolean layout table (§2, "Biolean (`biolean/`)") add rows for `ed25519.py`, `sshsig.py`, `ledger/errors.py`, `ledger/format.py`, `ledger/check.py`, `ledger/integrity.py`, `ledger/load.py`, `ledger/append.py` with their line counts (`wc -l`). In §4d add the flow `mg biolean ledger append --fact ... → check.py (§2) → ssh-keygen -Y sign (runner seam) → self-verify → ledger/<key16>.jsonl` and `load_store(ledger_dir) → integrity.py → load.py (base binding) → StaticFactStore(base + admitted)`. In §6 (trust boundary) add the three verifier modules to the trusted set with the sentence "the ledger decides what enters the store, so it is inside the boundary". In §7 add the four `ledger` rows and the `--ledger` flags. In the "Shared code" note, `biolean/bench/items.py` now imports `read_release` from `store.py`, not `fetch.gaf_header`.

`docs/STATUS.md`: in §1.3 add a "Works" bullet: "`mg biolean ledger init|append|verify|show` and `--ledger` on `prove|check|goals`; N tests in `tests/test_biolean_ledger_*.py`, `test_biolean_ed25519.py`, `test_biolean_sshsig.py`; no ledger repo exists yet (the base pair cannot be re-fetched: O-02)." Update the test count in the header and §1.3.

`docs/README.md`: add the row `| [biolean/ledger.md](biolean/ledger.md) | The ledger as built: format, CLI contract, error table, what verify proves. |` and mention the plan in the `superpowers/plans/` row.

`CLAUDE.md`: in the Layout table's `biolean/` row append "; `ledger/` is the signed fact ledger (`mg biolean ledger init|append|verify|show`), with `ed25519.py` and `sshsig.py` the verify-only crypto beside it". Under "Run things this way" add:

```bash
.venv/bin/python -m methods_graph.cli biolean ledger verify --ledger <dir> --store snapshots/go --no-cache
.venv/bin/python tests/fixtures/biolean/ledger/make_fixtures.py   # regenerates every signed fixture with the real ssh-keygen; never run by the suite
```

and one trap line: "**Ledger fixtures are content-addressed signatures.** Changing the entry envelope, `methods_graph.__version__`, the ledger fixture base or a test scenario makes `fake_runner` fail naming a missing `sigs/*.sig`; re-run `make_fixtures.py` and commit."

Spec banner (`docs/superpowers/specs/2026-09-25-biolean-ledger-design.md`, the first blockquote): replace "not implemented. No plan exists yet." with "implemented per [`plans/2026-09-25-biolean-ledger.md`](../plans/2026-09-25-biolean-ledger.md) (merge commit `<hash>`). The plan refines the spec in twenty-seven places, listed in its 'Plan refinements' section; the code follows the plan where the two differ." Then copy the twenty-seven refinements verbatim under a "Divergences" heading in the banner.

This plan's banner: replace "not started" with the merge commit and the final test count.

- [ ] **Step 4: Run everything**

Run: `env -u OPENAI_API_KEY $PYTEST -q`
Expected: all pass. Record the count.

Run: `.venv/bin/python -m methods_graph.cli biolean ledger --help` and `... ledger append --help` and paste both into `docs/biolean/ledger.md` §2 only if they differ from the command block there.

- [ ] **Step 5: Commit**

```bash
git add tests/test_biolean_ledger_check.py docs/biolean/ledger.md docs/biolean/README.md docs/ARCHITECTURE.md docs/STATUS.md docs/README.md CLAUDE.md docs/superpowers/specs/2026-09-25-biolean-ledger-design.md docs/superpowers/plans/2026-09-25-biolean-ledger.md
git commit -m "docs(biolean-ledger): as-built guide, the north-star fix test, spec banner

test_rejection_fix_is_substitutable pins the §7 table: every value fix
re-checks to ACCEPTED with the submitted polarity, every option does, every
null-row code carries no fix.

mutation checked: offering the raw consider list (a non-term) and dropping
NOT| from qualifier options both fail the north-star test."
```

---

## Self-review (run by the planner before handoff)

**Spec coverage.** §0 decisions: 1 (trust boundary: Task 5's import test), 2 (allowed_signers only: Tasks 4, 7), 3 (`computed` refused: Task 6), 4 (GAF row + envelope: Tasks 5, 6), 5 (one file per key, chains: Task 7), 6 (verify-only, RFC vectors, real fixtures: Tasks 3, 4, 8), 7 (contested is not a rejection: Task 6 step 9, Task 7 report). §1: every field in `shape_errors` (Task 5), canonical bytes (Task 5), content key (Task 6), `read_release` move (Task 1). §2: steps 1–9 (Task 6), derived and computed (Task 6). §3: steps 0–7 (Task 7), `--extends` (Task 7), base binding, stale, superseded, duplicate content, contested (Task 7), load report and `ledger_gaf` (Task 7), cache (Task 7). §4: `allowed_signers` rules (Task 4), signing and self-verify (Task 8), the verifier (Tasks 3, 4). §5: schema check (Task 6). §6: `.gitignore` (Task 9); the CI command is documented (Task 10). §7: the CLI (Task 9), the payload (Tasks 5–9), the normative table (Task 10). §8: `admission` is opaque and preserved (Task 5). §9: every named test exists in Tasks 3–10, under the spec's name or a nearby one (`test_second_key_signature_is_signer_mismatch_or_unknown`, `test_small_order_keys_refused_in_allowed_signers`, `test_unsupported_key_type_refused_before_signing`, `test_key16_collision_refused`, `test_version_true_or_float_is_ledger_version`, `test_cache_hit_does_not_cover_a_renamed_copy` (renamed `test_cache_hit_still_binds_the_file_name_to_its_content_at_step_3` in the final-review fix wave; the cache key's file name is pinned by `test_cache_key_includes_file_name_signers_and_verifier_version`), `test_show_filters_and_store_requirement`, `test_bench_has_no_ledger_flag`, `test_init_writes_allowed_signers_base_json_ledger_json_and_ledger_dir` included).

**Placeholder scan.** No "TBD", "TODO", "similar to Task N", or "add validation". Task 10's doc edits are described as edits to named sections with the text to add; the only value left open is the merge commit hash, which does not exist until execution.

**Type consistency.** `LedgerError(code, message, field, got=, fix=, options=, context=)` is used with that positional order everywhere; `options` is always a tuple in code and a list in `to_dict()`; `check_axiom(fact, ctx, *, mode)` returns `AxiomResult` with `.fact/.annotation/.check/.deferred/.gaf_report`; `LedgerEntry(file, line, entry, hash)` with `.key16`; `LedgerState(ledger_dir, ledger_id, signers, allowed_signers_sha256, files, files_verified_from_cache)`; `load_with_ledger(...) -> (store, report, LoadedLedger)`; `append_entry(...) -> AppendResult` with `.to_json()`; `init_ledger(..., allow_fixture_keys=)`; `fake_runner(argv, *, input, capture_output, check)`; `verify_sshsig(sig, message, *, namespace) -> blob`. The test modules import exactly these names.

**Review Focus.** Line 1 → Task 7 `test_bom_crlf_and_missing_final_newline_are_malformed`. Line 2 → Task 6 `test_non_string_column_value_is_bad_columns`. Line 3 → Task 7 `test_missing_ledger_files_are_malformed_not_a_crash`. Line 4 → the `sig` half is Task 4 `test_sshsig_fields_are_enforced` (URL-safe, whitespace, empty) and Task 7 `test_unparseable_sig_is_bad_signature_with_file_and_line` at integrity; the `ts` half is Task 5 `test_impossible_ts_is_malformed_by_shape`. Line 5 → Task 9 `test_extends_with_a_bad_path_is_a_usage_error`.
