# Changelog

## v1.0.0 — 2026-11-07

- **site-kit created** as the merged flagship ordered
  by FLEET-AUDIT-2026-11-04 (flagship B4, the last of
  the audit's four merges): five shipped static-site
  tools — site-audit, compliance-pages, widget-kit,
  link-page-kit and wall-of-love — become modules of
  one "is this static site ready to launch?" suite.
  They were always one job seen from five sides: audit
  the pages, generate the legal pages, the widgets,
  the link page and the testimonials wall — and nobody
  was installing five separate tools to do it.
- **Engines ported byte-identical** from the source
  packs — site_audit.py, compliance_pages.py,
  widget_kit.py, link_page_kit.py and wall_of_love.py,
  each at its source v0.1.0 state (verified with cmp
  against every source). No check, generator, verdict
  word, or honesty limit was changed; each module
  keeps its own CLI shape behind the suite command
  (`site-kit site-audit audit ...`,
  `site-kit compliance-pages make|check ...`,
  `site-kit widget-kit make ...`,
  `site-kit link-page-kit build|preview ...`,
  `site-kit wall-of-love build|preview ...`), and each
  still reports its own v0.1.0 inside its sections.
  The suite itself is v1.0.0 and ships at
  Production/Stable.
- **New: `launch-check` subcommand** — runs every
  module that has an input in one site folder and
  prints a single launch-readiness receipt. Input
  discovery is deterministic and documented:
  site-audit audits the folder itself when it holds
  HTML pages; compliance-pages gets the first `.json`
  carrying a business object and a pages list naming
  privacy, terms or cookies; widget-kit gets the
  first `.json` carrying a widgets list; link-page-kit
  gets the first `.json` carrying a name and a links
  list; wall-of-love gets the first `.json` carrying a
  testimonials list, else the first `.csv` whose
  header names name and quote. One file serves at most
  one module. `--json` emits one object whose
  per-module sections are the exact objects the
  modules print standalone, plus their exit codes.
  `--as-of` passes to compliance-pages' check only —
  the only module that takes a date.
- **launch-check is read-only by design.** Audits,
  checks and previews write nothing into the folder
  being checked. widget-kit — the one module with no
  read-only mode — trial-renders its fragments into a
  fixed-name temporary folder that is removed when the
  run ends, and its receipt section says so.
  compliance-pages runs its `check` mode, never
  `make`: the combined run reports the gaps a profile
  carries and generates nothing.
- **Honesty rules for the combined verdict.** A module
  with no qualifying input reports SKIPPED with a
  reason — never as passed — and **READY requires at
  least one module to have actually run and every
  module that ran to be clean**, so an empty folder is
  NOT READY. A module that errors on a discovered
  input counts as findings, never as skipped. READY
  speaks only for the modules' own checks — never for
  legal compliance or platform acceptance.
- **Tests: 324.** The five source suites carried over
  (71 + 34 + 48 + 62 + 76 = 291 tests; the only edit
  is each suite's examples paths — examples now live
  per-module under `examples/<module>/`), plus 33 new
  dispatcher tests covering routing for all five
  modules, the JSON/error contract, launch-check's
  discovery and skip honesty, the planted-fault
  fixture (one fault per module, each asserted
  exactly), read-only behaviour (the checked folder is
  byte-identical after a run) and byte-identical
  repeat runs.
- **Found in stage 1, fixed in the dispatcher only:**
  widget-kit's trial render first used a random
  temporary path, which leaked into its own reported
  output directory and made repeat `launch-check`
  receipts differ run to run — breaking the fleet's
  byte-identical-receipt rule. It now renders into a
  fixed-name temporary folder, removed in a `finally`,
  and determinism tests pin both the clean and the
  faulty receipts.
- **Observed in stage 1, deliberately not changed:**
  compliance-pages' `check` treats `--as-of` as a
  reported value and never parses it; only `make`
  validates the date. That is the engine's own source
  behaviour, and engines are ported, not improved —
  it is recorded here and in the README so the
  behaviour is known rather than silent.
