from typing import Any

import pytest

from tools.service_gen.spec import SpecError, parse_spec, resolve_property_names, snake_case

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


@pytest.mark.parametrize(
    ("declared", "media_type", "response_type"),
    [
        ("application/json", "application/json", "Thing"),
        ("application/vnd.api+json", "application/vnd.api+json", "Thing"),
        ("text/plain", None, "Any"),
        # Parameterised media types are not supported (see the README).
        ("application/json; charset=utf-8", None, "Any"),
    ],
)
def test_success_media_type_is_named_for_json_bodies(
    declared: str, media_type: str | None, response_type: str
) -> None:
    doc = {
        **MINIMAL,
        "paths": {
            "/things": {
                "get": {
                    "operationId": "getThing",
                    "responses": {
                        "200": {"description": "ok", "content": {declared: {"schema": THING_REF}}},
                        "404": {
                            "description": "nope",
                            "content": {"application/problem+json": {"schema": THING_REF}},
                        },
                    },
                }
            }
        },
    }

    (op,) = parse_spec(doc).tags[0].operations

    assert (op.response_media_type, op.response_type) == (media_type, response_type)


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


def _spec_with_models(*, body_required: bool = True) -> dict[str, Any]:
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "components": {
            "schemas": {
                "Gadget": {
                    "type": "object",
                    "required": ["gadgetId"],
                    "properties": {"gadgetId": {"type": "string"}, "label": {"type": "string"}},
                },
                "Empty": {"type": "object"},
            }
        },
        "paths": {
            "/gadgets": {
                "post": {
                    "operationId": "createGadget",
                    "requestBody": {
                        "required": body_required,
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Gadget"}}
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Gadget"}
                                }
                            },
                        }
                    },
                },
                "get": {
                    "operationId": "listGadgets",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/Gadget"},
                                    }
                                }
                            },
                        },
                        "202": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Empty"}
                                }
                            },
                        },
                    },
                },
            }
        },
    }
    return doc


GADGET_FIELDS = {"Gadget": {"gadgetId": "gadget_id", "label": "label_"}, "Empty": {}}


def _resolved(doc: dict[str, Any], fields: dict[str, dict[str, str]] = GADGET_FIELDS) -> Any:
    spec = parse_spec(doc)
    resolve_property_names(spec, fields)
    return {op.function_name: op for op in spec.operations}


def test_object_bodies_and_responses_are_mapped_property_by_property() -> None:
    create = _resolved(_spec_with_models())["create_gadget"]

    # Attribute names are the ones the model generator chose, not our own guess.
    assert [(p.name, p.required) for p in create.response_properties or []] == [
        ("gadget_id", True),
        ("label_", False),
    ]
    assert create.call_args == ["gadget_id=body.gadget_id", "label_=body.label_"]
    assert create.port_params == ["gadget_id: Any", "label_: Any | None = None"]


def test_an_optional_body_is_spread_with_every_property_optional() -> None:
    create = _resolved(_spec_with_models(body_required=False))["create_gadget"]

    assert create.call_args == [
        "gadget_id=None if body is None else body.gadget_id",
        "label_=None if body is None else body.label_",
    ]
    assert create.port_params == ["gadget_id: Any | None = None", "label_: Any | None = None"]


def test_responses_that_are_not_a_component_object_have_no_properties() -> None:
    assert _resolved(_spec_with_models())["list_gadgets"].response_properties is None


def test_a_schema_the_generator_did_not_make_a_plain_model_is_mapped_whole() -> None:
    # A root model has no fields of its own.
    create = _resolved(_spec_with_models(), {"Gadget": {}})["create_gadget"]

    assert create.body_properties is None
    assert create.response_properties is None
    assert create.call_args == ["body=body"]


def test_a_body_property_that_clashes_with_a_parameter_keeps_the_body_whole() -> None:
    doc = _spec_with_models()
    doc["paths"]["/gadgets/{label}"] = {
        "put": {
            "operationId": "replaceGadget",
            "parameters": [
                {"name": "label", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "requestBody": doc["paths"]["/gadgets"]["post"]["requestBody"],
            "responses": {"204": {"description": "ok"}},
        }
    }

    fields = {"Gadget": {"gadgetId": "gadget_id", "label": "label"}}
    replace = _resolved(doc, fields)["replace_gadget"]

    assert replace.body_properties is None
    assert replace.body_crosses_whole
    assert replace.call_args == ["label=label", "body=body"]


def test_nested_properties_are_flagged_for_the_author() -> None:
    doc = _spec_with_models()
    doc["components"]["schemas"]["Gadget"]["properties"]["parts"] = {
        "type": "array",
        "items": {"type": "string"},
    }
    fields = {"Gadget": {"gadgetId": "gadget_id", "label": "label_", "parts": "parts"}}

    create = _resolved(doc, fields)["create_gadget"]

    assert create.nested_body_properties == ["parts"]
    # Optional properties are not mapped, so there is nothing to convert for them.
    assert create.nested_response_properties == []
    assert not create.body_crosses_whole


@pytest.mark.parametrize(
    "prop",
    [
        {"$ref": "#/components/schemas/Empty"},
        {"allOf": [{"$ref": "#/components/schemas/Empty"}]},
        {"oneOf": [{"type": "string"}, {"type": "integer"}]},
        {"type": "string", "enum": ["a", "b"]},
        {"type": "object"},
        {"items": {"$ref": "#/components/schemas/Empty"}},
    ],
)
def test_properties_the_generator_turns_into_models_are_flagged(prop: dict[str, Any]) -> None:
    doc = _spec_with_models()
    doc["components"]["schemas"]["Gadget"]["properties"]["extra"] = prop
    fields = {"Gadget": {"gadgetId": "gadget_id", "label": "label_", "extra": "extra"}}

    assert _resolved(doc, fields)["create_gadget"].nested_body_properties == ["extra"]


def test_plain_properties_are_not_flagged() -> None:
    assert _resolved(_spec_with_models())["create_gadget"].nested_body_properties == []


def test_a_schema_that_inherits_properties_is_mapped_whole() -> None:
    doc = _spec_with_models()
    doc["components"]["schemas"]["Gadget"]["allOf"] = [{"$ref": "#/components/schemas/Empty"}]

    create = _resolved(doc)["create_gadget"]

    assert create.body_properties is None
    assert create.response_properties is None


def test_a_probe_maps_only_status() -> None:
    doc = _spec_with_models()
    doc["components"]["schemas"]["Gadget"]["properties"] = {
        "status": {"type": "string"},
        "version": {"type": "string"},
    }
    doc["components"]["schemas"]["Gadget"]["required"] = ["status", "version"]
    doc["paths"]["/livez"] = {
        "get": {
            "operationId": "getLivez",
            "responses": doc["paths"]["/gadgets"]["post"]["responses"]
            | {
                "200": {
                    "description": "ok",
                    "content": doc["paths"]["/gadgets"]["post"]["responses"]["201"]["content"],
                }
            },
        }
    }
    fields = {"Gadget": {"status": "status", "version": "version"}}

    live = _resolved(doc, fields)["get_livez"]

    assert [(p.name, mapped) for p, mapped in live.mapped_response_properties] == [
        ("status", True),
        ("version", False),
    ]


def _list_spec(params: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/things/{kind}": {
                "get": {
                    "operationId": "listThings",
                    "parameters": [
                        {
                            "name": "kind",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        *params,
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }


SIZE = {
    "name": "maxPageSize",
    "in": "query",
    "schema": {"type": "integer", "default": 25, "maximum": 200},
}
TOKEN = {"name": "pageToken", "in": "query", "schema": {"type": "string"}}


def test_paging_parameters_stay_in_the_adapter() -> None:
    op = parse_spec(_list_spec([SIZE, TOKEN])).operations[0]

    assert op.paging is not None
    assert (op.paging.token, op.paging.size) == ("page_token", "max_page_size")
    assert (op.paging.default_size, op.paging.max_size) == (25, 200)
    assert op.port_params == ["kind: str", "limit: int", "cursor: Any | None = None"]
    assert op.call_args == ["kind=kind", "limit=limit", "cursor=cursor"]
    # The adapter keeps the generated signature.
    assert op.adapter_params == [
        "kind: str",
        "max_page_size: int | None = None",
        "page_token: str | None = None",
    ]


def test_page_size_falls_back_when_the_spec_names_no_default_or_maximum() -> None:
    size = {"name": "pageSize", "in": "query", "schema": {"type": "integer"}}

    op = parse_spec(_list_spec([size, TOKEN])).operations[0]

    assert op.paging is not None
    assert (op.paging.size, op.paging.default_size, op.paging.max_size) == ("page_size", 50, 100)


def test_a_token_without_a_page_size_gives_the_port_only_a_cursor() -> None:
    op = parse_spec(_list_spec([TOKEN])).operations[0]

    assert op.port_params == ["kind: str", "cursor: Any | None = None"]
    assert op.call_args == ["kind=kind", "cursor=cursor"]


def test_an_ordinary_limit_param_can_sit_beside_a_token_without_a_page_size() -> None:
    limit = {"name": "limit", "in": "query", "schema": {"type": "integer"}}

    op = parse_spec(_list_spec([TOKEN, limit])).operations[0]

    assert op.paging is not None
    assert op.call_args == ["kind=kind", "limit=limit", "cursor=cursor"]


def test_page_size_ceiling_is_ten_thousand() -> None:
    def sizes(default: int, maximum: int) -> tuple[int | None, int | None]:
        size = {
            "name": "pageSize",
            "in": "query",
            "schema": {"type": "integer", "default": default, "maximum": maximum},
        }
        op = parse_spec(_list_spec([size, TOKEN])).operations[0]
        assert op.paging is not None
        return op.paging.default_size, op.paging.max_size

    assert sizes(10_000, 10_000) == (10_000, 10_000)
    assert sizes(50, 10_001) == (50, 100)


def test_a_page_size_alone_is_an_ordinary_parameter() -> None:
    op = parse_spec(_list_spec([SIZE])).operations[0]

    assert op.paging is None
    assert op.call_args == ["kind=kind", "max_page_size=max_page_size"]


def test_paging_is_left_alone_when_the_port_names_would_clash() -> None:
    limit = {"name": "limit", "in": "query", "schema": {"type": "integer"}}

    op = parse_spec(_list_spec([SIZE, TOKEN, limit])).operations[0]

    assert op.paging is None
    assert "page_token: str | None = None" in op.port_params


def test_a_page_size_that_is_not_an_integer_is_an_ordinary_parameter() -> None:
    size = {"name": "pageSize", "in": "query", "schema": {"type": "string"}}

    op = parse_spec(_list_spec([size, TOKEN])).operations[0]

    assert op.paging is not None
    assert op.paging.size is None
    assert op.call_args == ["kind=kind", "page_size=page_size", "cursor=cursor"]


def test_a_body_property_that_resolves_to_a_port_name_keeps_the_body_whole() -> None:
    doc = _spec_with_models()
    doc["paths"]["/gadgets/search"] = {
        "post": {
            "operationId": "searchGadgets",
            "parameters": [TOKEN],
            "requestBody": doc["paths"]["/gadgets"]["post"]["requestBody"],
            "responses": {"200": {"description": "ok"}},
        }
    }
    # The model generator names the property `cursor`, which the port uses for the cursor.
    fields = {"Gadget": {"gadgetId": "cursor", "label": "label_"}}

    search = _resolved(doc, fields)["search_gadgets"]

    assert search.body_properties is None
    assert search.port_params == ["body: Any", "cursor: Any | None = None"]
    assert search.call_args == ["cursor=cursor", "body=body"]


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({"type": "integer", "maximum": 10}, (10, 10)),
        ({"type": "integer", "default": 25, "maximum": 200}, (25, 200)),
        ({"type": "integer"}, (50, 100)),
        ({"type": "integer", "default": 10**30, "maximum": 10**31}, (50, 100)),
        ({"type": "integer", "default": 0}, (50, 100)),
    ],
)
def test_the_default_page_size_never_exceeds_the_cap(
    schema: dict[str, Any], expected: tuple[int, int]
) -> None:
    size = {"name": "pageSize", "in": "query", "schema": schema}

    paging = parse_spec(_list_spec([size, TOKEN])).operations[0].paging

    assert paging is not None
    assert (paging.default_size, paging.max_size) == expected
