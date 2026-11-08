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
    status_code: int

    @property
    def handler_params(self) -> list[str]:
        """Signature for the Connexion-facing handler: raw wire types, body unvalidated."""
        return self._signature("Any", wire=True)

    @property
    def adapter_params(self) -> list[str]:
        """Signature for the request adapter: the body is a validated DTO."""
        return self._signature(self.body_type)

    @property
    def port_params(self) -> list[str]:
        """Signature for the application port: the body is a domain object (TODO for the user)."""
        return self._signature("Any")

    @property
    def call_args(self) -> list[str]:
        args = [f"{p.py_name}={p.py_name}" for p in self.params]
        if self.body_type is not None:
            args.append("body=body")
        return args

    @property
    def handler_call_args(self) -> list[str]:
        """Like call_args, but coerces formatted params and passes the validated DTO."""
        args = [p.handler_arg for p in self.params]
        if self.body_type is not None:
            args.append("body=request")
        return args

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
    if "requestBody" in raw:
        body = _deref(doc, raw["requestBody"])
        body_required = bool(body.get("required", False))
        body_type = _json_schema_type(doc, body.get("content", {}))

    status_code, response_type = _success_response(doc, raw.get("responses", {}))

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
        status_code=status_code,
    )


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


def _success_response(doc: dict[str, Any], responses: dict[Any, Any]) -> tuple[int, str | None]:
    codes = sorted(
        (int(code) for code in responses if str(code).isdigit() and 200 <= int(code) < 300),
    )
    if not codes:
        return 200, None
    status = codes[0]
    response = _deref(doc, responses.get(status) or responses.get(str(status)) or {})
    return status, _json_schema_type(doc, response.get("content", {}))


def _json_schema_type(doc: dict[str, Any], content: dict[str, Any]) -> str | None:
    media = content.get("application/json") or next(
        (v for k, v in content.items() if k.endswith("+json")), None
    )
    if media is None:
        return "Any" if content else None
    return _schema_type(doc, media.get("schema", {}))


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
