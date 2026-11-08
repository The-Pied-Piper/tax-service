# service_scripts/

Commands that belong to **this service**, not to the template.

`./dev.sh <command>` runs `scripts/<command>.sh` if there is one, otherwise
`service_scripts/<command>.sh`. `./dev.sh help` lists both, with the service's own
commands in a separate group.

- **You own this folder.** `./dev.sh upgrade` replaces `dev.sh`, `scripts/`,
  `tools/service_gen/` and `.github/workflows/ci.yml` from the template; it never
  touches `service_scripts/`. Commit it with the rest of the service.
- **One command per file**, `service_scripts/<command>.sh`, executable
  (`chmod +x`). Line 2 is its help text, as in `scripts/`:

  ```bash
  #!/usr/bin/env bash
  # Deploy the current commit to staging.
  source "$(dirname "$0")/../scripts/_lib.sh"   # optional: repo root, run/compose helpers
  ...
  ```

- **Template commands win.** If a file here has the same name as one in `scripts/`,
  it never runs and `help` does not list it. Pick another name.
- **Names starting with `_` are not commands** (use them for shared helpers you
  `source`).
- **Don't edit `scripts/` to add a command.** The next upgrade would erase it.
  Put it here instead.
