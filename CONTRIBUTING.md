# Contributing

Thanks for helping improve tax-service. Everything runs in Docker, so you only need Docker and Git. No local Python is required.

## Set up

```sh
git clone https://github.com/The-Pied-Piper/tax-service.git
cd tax-service
./dev.sh build
./dev.sh help      # lists every command
```

## Before you open a pull request

```sh
./dev.sh check
```

This is the same command CI runs. It checks that generated code is up to date, then runs lint, type checks, tests and the migration check. A pull request needs it to pass. See the README for what each step does.

To run the API locally, use `./dev.sh up` (the README says how to reset afterwards).

## Proposing a change

- Open an issue first for anything bigger than a small fix, so we can agree on the approach.
- One pull request per change. Keep it small and focused.
- Add or update tests with the change. Tests live in `tests/`.
- Fill in the pull request template and write `closes #N` for the issue it resolves.

## Where a problem belongs

- The tax calculation itself (rates, brackets, credits and rounding) belongs to [tax-engine](https://github.com/The-Pied-Piper/tax-engine). Which deductions are included and how take-home pay is worked out from the engine's result stay here.
- Request and response shapes, validation, error messages and the deployed API belong here. The API is described in `openapi/openapi.yml`.

## Template files and service files

Part of this repository comes from a private service template. The README's layout marks the template-owned paths. The short version:

- **Template-owned** (`dev.sh`, `scripts/`, `tools/service_gen/`, `.github/workflows/ci.yml`): the maintainers replace these from the template (`./dev.sh upgrade`), so a change to them in a pull request may be overwritten. Open an issue rather than a pull request for these.
- **Service-owned** (everything else, such as `Dockerfile`, `compose.yaml`, `pyproject.toml` and `app/`): edit these freely; `upgrade` never touches them.
- **Generated** (`app/generated/**`): never edited by hand. Change `openapi/openapi.yml` and run `./dev.sh sync`.

## Security

Please do not report vulnerabilities in a public issue. See [SECURITY.md](SECURITY.md).
