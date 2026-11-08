from typing import Any

import pytest

from tools.service_gen.spec import SpecError, parse_spec, snake_case

THING_REF = {"$ref": "#/components/schemas/Thing"}

MINIMAL = {
    "openapi": "3.0.3",
    "info": {"title": "T", "version": "1"},
    "servers": [{"url": "https://x.example/api/v2/"}],
    "components": {
        "schemas": {"Thing": {"type": "object"}},
        "parameters": {
            "Limit": {"name": "limit", "in": "query", "schema": {"type": "integer"}},
        },
    },
    "paths": {
        "/things/{thingId}": {
            "parameters": [
                {"name": "thingId", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "put": {
                "operationId": "pkg.mod.replaceThing",
                "parameters": [
                    {"$ref": "#/components/parameters/Limit"},
                    {
                        "name": "X-Tags",
                        "in": "header",
                        "schema": {"type": "array", "items": {"type": "string"}},
                    },
                ],
                "requestBody": {"content": {"application/json": {"schema": THING_REF}}},
                "responses": {
                    "404": {"description": "nope"},
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {"schema": {"type": "array", "items": THING_REF}}
                        },
                    },
                },
            },
        }
    },
}


def test_parse_operation_shapes() -> None:
    spec = parse_spec(MINIMAL)
    assert spec.base_path == "/api/v2"
    (tag,) = spec.tags
    assert (tag.name, tag.snake, tag.pascal) == ("default", "default", "Default")
    (op,) = tag.operations
    assert op.operation_id == "pkg.mod.replaceThing"
    assert op.function_name == "replace_thing"
    assert op.status_code == 200
    assert op.response_type == "list[Thing]"
    assert op.body_type == "Thing"
    assert not op.body_required
    assert op.handler_params == [
        "thing_id: str",
        "limit: int | None = None",
        "x_tags: list[str] | None = None",
        "body: Any | None = None",
    ]
    assert op.adapter_params[-1] == "body: Thing | None = None"
    assert op.call_args == ["thing_id=thing_id", "limit=limit", "x_tags=x_tags", "body=body"]
    assert tag.referenced_models(spec.model_names) == ["Thing"]
    assert tag.coercers == []
    assert tag.type_imports == []


def test_formatted_string_params_are_typed_and_coerced() -> None:
    doc: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/things/{thingId}": {
                "get": {
                    "operationId": "getThing",
                    "parameters": [
                        {
                            "name": "thingId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "format": "uuid"},
                        },
                        {
                            "name": "since",
                            "in": "query",
                            "schema": {"type": "string", "format": "date-time"},
                        },
                        {"name": "q", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {"204": {"description": "ok"}},
                }
            }
        },
    }
    (tag,) = parse_spec(doc).tags
    (op,) = tag.operations
    # Connexion hands over strings; the adapter/port see real types.
    assert op.handler_params == [
        "thing_id: str",
        "since: str | None = None",
        "q: str | None = None",
    ]
    assert op.adapter_params == [
        "thing_id: UUID",
        "since: datetime | None = None",
        "q: str | None = None",
    ]
    assert op.handler_call_args == [
        "thing_id=_uuid.validate_python(thing_id)",
        "since=_datetime_none.validate_python(since)",
        "q=q",
    ]
    assert tag.coercers == [("_datetime_none", "datetime | None"), ("_uuid", "UUID")]
    assert tag.type_imports == [("datetime", "datetime"), ("uuid", "UUID")]


@pytest.mark.parametrize(
    ("operation_ids", "kinds", "is_health"),
    [
        (["getLivez", "getReadyz"], ["live", "ready"], True),
        (["healthz"], ["live"], True),
        (["readinessCheck"], ["ready"], True),
        (["getLivez", "listThings"], ["live", None], False),
    ],
)
def test_health_tag_detection(
    operation_ids: list[str], kinds: list[str | None], is_health: bool
) -> None:
    doc: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "paths": {
            f"/{op_id}": {
                "get": {
                    "tags": ["Status"],
                    "operationId": op_id,
                    "responses": {"204": {"description": "ok"}},
                }
            }
            for op_id in operation_ids
        },
    }
    spec = parse_spec(doc)
    (tag,) = spec.tags
    assert [op.probe_kind for op in tag.operations] == kinds
    assert tag.is_health is is_health
    assert spec.has_health_tag is is_health


def test_missing_operation_id_is_an_error() -> None:
    doc: dict[str, Any] = {"paths": {"/x": {"get": {"responses": {}}}}}
    with pytest.raises(SpecError, match="operationId"):
        parse_spec(doc)


def test_duplicate_operation_id_is_an_error() -> None:
    op = {"operationId": "same", "responses": {}}
    with pytest.raises(SpecError, match="duplicate"):
        parse_spec({"paths": {"/a": {"get": op}, "/b": {"get": op}}})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pageSize", "page_size"),
        ("X-Request-ID", "x_request_id"),
        ("widgetID", "widget_id"),
        ("class", "class_"),
        ("2fa", "_2fa"),
        ("Status", "status"),
    ],
)
def test_snake_case(raw: str, expected: str) -> None:
    assert snake_case(raw) == expected
