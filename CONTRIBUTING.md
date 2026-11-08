# Contributing

Thanks for helping improve service-template. Everything runs in Docker, so you only need Docker and Git. No local Python is required.

## Set up

```sh
git clone https://github.com/The-Pied-Piper/service-template.git
cd service-template
./dev.sh build
./dev.sh help      # lists every command
```

## Before you open a pull request

```sh
./dev.sh check
```

This is the same command CI runs. It checks that generated code is up to date, then runs lint, type checks, tests and the migration check. A pull request needs it to pass. See the README for what each step does.

To try the generator end to end, use `./dev.sh init && ./dev.sh up` (the README says how to reset afterwards).

## Proposing a change

- Open an issue first for anything bigger than a small fix, so we can agree on the approach.
- One pull request per change. Keep it small and focused.
- Add or update tests with the change. Generator tests live in `tools/service_gen/tests`.
- Fill in the pull request template and write `closes #N` for the issue it resolves.

## Template files and service files

The README has an ownership table. The short version:

- **Template-owned** (`dev.sh`, `scripts/`, `tools/service_gen/`, `.github/workflows/ci.yml`): these are replaced when a service runs `./dev.sh upgrade`. Changes here reach every service, so keep them backwards compatible and mention anything services must do by hand in the pull request.
- **Service-owned** (everything else shipped here, such as `Dockerfile`, `compose.yaml` and `pyproject.toml`): services edit these freely and `upgrade` never touches them. Changes here only affect new services.
- **Generated** (`app/generated/**` in a service): never edited by hand. Change `openapi/openapi.yml` and run `./dev.sh sync`.

## Security

Please do not report vulnerabilities in a public issue. See [SECURITY.md](SECURITY.md).
