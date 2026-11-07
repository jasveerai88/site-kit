# Contributing

Thanks for looking. site-kit is a merged suite: five
tools with deliberately separate scopes, one
dispatcher. Contributions that keep each module's
scope sharp — and the merge honest — are welcome.

## Ground rules

- **Standard library only.** No third-party
  dependencies, no network calls, ever — in any module
  or in the dispatcher. The suite's promise is "clone
  and run" on the site owner's own machine.
- **The engines are ported, not rewritten.** Each
  module's checks, generators, verdict words, and
  honesty limits are its source tool's contract. A
  behaviour change to a module belongs upstream in
  that module's own test suite first: its ported suite
  here must keep passing, and any intentional
  divergence must be named in CHANGELOG.md, never
  silent.
- **Deterministic, always.** No LLM, no randomness:
  the same inputs must produce a byte-identical report
  on every run — including the combined receipt, which
  is why launch-check's trial render uses a fixed-name
  scratch folder that is removed when the run ends.
- **launch-check is read-only.** No module's combined
  run may write into the folder it checks. Generators
  run their read-only modes (check, preview, audit);
  widget-kit, which has no read-only mode, renders
  into the scratch folder and says so in its section.
  Tests prove fixture trees are byte-identical after
  a launch-check run; keep them passing.
- **Skipped is not clean.** A module with nothing to
  check reports itself skipped with a reason. Never
  let the combined verdict count a skipped module as
  evidence of readiness.
- **No tracebacks, ever.** Bad input is a clean
  `{"error": ...}` with exit 2 — including argument
  errors in `--json` mode, at dispatcher and module
  level alike.
- **Fixtures stay fictional.** Test sites, businesses
  and testimonials are invented; never commit a real
  site's data.

## Running the tests

```bash
python3 -m unittest discover -s tests
```

All 324 tests must pass on a clean checkout with
nothing but Python 3.10+ — including in a copy with
every file's executable bit stripped (the suites
invoke engines through the Python interpreter and set
any fixture permissions themselves). The five module
suites live in `tests/test_site_audit.py`,
`tests/test_compliance_pages.py`,
`tests/test_widget_kit.py`,
`tests/test_link_page_kit.py` and
`tests/test_wall_of_love.py`; dispatcher and
launch-check tests in `tests/test_site_kit.py`.
