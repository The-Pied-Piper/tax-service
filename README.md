# service-template

[![CI](https://github.com/The-Pied-Piper/service-template/actions/workflows/ci.yml/badge.svg)](https://github.com/The-Pied-Piper/service-template/actions/workflows/ci.yml)

A GitHub template for **spec-first Python services**. You write an OpenAPI 3
contract; the template gives you a hexagonal-architecture
[Connexion 3](https://connexion.readthedocs.io/) (ASGI) service with Postgres,
migrations, tests and CI. When the contract changes you regenerate the plumbing
and keep every line of code you wrote by hand.

```
HTTP -> Connexion -> generated handler -> request adapter -> port -> service -> domain
                     (validates DTOs,     (DTO <-> domain)   (Protocol) (yours)
                      picks status)
```

## Why it exists

The opinion is **spec-first**: the contract comes first and the code follows it.
[Connexion](https://connexion.readthedocs.io/) follows from that choice. It is
the mainstream Python framework where the contract drives the code, whereas
FastAPI is code-first and derives the contract from the code afterwards.

Generating a service from a spec is easy once. The hard part is the second
change: most generators either overwrite your code or leave you to merge by hand.
Here the generator is vendored into the repo, owns only `app/generated/`, and
never touches files you own (see [Ownership](#ownership)). Template improvements
reach existing services through one command (`./dev.sh upgrade`).

### When an agent writes the code

When an AI agent writes most of the code, the contract is what a human still
reads and signs off: it is short, reviewable, and states what the service
promises. The boundary between generated and owned code also keeps the agent
away from the plumbing. `app/generated/` is rewritten from the spec and nothing
else, and CI's `check-generated` step fails if it has been edited by hand, so
any edit, by a person or an agent, belongs in the files you own. The human owns
the spec and the domain; the generator owns the rest.

## Everything runs in Docker

Everything runs in Docker: the app and Postgres via Compose, plain `pip` inside
the image. **You need Docker with Compose v2, plus bash and git** (the `./dev.sh` scripts
run on the host). No local Python, virtualenv or package manager, and there is
no non-Docker path. That is a
deliberate choice, so every machine and CI run uses the same environment.

## Try it

Docker with Compose v2 is the only thing to install (plus bash and git, which
most machines already have). The first build downloads images and takes a few
minutes.

```sh
git clone <your copy of this repo> my-service && cd my-service
./dev.sh init        # writes app/, tests/, README.md from the spec
./dev.sh up          # postgres + app with hot reload on :8080 (stays in the foreground)
```

In a second terminal, call the first endpoint:

```console
$ curl -i http://localhost:8080/api/v1/status/livez
HTTP/1.1 200 OK
date: Sun, 08 Nov 2026 07:03:04 GMT
server: uvicorn
content-type: application/json
content-length: 17

{"status": "ok"}
```

The example `openapi/openapi.yml` is a small Widget service, so this works out
of the box. The business endpoints answer `501 Not Implemented` until you fill in
the matching method in `app/application/services/<tag>_service.py`:

```console
$ curl -i http://localhost:8080/api/v1/widgets
HTTP/1.1 501 Not Implemented
date: Sun, 08 Nov 2026 07:03:04 GMT
server: uvicorn
content-type: application/problem+json
content-length: 91

{"type": "about:blank", "title": "Not Implemented", "detail": "listWidgets", "status": 501}
```

The Swagger UI is at `http://localhost:8080/api/v1/ui` (`./dev.sh docs` opens
it). `/api/v1` is the path in the contract's `servers` entry, so it changes with your contract.

The database login `app` / `app` in `compose.yaml` is for local development only.
Never reuse it anywhere reachable from a network.

## Who it is for

- You want a Python HTTP service where the OpenAPI contract is the source of
  truth and the code follows it.
- You are happy with the opinions here: Connexion 3, Pydantic, async SQLAlchemy
  and Alembic on Postgres, a hexagonal layout, Docker only.

- You are building a service you will keep changing, and you want to change the
  contract, not hand-edit generated code.

It is **not** for you if you need another web framework, another database, a
non-Docker workflow, or a generator that covers all of OpenAPI. It is also not
for generating client libraries or for languages other than Python.

How it differs from the usual alternatives:

- **cookiecutter** renders a project once. Afterwards the template and your
  project drift apart. Here `./dev.sh sync` regenerates from the spec at any time
  and `./dev.sh upgrade` pulls in template changes.
- **openapi-generator** is a general generator for many languages and
  frameworks. This is one opinionated stack, with the project scaffolding, tests,
  migrations and CI included, and a clear rule for which files are overwritten.

## Create a service

1. **Use this template** on GitHub (or clone and re-init), then clone your new repo.
2. Replace `openapi/openapi.yml` with your contract. Every operation needs an
   `operationId` (a tag is recommended; untagged operations go under `default`); bodies should `$ref` schemas under `components/schemas`.
3. Run `./dev.sh init` once, then `./dev.sh up`.
4. Commit. The generated `README.md` documents the service layout and day-to-day
   workflow (`./dev.sh help` lists every command). Copy `.env.example` to `.env`
   to change host ports or log level.

`./dev.sh` works from the host and from inside the app container (e.g. a VS Code
dev container). Inside, `compose.yaml` sets `IN_APP_CONTAINER=1` and commands run
directly; from the host they run in a one-off app container. Commands that manage
containers (`up`, `down`, `build`, `logs`, `fresh`, `psql`, `init`) run from the host.

## Evolve a service

Edit `openapi/openapi.yml`, then:

```sh
./dev.sh sync
```

`sync` rewrites `app/generated/` (Pydantic models + handlers) and creates
adapter/port/service stubs for any new tag. It never touches files you own; if a
new tag appeared it tells you to wire the adapter into `app/main.py`.

## Ownership

| Path | Owner | On `sync` | On `upgrade` |
| --- | --- | --- | --- |
| `app/generated/**` | generator | overwritten | overwritten (via sync) |
| `app/adapters/inbound/*_adapter.py`, `app/application/ports/*_port.py`, `app/application/services/*_service.py` | you (scaffolded once) | created if missing | untouched |
| `app/main.py`, `app/settings.py`, `app/domain/**`, `app/adapters/outbound/**`, `tests/**`, `README.md` | you (written by `init`) | untouched | untouched |
| `Dockerfile`, `compose.yaml`, the root `requirements*.in` and `requirements*.txt`, `pyproject.toml`, `alembic.ini`, `migrations/` | you (shipped plain) | untouched | untouched |
| `dev.sh`, `scripts/`, `tools/service_gen/`, `.github/workflows/ci.yml` | template | untouched | **replaced** |

## Known limits

The generator is small on purpose. It does not try to cover all of OpenAPI:

- **Every operation needs an `operationId`.** A missing or duplicate one stops
  `init` and `sync` with an error.
- **External `$ref`s are not supported** (anything not starting with `#/`); the
  tool stops with an error. Keep the contract in one file.
- **Only the first tag** of an operation is used to group it; operations without
  a tag go under `default`.
- **Only JSON bodies are typed.** Other media types are passed through as `Any`.
- **Only the lowest 2xx response** is used for the handler's status and return
  type; other responses are not generated.
- **It generates the HTTP layer, not your business logic.** Services, domain,
  outbound adapters (database access), migrations and tests are yours to write.
- Postgres and Docker only, as above.

## CI

Every service gets `.github/workflows/ci.yml` out of the box. On pushes to `main`
and `dev` and on pull requests it builds the dev image (cached) and runs `./dev.sh check` — the
same image and command as locally — and builds the production image once
`app/` exists. `check` is, in order:

| Step | Fails when |
| --- | --- |
| `check-generated` | `app/generated/` doesn't match what `sync` produces from the spec |
| `lint` | ruff check / format, or `openapi/openapi.yml` is not valid OpenAPI 3 |
| `typecheck` | mypy `--strict` |
| `test` | pytest (against the compose Postgres) |
| `check-migrations` | `alembic upgrade head` fails, or ORM models drifted from the migrations |

It is template-owned, so put service-specific jobs (deploy, publish) in
separate workflow files.

## Upgrading a service to a newer template

```sh
./dev.sh upgrade            # latest main
./dev.sh upgrade <branch>   # another branch of the template
```

Replaces the template-owned paths from this repo, records the version in
`TEMPLATE_VERSION`, rebuilds the dev image and runs `sync`. Review the result as
one PR: generator diff + regenerated code + any manual edits that are needed.
If the generator's pins changed, recompile `requirements-dev.txt` (the command is in
its header) so it matches `tools/service_gen/requirements.txt`; a test checks they agree.

Where the template is fetched from, in order: the `TEMPLATE_REPO` environment
variable, then the `TEMPLATE_REPO` file that `./dev.sh init` writes. By default
`init` records this template at the same host and scheme (SSH or HTTPS) as the
service's own `origin`, so access that works for the service works for the
template; pass `./dev.sh init --template-repo URL` to record a fork or mirror
instead. The `OWNER/REPO.git` used for the default comes from `$TEMPLATE_PATH`,
else the `TEMPLATE_HOME` file; a copy of the template points it at its own
repository.

## Layout of this repo (= an un-initialised service)

```
openapi/openapi.yml      example contract; a service replaces this
Dockerfile               dev target (tooling, bind mount) and prod target (slim)
compose.yaml             app + postgres:16 (.env.example lists the knobs)
requirements*.txt        pinned versions: runtime, tooling, and tools/service_gen/ (generator); compiled with uv (see the header of requirements.txt)
requirements*.in         the loose lists those are compiled from
pyproject.toml           ruff / mypy / pytest config only
alembic.ini, migrations/ async Alembic wired to app.settings
dev.sh                   dispatcher: ./dev.sh <cmd> -> scripts/<cmd>.sh
scripts/                 one command per file; line 2 is its help text
tools/service_gen/       the generator: cli.py, spec.py, render.py, templates/, tests/
.github/workflows/ci.yml lint + typecheck + test in Docker; prod image build
TEMPLATE_VERSION         what a service was last upgraded to
```

The service package is always `app/` and settings use the `APP_` env prefix, so
Dockerfile, compose and Alembic are plain files rather than templates.

## Maintenance

This is a small project, maintained on a best-effort basis. Contributions are
welcome: issues, questions and pull requests. Replies may take a few days. See
[CONTRIBUTING.md](CONTRIBUTING.md) to get started and [SECURITY.md](SECURITY.md)
to report a vulnerability. Issues labelled "good first issue" are a good place
to begin.

## Roadmap

Plans are tracked as [milestones](../../milestones) on GitHub:

- **First public release**: getting the repository ready to open up.
- **After launch**: CI that creates a fresh service and runs its full check on
  Linux and macOS, pinned GitHub Actions, documenting which choices are options
  and which are opinions, a release process, and launch material.
- **1.0**: the generator published as a Python package, and the skeleton as a
  Copier template.

## Developing the template

```sh
./dev.sh test tools/service_gen/tests    # generator tests (init + sync + a full request flow)
./dev.sh lint && ./dev.sh typecheck
./dev.sh init && ./dev.sh up             # try the result; `git clean -fd app tests && git checkout README.md` to reset
```

Templates live in `tools/service_gen/templates/`: `project/` is written once by
`init`, `generated/` is rewritten by every `sync`, `stubs/` are created only when
missing. If a change needs manual steps in services, say so in the PR description.

## License

This template is licensed under Apache-2.0; see [LICENSE](LICENSE). A service you
create from it does not inherit any licence obligation from the template: you
choose your service's licence.
