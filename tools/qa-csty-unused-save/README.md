# Fork QA: unused combat-style copy created by SaveGame

This push-only workflow runs only `jojokengly/NVForever` branch
`qa/csty-unused-save-20261114`. It creates no issue or PR and changes no public
candidate branch, repository settings or default branch. Local execution without
`--execute` prepares source only; hosted compilation must be explicitly enabled.

Three actual public sources run sequentially at the same absolute `output/source`
path, reusing only that job's private `output/target`:

1. Main805: `805454db21c5a4388cb7ee3e1002747acefb56c8`.
2. Prior refusal: `1ff900f2ee35d5feb967f8692b8b6c00243b967d`.
3. Public correction: `35f69bd452ccfcf29e78180e7fcf632799ae9dc5`.

Append the same `#[cfg(test)]` module to each `engine/nvf-play/src/save.rs`. It
contains the corrected public35f69 helpers and only the existing unused-copy case;
its actual selected name is
`save::unused_copy_qa::an_unused_csty_clone_created_by_savegame_still_enqueues_manual_and_auto_saves`.
The canonical source case is `save::tests::...`. This namespace-only test harness
avoids replacing/removing any existing helper, case, assertion or production on
any variant. The exact helper and test bodies are identical on all three.

The control uses the real SaveGame callback to make an unused TempCloneForm,
checks manual and auto enqueueing, callback execution, actual alias/carrier,
authored combat-style selection, serialized payload and restore fallback, and
preserves previous on-disk bytes before asynchronous writes. Main805 already has
TempCloneForm, `Game::combat_style`, `combat_style_id`, `checked_snapshot`, restore
and all save/queue APIs. The Vec-based authored plugin builders are unchanged
between main805 and fixed35f69. No new production API, stub, dependency, source
override or private aggregate is transplanted to the baseline.

No result is presumed. Setup/compiler failure is zero behavioral tests and stops
before another source variant. Exact list/run must execute one unignored case;
raw exits, counts and unrelated filtered counts are kept. Main and fixed must
pass to certify compatibility; refusal results are measured, not fabricated.
First assertion failure does not establish later assertions or the auto arm.

Full raw source hashes and Git identities are recorded before/after each phase.
Only the exact known appended fixture file is restored to its original raw bytes;
all original hashes and clean status must match before switching the same path.
Unknown outputs stop; no broad reset/clean or timestamp editing. Commands use
owned Linux process groups; timeout kills the group, reaps the child and aborts.
Phase executable hashes are historical captures: a later same-path build may
overwrite the earlier executable. Raw evidence excludes targets/source checkouts.

The hosted job uses two Cargo jobs, release/default features, stable Rust captured
in the receipt, and the upstream four development libraries. No cache is imported
or exported and there is no GPU, renderer, original game, native DLL, asset fetch
or full-save/native compatibility claim. Local source preparation is not a Rust
typecheck or test pass. Canonical CI remains separate from this focused comparison.
