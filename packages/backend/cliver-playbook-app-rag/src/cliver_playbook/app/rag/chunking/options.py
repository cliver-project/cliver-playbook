"""Chunker option models and the flat catalog descriptor helper.

Option models are ordinary Pydantic models whose fields are primitives
with defaults. Two consumers share them:

* the upload endpoint validates the JSON object submitted by the
  browser against the selected chunker's ``options_model``;
* the stage catalog serializes the model through ``describe_options``
  into a flat list of field descriptors the web UI can render without
  a generic JSON-Schema renderer.

The flat contract is deliberate. Nested models, arrays, and required
fields would each need new UI machinery, so ``describe_options``
raises instead of silently emitting a descriptor the form cannot
honour. A chunker that needs a richer option can still accept JSON
through its own model, but it must keep the browser-facing model
flat.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BaseOptions(BaseModel):
    """Base class for every browser-configurable chunker option model.

    ``extra="forbid"`` turns a misspelled option into a validation
    error instead of a silent no-op: a user who asks for
    ``remove_boilerplte`` should be told, not quietly get the default.
    """

    model_config = ConfigDict(extra="forbid")


class EmptyOptions(BaseOptions):
    """No options. Used by chunkers whose output shape is fixed."""


class SectionOptions(BaseOptions):
    """Options shared by the structure-aware DOCX and HTML chunkers.

    ``chunk_size`` and ``chunk_overlap`` are separate parameters on
    ``Chunker.split`` because every chunker accepts them; these
    options only control how blocks become sections and how tables
    are rendered into text.
    """

    heading_based: bool = Field(
        default=True,
        description="Group blocks into heading-delimited sections.",
    )
    max_heading_level: int = Field(
        default=6,
        ge=1,
        le=9,
        description="Headings deeper than this level are treated as body text.",
    )
    include_tables: bool = Field(
        default=True,
        description="Include table content in the emitted chunks.",
    )
    table_format: Literal["markdown", "html"] = Field(
        default="markdown",
        description="How tables are rendered into chunk text.",
    )
    include_heading_path: bool = Field(
        default=True,
        description="Prefix each chunk with its heading path.",
    )


class DocxOptions(SectionOptions):
    """DOCX-specific options."""

    drop_toc: bool = Field(
        default=True,
        description="Skip paragraphs styled as a table of contents.",
    )


class HtmlOptions(SectionOptions):
    """HTML-specific options."""

    content_selector: str | None = Field(
        default=None,
        description="CSS selector for the content root. Empty means the whole body.",
    )
    remove_selectors: str | None = Field(
        default=None,
        description="Comma-separated CSS selectors removed after the content root is chosen.",
    )
    remove_boilerplate: bool = Field(
        default=True,
        description="Remove navigation, headers, footers, sidebars, and forms.",
    )
    include_links: bool = Field(
        default=True,
        description="Render inline links as [text](href).",
    )


def describe_options(model: type[BaseModel]) -> list[dict[str, Any]]:
    """Describe ``model`` as flat fields for the stage catalog and UI.

    Each descriptor has the shape::

        {
            "name": "heading_based",
            "label": "Heading Based",
            "type": "boolean" | "integer" | "string" | "enum",
            "default": ...,
            "enum": [...] | None,
            "minimum": ... | None,
            "maximum": ... | None,
            "description": "...",
        }

    The model must contain only boolean, integer, string, or
    single-value enum fields, all with defaults. ``str | None`` is
    normalized to ``string`` with a ``None`` default. Anything else
    raises ``TypeError`` so a new option cannot silently render as an
    unusable control.
    """
    schema = model.model_json_schema()
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: list[dict[str, Any]] = []

    for name, raw_property in properties.items():
        prop = dict(raw_property)
        if name in required:
            raise TypeError(f"option {name!r} must have a default")

        # Optional fields arrive as anyOf [<type>, null]. Collapse the
        # null branch; the UI treats the field as its real type and
        # renders an empty string as "unset".
        if "anyOf" in prop:
            variants = [variant for variant in prop["anyOf"] if variant.get("type") != "null"]
            if len(variants) != 1:
                raise TypeError(f"option {name!r} has an unsupported union type")
            merged = {**prop, **variants[0]}
            merged.pop("anyOf", None)
            prop = merged

        if "$ref" in prop or prop.get("type") in {"object", "array"}:
            raise TypeError(f"option {name!r} must be a flat primitive")

        enum = prop.get("enum")
        if enum is None and "const" in prop:
            enum = [prop["const"]]

        raw_type = prop.get("type")
        if enum is not None:
            field_type = "enum"
        elif raw_type == "boolean":
            field_type = "boolean"
        elif raw_type == "integer":
            field_type = "integer"
        elif raw_type == "string":
            field_type = "string"
        else:
            raise TypeError(f"option {name!r} has an unsupported type: {raw_type!r}")

        fields.append(
            {
                "name": name,
                "label": name.replace("_", " ").title(),
                "type": field_type,
                "default": prop.get("default"),
                "enum": enum,
                "minimum": prop.get("minimum"),
                "maximum": prop.get("maximum"),
                "description": prop.get("description", ""),
            }
        )

    return fields


__all__ = [
    "BaseOptions",
    "DocxOptions",
    "EmptyOptions",
    "HtmlOptions",
    "SectionOptions",
    "describe_options",
]
