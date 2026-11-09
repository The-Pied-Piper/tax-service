"""Load an OpenAPI 3 document and extract the operations we generate code for."""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

_PRIMITIVES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
}

# `string` params with these formats arrive from Connexion as str; the handler coerces them.
_STRING_FORMATS = {
    "uuid": ("UUID", "uuid"),
    "date": ("date", "datetime"),
    "date-time": ("datetime", "datetime"),
}
_TYPE_MODULES = {py_type: module for py_type, module in _STRING_FORMATS.values()}

# Conventional health-check operation names (after stripping get_/_check); see Operation.probe_kind.
_LIVENESS_OPS = {"livez", "live", "liveness", "healthz", "health"}
_READINESS_OPS = {"readyz", "ready", "readiness"}


class SpecError(Exception):
    pass


@dataclass
class Param:
    wire_name: str
    py_name: str
    py_type: str
    required: bool
    location: str
    # What Connexion actually passes; differs from py_type for formatted strings.
    wire_type: str = "str"
    default: Any = None
    maximum: Any = None

    @property
    def signature(self) -> str:
        return self._sig(self.py_type)

    @property
    def wire_signature(self) -> str:
        return self._sig(self.wire_type)

    @property
    def needs_coercion(self) -> bool:
        return self.py_type != self.wire_type

    @property
    def coercer(self) -> tuple[str, str]:
        """(module-level TypeAdapter variable name, the type it validates)."""
        type_expr = self.py_type if self.required else f"{self.py_type} | None"
        return "_" + re.sub(r"[^a-z0-9]+", "_", type_expr.lower()).strip("_"), type_expr

    @property
    def handler_arg(self) -> str:
        if not self.needs_coercion:
            return f"{self.py_name}={self.py_name}"
        return f"{self.py_name}={self.coercer[0]}.validate_python({self.py_name})"

    def _sig(self, py_type: str) -> str:
        if self.required:
            return f"{self.py_name}: {py_type}"
        return f"{self.py_name}: {py_type} | None = None"


@dataclass
class Property:
    """One property of an object schema.

    `name` is the attribute the generated Pydantic model gives it; it stays empty until
    `resolve_property_names` reads it back from the generated models.
    """

    wire_name: str
    required: bool
    name: str = ""
    # A model, list or object: the starter cannot convert it, so the author has to.
    nested: bool = False


# Conventional paging parameters (AIP-158): the client's page size and the opaque token.
_PAGE_SIZE_PARAMS = ("max_page_size", "page_size")
_PAGE_TOKEN_PARAM = "page_token"
_PAGE_SIZE_FALLBACK = (50, 100)
# What the port takes in place of them.
_LIMIT, _CURSOR = "limit", "cursor"


@dataclass
class Paging:
    """A list operation's paging parameters, which stay in the inbound adapter."""

    token: str
    size: str | None
    default_size: int
    max_size: int

    @property
    def port_names(self) -> set[str]:
        """The parameter names the port adds in place of the token and the size."""
        return {_CURSOR} | ({_LIMIT} if self.size is not None else set())


@dataclass
class Operation:
    operation_id: str
    function_name: str
    method: str
    path: str
    summary: str
    params: list[Param]
    body_type: str | None
    body_required: bool
    response_type: str | None
    # The handler returns this as the Content-Type: Connexion cannot choose between the
    # media types an operation declares (for example problem+json on an error) by itself.
    response_media_type: str | None
    status_code: int
    # Set when the body or the response is a component object schema: the adapter stub
    # maps its properties one by one instead of handing the generated model across.
    body_properties: list[Property] | None = None
    response_properties: list[Property] | None = None
    paging: Paging | None = None

    @property
    def handler_params(self) -> list[str]:
        """Signature for the Connexion-facing handler: raw wire types, body unvalidated."""
        return self._signature("Any", wire=True)

    @property
    def adapter_params(self) -> list[str]:
        """Signature for the request adapter: the body is a validated DTO."""
        return self._signature(self.body_type)

    def _body_props(self) -> list[Property]:
        props = self.body_properties or []
        assert all(p.name for p in props), "resolve_property_names has not run"
        return props

    @property
    def nested_body_properties(self) -> list[str]:
        return [p.name for p in self._body_props() if p.nested]

    @property
    def nested_response_properties(self) -> list[str]:
        return [p.name for p in self.response_properties or [] if p.nested and self._mapped(p)]

    @property
    def body_crosses_whole(self) -> bool:
        """The body is passed to the application as the generated model."""
        return self.body_type is not None and self.body_properties is None

    def _mapped(self, prop: Property) -> bool:
        if self.probe_kind is not None:
            return prop.name == "status"
        return prop.required

    @property
    def mapped_response_properties(self) -> list[tuple[Property, bool]]:
        """Each response property with whether the starter maps it (else it is a comment)."""
        return [(p, self._mapped(p)) for p in self.response_properties or []]

    @property
    def port_params(self) -> list[str]:
        """Signature for the application port: plain values, typed `Any` for the user to narrow."""
        if self.body_properties is None and self.paging is None:
            return self._signature("Any")
        required = [p.signature for p in self._port_params() if p.required]
        optional = [p.signature for p in self._port_params() if not p.required]
        if self.paging is not None:
            if self.paging.size is not None:
                required.append(f"{_LIMIT}: int")
            optional.append(f"{_CURSOR}: Any | None = None")
        for prop in self._body_props():
            if prop.required and self.body_required:
                required.append(f"{prop.name}: Any")
            else:
                optional.append(f"{prop.name}: Any | None = None")
        if self.body_properties is None and self.body_type is not None:
            if self.body_required:
                required.append("body: Any")
            else:
                optional.append("body: Any | None = None")
        return required + optional

    def _port_params(self) -> list[Param]:
        """The operation's parameters minus the paging ones, which the adapter keeps."""
        paging = {self.paging.token, self.paging.size} if self.paging else set()
        return [p for p in self.params if p.py_name not in paging]

    @property
    def call_args(self) -> list[str]:
        args = [f"{p.py_name}={p.py_name}" for p in self._port_params()]
        if self.paging is not None:
            if self.paging.size is not None:
                args.append(f"{_LIMIT}={_LIMIT}")
            args.append(f"{_CURSOR}={_CURSOR}")
        if self.body_properties is None:
            if self.body_type is not None:
                args.append("body=body")
        elif self.body_required:
            args += [f"{b.name}=body.{b.name}" for b in self._body_props()]
        else:
            args += [
                f"{b.name}=None if body is None else body.{b.name}" for b in self._body_props()
            ]
        return args

    @property
    def handler_call_args(self) -> list[str]:
        """Like call_args, but coerces formatted params and passes the validated DTO."""
        args = [p.handler_arg for p in self.params]
        if self.body_type is not None:
            args.append("body=request")
        return args

    @property
    def maps_result(self) -> bool:
        """The starter reads the application's result: a mapped property, or a validated one."""
        if self.response_properties is None:
            return self.response_type is not None
        return any(mapped for _, mapped in self.mapped_response_properties)

    @property
    def has_required_inputs(self) -> bool:
        return self.body_required or any(p.required for p in self.params)

    @property
    def probe_kind(self) -> str | None:
        """Return "live" or "ready" for conventional health-check operations, else None."""
        name = self.function_name.removeprefix("get_").removesuffix("_check")
        if name in _LIVENESS_OPS:
            return "live"
        if name in _READINESS_OPS:
            return "ready"
        return None

    def _signature(self, body_type: str | None, *, wire: bool = False) -> list[str]:
        """Parameters in call order: required, then body, then optional."""

        def sig(p: Param) -> str:
            return p.wire_signature if wire else p.signature

        required = [sig(p) for p in self.params if p.required]
        optional = [sig(p) for p in self.params if not p.required]
        if self.body_type is None:
            return required + optional
        if self.body_required:
            return required + [f"body: {body_type}"] + optional
        return required + optional + [f"body: {body_type} | None = None"]


@dataclass
class Tag:
    name: str
    snake: str
    pascal: str
    operations: list[Operation] = field(default_factory=list)

    def referenced_models(self, model_names: set[str]) -> list[str]:
        """Generated model class names used by this tag's bodies and responses."""
        classes = {pascal_case(n) for n in model_names}
        found: set[str] = set()
        for op in self.operations:
            for type_str in (op.body_type, op.response_type):
                if type_str:
                    tokens = re.findall(r"\b[A-Za-z_]\w*\b", type_str)
                    found.update(t for t in tokens if t in classes)
        return sorted(found)

    @property
    def adapter_validates_response(self) -> bool:
        """Some response is not a component object, so the stub validates it with a TypeAdapter."""
        return any(op.response_type and op.response_properties is None for op in self.operations)

    @property
    def adapter_uses_any(self) -> bool:
        return any(
            "Any" in re.findall(r"\b\w+\b", " ".join([*op.adapter_params, op.response_type or ""]))
            for op in self.operations
        )

    @property
    def is_health(self) -> bool:
        """Every operation is a liveness/readiness probe; its service gets a real implementation."""
        return bool(self.operations) and all(op.probe_kind for op in self.operations)

    @property
    def coercers(self) -> list[tuple[str, str]]:
        """Distinct (variable, type) TypeAdapters the handler module needs, sorted."""
        return sorted({p.coercer for op in self.operations for p in op.params if p.needs_coercion})

    @property
    def type_imports(self) -> list[tuple[str, str]]:
        """Stdlib (module, names) imports for param types, sorted by module."""
        by_module: dict[str, set[str]] = {}
        for op in self.operations:
            for p in op.params:
                for token in re.findall(r"\b\w+\b", p.py_type):
                    if token in _TYPE_MODULES:
                        by_module.setdefault(_TYPE_MODULES[token], set()).add(token)
        return [(m, ", ".join(sorted(names))) for m, names in sorted(by_module.items())]


@dataclass
class Spec:
    title: str
    version: str
    base_path: str
    tags: list[Tag]
    model_names: set[str]

    @property
    def operations(self) -> list[Operation]:
        return [op for tag in self.tags for op in tag.operations]

    @property
    def has_health_tag(self) -> bool:
        return any(tag.is_health for tag in self.tags)


def resolve_property_names(spec: Spec, fields: dict[str, dict[str, str]]) -> None:
    """Fill in each property's attribute name from the generated models.

    `fields` maps a model class to {wire name: attribute name}. A schema that did not
    become a plain model with those properties (a root model, say), or whose property
    names would clash with the operation's own parameters, is mapped whole instead.
    """

    def resolved(cls: str | None, props: list[Property] | None) -> list[Property] | None:
        known = fields.get(cls or "")
        if props is None or known is None or any(p.wire_name not in known for p in props):
            return None
        return [Property(p.wire_name, p.required, known[p.wire_name], p.nested) for p in props]

    for op in spec.operations:
        op.response_properties = resolved(op.response_type, op.response_properties)
        op.body_properties = resolved(op.body_type, op.body_properties)
        taken = {"self", *(p.py_name for p in op.params)}
        if op.paging is not None:
            taken |= op.paging.port_names
        if op.body_properties is not None:
            names = [b.name for b in op.body_properties]
            if len(set(names)) < len(names) or taken & set(names):
                op.body_properties = None


def snake_case(name: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    name = re.sub(r"_+", "_", name).strip("_").lower()
    if not name:
        raise SpecError("cannot derive an identifier from an empty name")
    if name[0].isdigit():
        name = f"_{name}"
    if keyword.iskeyword(name):
        name = f"{name}_"
    return name


def pascal_case(name: str) -> str:
    return "".join(part.capitalize() for part in snake_case(name).split("_"))


def load_spec(path: Path) -> Spec:
    with path.open() as fh:
        doc = yaml.safe_load(fh)
    if not isinstance(doc, dict) or "paths" not in doc:
        raise SpecError(f"{path} is not an OpenAPI 3 document")
    return parse_spec(doc)


def parse_spec(doc: dict[str, Any]) -> Spec:
    components = doc.get("components", {}) or {}
    model_names = set((components.get("schemas") or {}).keys())
    tags: dict[str, Tag] = {}
    seen_ids: set[str] = set()

    for path, path_item in (doc.get("paths") or {}).items():
        path_item = _deref(doc, path_item)
        shared_params = [_deref(doc, p) for p in path_item.get("parameters", [])]
        for method in HTTP_METHODS:
            raw = path_item.get(method)
            if raw is None:
                continue
            op = _parse_operation(doc, path, method, raw, shared_params)
            if op.operation_id in seen_ids:
                raise SpecError(f"duplicate operationId {op.operation_id!r}")
            seen_ids.add(op.operation_id)
            tag_name = (raw.get("tags") or ["default"])[0]
            tag = tags.setdefault(
                tag_name,
                Tag(name=tag_name, snake=snake_case(tag_name), pascal=pascal_case(tag_name)),
            )
            tag.operations.append(op)

    return Spec(
        title=doc.get("info", {}).get("title", "Service"),
        version=str(doc.get("info", {}).get("version", "0.1.0")),
        base_path=_base_path(doc),
        tags=sorted(tags.values(), key=lambda t: t.snake),
        model_names=model_names,
    )


def _parse_operation(
    doc: dict[str, Any],
    path: str,
    method: str,
    raw: dict[str, Any],
    shared_params: list[dict[str, Any]],
) -> Operation:
    operation_id = raw.get("operationId")
    if not operation_id:
        raise SpecError(f"{method.upper()} {path} is missing operationId")
    # Connexion resolves dotted operationIds as module paths; we only want the leaf.
    function_name = snake_case(operation_id.rsplit(".", 1)[-1])

    own_params = [_deref(doc, p) for p in raw.get("parameters", [])]
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for p in shared_params + own_params:
        merged[(p["name"], p["in"])] = p
    params = [_parse_param(doc, p) for p in merged.values()]

    body_type: str | None = None
    body_required = False
    body_properties: list[Property] | None = None
    if "requestBody" in raw:
        body = _deref(doc, raw["requestBody"])
        body_required = bool(body.get("required", False))
        body_type = _json_schema_type(doc, body.get("content", {}))
        body_properties = _model_properties(doc, _json_schema(body.get("content", {})))

    paging = _paging(params, body_properties)

    status_code, response_type, response_media_type = _success_response(
        doc, raw.get("responses", {})
    )
    response_properties = _model_properties(
        doc, _json_schema(_success_content(doc, raw.get("responses", {})))
    )

    return Operation(
        operation_id=operation_id,
        function_name=function_name,
        method=method,
        path=path,
        summary=raw.get("summary", ""),
        params=params,
        body_type=body_type,
        body_required=body_required,
        response_type=response_type,
        response_media_type=response_media_type,
        status_code=status_code,
        body_properties=body_properties,
        response_properties=response_properties,
        paging=paging,
    )


def _sane_size(value: Any) -> int | None:
    """A page size worth writing into the starter: a positive integer, not absurdly large."""
    ok = isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 10_000
    return value if ok else None


def _paging(params: list[Param], body_properties: list[Property] | None) -> Paging | None:
    """Paging parameters, when the operation takes a page token (AIP-158)."""
    names = {p.py_name: p for p in params}
    if _PAGE_TOKEN_PARAM not in names:
        return None
    # A page size that is not an integer is an ordinary parameter.
    size = next(
        (names[n] for n in _PAGE_SIZE_PARAMS if n in names and names[n].py_type == "int"), None
    )
    default, maximum = _PAGE_SIZE_FALLBACK
    if size is not None:
        default = _sane_size(size.default) or default
        maximum = _sane_size(size.maximum) or maximum
    default = min(default, maximum)
    paging = Paging(_PAGE_TOKEN_PARAM, size.py_name if size else None, default, maximum)
    # The port's own names must not collide with the operation's other inputs.
    taken = {*names, *(b.wire_name for b in body_properties or [])}
    return None if taken & paging.port_names else paging


def _parse_param(doc: dict[str, Any], raw: dict[str, Any]) -> Param:
    location = raw["in"]
    schema = _deref(doc, raw.get("schema", {}))
    return Param(
        wire_name=raw["name"],
        py_name=snake_case(raw["name"]),
        py_type=_param_type(doc, schema),
        required=location == "path" or bool(raw.get("required", False)),
        location=location,
        wire_type=_param_type(doc, schema, formats=False),
        default=schema.get("default"),
        maximum=schema.get("maximum"),
    )


def _param_type(doc: dict[str, Any], schema: dict[str, Any], *, formats: bool = True) -> str:
    """Python type of a path/query/header param.

    Connexion coerces integer/number/boolean; with ``formats`` the uuid/date/date-time
    string formats map to their stdlib types (the generated handler does that coercion).
    """
    kind = schema.get("type")
    if kind == "array":
        items = _deref(doc, schema.get("items", {}))
        return f"list[{_param_type(doc, items, formats=formats)}]"
    if kind == "string" and formats and schema.get("format") in _STRING_FORMATS:
        return _STRING_FORMATS[schema["format"]][0]
    return _PRIMITIVES.get(str(kind), "str")


def _success_status(responses: dict[Any, Any]) -> int | None:
    codes = sorted(
        (int(code) for code in responses if str(code).isdigit() and 200 <= int(code) < 300),
    )
    return codes[0] if codes else None


def _success_content(doc: dict[str, Any], responses: dict[Any, Any]) -> dict[str, Any]:
    status = _success_status(responses)
    if status is None:
        return {}
    response = _deref(doc, responses.get(status) or responses.get(str(status)) or {})
    content: dict[str, Any] = response.get("content", {})
    return content


def _success_response(
    doc: dict[str, Any], responses: dict[Any, Any]
) -> tuple[int, str | None, str | None]:
    status = _success_status(responses)
    if status is None:
        return 200, None, None
    content = _success_content(doc, responses)
    return status, _json_schema_type(doc, content), _json_media_type(content)


def _json_schema(content: dict[str, Any]) -> dict[str, Any]:
    media_type = _json_media_type(content)
    schema: dict[str, Any] = content[media_type].get("schema", {}) if media_type else {}
    return schema


def _model_properties(doc: dict[str, Any], schema: dict[str, Any]) -> list[Property] | None:
    """The properties of a component object schema, or None for any other kind of body."""
    ref = schema.get("$ref", "")
    if not ref.startswith("#/components/schemas/"):
        return None
    target = _deref(doc, schema)
    properties = target.get("properties")
    if any(key in target for key in ("allOf", "anyOf", "oneOf")):
        # Inherited or alternative properties are not in `properties`: map the schema whole.
        return None
    if (
        target.get("type", "object") != "object"
        or not properties
        or not isinstance(properties, dict)
    ):
        return None
    required = set(target.get("required", []))
    return [
        Property(name, name in required, nested=_is_nested(schema))
        for name, schema in properties.items()
    ]


_COMPOSED = ("allOf", "anyOf", "oneOf", "enum", "properties", "items")


def _is_nested(schema: Any) -> bool:
    """Whether the generator turns this property into a model, enum, list or object."""
    if isinstance(schema, dict) and "$ref" in schema:
        return True
    return isinstance(schema, dict) and (
        schema.get("type") in ("array", "object") or any(key in schema for key in _COMPOSED)
    )


def _json_media_type(content: dict[str, Any]) -> str | None:
    """The JSON media type a body is typed from: ``application/json``, else a ``+json`` type.

    Media types with parameters (``; charset=utf-8``) do not match: Connexion's response
    validation, on by default, rejects them.
    """
    if "application/json" in content:
        return "application/json"
    return next((key for key in content if key.endswith("+json")), None)


def _json_schema_type(doc: dict[str, Any], content: dict[str, Any]) -> str | None:
    media_type = _json_media_type(content)
    if media_type is None:
        return "Any" if content else None
    return _schema_type(doc, content[media_type].get("schema", {}))


def _schema_type(doc: dict[str, Any], schema: dict[str, Any]) -> str:
    """Map a body schema to a Python type that names the generated Pydantic models."""
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref.startswith("#/components/schemas/"):
            return pascal_case(ref.rsplit("/", 1)[-1])
        schema = _deref(doc, schema)
    kind = schema.get("type")
    if kind == "array":
        return f"list[{_schema_type(doc, schema.get('items', {}))}]"
    if kind in _PRIMITIVES:
        return _PRIMITIVES[kind]
    if kind == "object" or "properties" in schema:
        return "dict[str, Any]"
    return "Any"


def _deref(doc: dict[str, Any], node: Any) -> Any:
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            raise SpecError(f"external $ref not supported: {ref}")
        target: Any = doc
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            target = target[part]
        node = target
    return node


def _base_path(doc: dict[str, Any]) -> str:
    servers = doc.get("servers") or []
    if not servers:
        return ""
    path: str = urlparse(str(servers[0].get("url", ""))).path
    return path.rstrip("/")
