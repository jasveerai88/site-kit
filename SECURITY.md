# Security Policy

## Reporting a vulnerability

Please report security issues privately through
GitHub's private vulnerability reporting on this
repository (Security → Report a vulnerability) rather
than a public issue.

## Scope notes

site-kit is a static, local-only tool suite:

- The checkers and previews read files; they never
  execute, import, compile, or install code from a
  checked folder, and the combined `launch-check` run
  writes nothing into the folder it checks (widget
  fragments are trial-rendered into a temporary
  directory and discarded).
- It makes no network calls and collects no telemetry.
  Site profiles and testimonials name real businesses
  and people in real use — the suite is designed so
  that data never leaves the machine.
- The generators (compliance-pages, widget-kit,
  link-page-kit, wall-of-love) write only where their
  own `--out` / `--output` arguments point, exactly as
  their standalone tools did.
- A PASS or READY verdict from any command means "none
  of the problems this suite's checks look for were
  found". It is not a guarantee of legal compliance —
  compliance-pages generates templates from the facts
  a profile states, and templates are not legal
  advice. Each report prints its own limits.
