# Fork-only source fixture comparisons

This branch adds one push-only workflow and an orchestrator. It does not change
candidate production or public PR branches. Only `jojokengly/NVForever` at
`qa/cnd-null-baseline-20261114` can execute the two hosted jobs. No dispatch,
pull-request trigger, write token, game data, renderer launch or GPU use is needed.
The local default stages source only. `--execute` is restricted to the fork Actions
environment. ROOT reviews and pushes this QA branch separately.

The independent Ubuntu jobs use the upstream CI stable Rust action and release
configuration. The engine job installs the upstream four development libraries and
frees the same unused hosted SDK directories. Builds use two jobs and a private
target directory reused sequentially for that pair. No caches are imported,
exported or held locally. Full compile/list/named-case stdout/stderr, counts,
source/working hashes, commit/tree identities and patches are artifacts. Large
source checkouts and build targets are excluded from artifact uploads.

Both phases use the same absolute `output/source` checkout, preserving patched
dependency paths in Cargo's build identity. After the baseline post-execution
hash check, only its exact known fixture inputs are restored to their captured
original bytes (or the exact newly authored fixture is removed). Full raw hashes
and clean Git status must match before switching that checkout to the candidate.
Unknown changes stop the pair; there is no `git clean` or broad reset. Setup or
compile failure stops before candidate execution. Each Linux command has its own
process group; timeout kills that group and aborts the pair, without source switch.

## CND five actual producer fixtures

Baseline: exact public main `a605879db4d8a2d2998549c6788f3d190f1b5a56` production.
Inject the contiguous five producer helper/test block from actual candidate
`51ede41243a38fdfd532362ec7a3c915da53a771` into its existing stats test module,
plus the identical authored DDS generator and test-module visibility. These are
the only two changed files and all inserted code is in test modules. No
`picture_zoom`, `cut_picture`, layout metric, production API or dependency edit
is injected. Candidate production and fixtures stay exact51ede. Actual VFS,
TAI, GameData, Pictures, Ctx and condition produce the observed nodes and hits.

The candidate-only two cut helpers are retained canonical candidate coverage;
this five-fixture comparison does not inject or invoke them on main. They remain
part of canonical candidate CI, separate from this proof.

## NULL three actual public fixtures

Baseline: exact pre-fix public main `df80a70555baa182742808646019acedbe6791f7`
production. Add the byte-identical actual public05b test file and its sole module
registration to the existing integration target. The shared test common module
is byte-identical across these sources. No fixture invokes a new Host diagnostic
API, so no diagnostic-disabled production variant is substituted. Candidate:
`05b8316cc978ecc0966123d3e0ab34a93bf5ba35`, untouched. Schema reads use only
repository files. Source compilation, fatal errors, single evaluation, diagnostic
events and actual neighboring movement retain the original authored oracles.

No baseline outcomes are assumed. A compiler/setup failure is zero behavioral
tests, not a negative reproduction. Each exact named case records one outcome;
other suite tests are filtered and their filter counts remain in the raw result.
First-assertion aborts do not establish later branches. Candidate tests must all
pass; a baseline compile failure makes the workflow fail and retains its evidence.
This is a focused CPU source comparison, separate from canonical CI, whole UI
scheduling, installed-game behavior, native parity and full-mod compatibility.
