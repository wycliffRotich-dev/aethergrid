"""
ADR 0102, decision 2. What the SQL of the public reader may look like.

The reader selects from the seven public views and from nothing else. These
tests read the source of the package and hold every query to one narrow
shape: a named column list, one public view, a fixed order that ends with the
id, and a bound limit. Nothing else is accepted, so a join, a star, a base
table, a literal limit or a query built from text fails here before any
database is involved.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

import pytest

from app.application.public_read_port import (
    PublicEventRecord,
    PublicJobRecord,
    PublicLeaseReclaimRecord,
    PublicLeaseRecord,
    PublicLeaseRefusalRecord,
    PublicNodeRecord,
    PublicWorkerRecord,
)

PACKAGE = (
    Path(__file__).resolve().parents[2] / "app" / "infrastructure" / "public_read"
)

RECORD_OF_VIEW = {
    "public_nodes": PublicNodeRecord,
    "public_jobs": PublicJobRecord,
    "public_workers": PublicWorkerRecord,
    "public_leases": PublicLeaseRecord,
    "public_events": PublicEventRecord,
    "public_lease_reclaims": PublicLeaseReclaimRecord,
    "public_lease_refusals": PublicLeaseRefusalRecord,
}

QUERY = re.compile(
    r"^\s*select\s+(?P<columns>[a-z_][a-z_0-9]*(?:\s*,\s*[a-z_][a-z_0-9]*)*)\s+"
    r"from\s+(?P<view>public_(?:nodes|jobs|workers|leases|events"
    r"|lease_reclaims|lease_refusals))\s+"
    r"order\s+by\s+(?P<order>"
    r"[a-z_][a-z_0-9]*(?:\s+(?:asc|desc))?"
    r"(?:\s*,\s*[a-z_][a-z_0-9]*(?:\s+(?:asc|desc))?)*)\s+"
    r"limit\s+%s\s*$",
    re.IGNORECASE,
)

WRITE = re.compile(
    r"^\s*(insert\s+into|update\s+\w+\s+set|delete\s+from|truncate\b|drop\s"
    r"|alter\s|create\s+(table|view|role|index|schema|function)|grant\s"
    r"|revoke\s|copy\s)",
    re.IGNORECASE,
)

SQL_TEXT = re.compile(
    r"\b(select|order\s+by|insert\s+into|delete\s+from)\b|public_\w+",
    re.IGNORECASE,
)

GOOD = [
    "SELECT id, reclaimed_at FROM public_lease_reclaims "
    "ORDER BY reclaimed_at DESC, id LIMIT %s",
    "SELECT id, refused_at FROM public_lease_refusals "
    "ORDER BY refused_at DESC, id LIMIT %s",
    "SELECT id, name FROM public_nodes ORDER BY name, id LIMIT %s",
    "SELECT id, occurred_at\nFROM public_events\nORDER BY occurred_at DESC, id\nLIMIT %s\n",
]

BAD = [
    "SELECT id FROM lease_reclaims ORDER BY id LIMIT %s",
    "SELECT id FROM public_lease_reclaims_x ORDER BY id LIMIT %s",
    "SELECT * FROM public_nodes ORDER BY id LIMIT %s",
    "SELECT id FROM nodes ORDER BY id LIMIT %s",
    "SELECT id FROM public_nodes JOIN tenants ON true ORDER BY id LIMIT %s",
    "SELECT id FROM public_nodes ORDER BY id",
    "SELECT id FROM public_nodes ORDER BY id LIMIT 10",
    "SELECT id FROM public_nodes LIMIT %s",
    "SELECT id FROM public_nodes ORDER BY id LIMIT {limit}",
    "SELECT id FROM public_nodes WHERE true ORDER BY id LIMIT %s",
    "SELECT id FROM public_nodes ORDER BY id LIMIT %s; DROP TABLE nodes",
    "SELECT (SELECT 1) FROM public_nodes ORDER BY id LIMIT %s",
]


def trees() -> list[ast.Module]:
    files = sorted(PACKAGE.glob("*.py")) if PACKAGE.is_dir() else []
    assert files, f"{PACKAGE} must exist and hold the reader"

    return [ast.parse(path.read_text(), filename=str(path)) for path in files]


def docstring_ids(tree: ast.Module) -> set[int]:
    found: set[int] = set()

    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            first = node.body[0] if node.body else None

            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.add(id(first.value))

    return found


def strings() -> list[str]:
    found: list[str] = []

    for tree in trees():
        skip = docstring_ids(tree)

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in skip
            ):
                found.append(node.value)

    return found


def queries() -> list[str]:
    found = [text for text in strings() if re.match(r"\s*select\b", text, re.I)]
    assert found, "the package must hold the queries of the seven views"

    return found


def is_text_with_sql(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and SQL_TEXT.search(node.value) is not None
    )


def test_the_package_holds_the_reader_module() -> None:
    assert (PACKAGE / "postgres_public_reader.py").is_file()


def test_there_is_exactly_one_query_per_public_view() -> None:
    views = sorted(
        match.group("view").lower()
        for query in queries()
        if (match := QUERY.match(query))
    )

    assert views == sorted(RECORD_OF_VIEW)


def test_every_select_has_the_narrow_shape() -> None:
    assert [query for query in queries() if not QUERY.match(query)] == []


def test_each_column_list_is_the_field_list_of_its_record() -> None:
    for query in queries():
        match = QUERY.match(query)
        assert match is not None, query

        columns = [column.strip().lower() for column in match.group("columns").split(",")]
        record = RECORD_OF_VIEW[match.group("view").lower()]

        assert columns == [field.name for field in dataclasses.fields(record)], query


def test_every_order_ends_with_the_id_ascending() -> None:
    for query in queries():
        match = QUERY.match(query)
        assert match is not None, query

        keys = [key.split() for key in match.group("order").lower().split(",")]

        assert keys[-1][0] == "id", query
        assert keys[-1][1:] in ([], ["asc"]), query


def test_no_statement_of_the_package_writes() -> None:
    assert [text for text in strings() if WRITE.match(text)] == []


def test_no_query_is_built_from_text() -> None:
    offenders: list[str] = []

    for tree in trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                text = "".join(
                    part.value
                    for part in node.values
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                )

                if SQL_TEXT.search(text):
                    offenders.append(f"f-string: {text[:40]}")
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                if is_text_with_sql(node.left):
                    offenders.append("percent formatting of SQL text")
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                if is_text_with_sql(node.left) or is_text_with_sql(node.right):
                    offenders.append("concatenation of SQL text")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"
                and is_text_with_sql(node.func.value)
            ):
                offenders.append("str.format on SQL text")

    assert offenders == []


@pytest.mark.parametrize("query", GOOD)
def test_the_shape_accepts_a_query_of_the_right_form(query: str) -> None:
    assert QUERY.match(query) is not None


@pytest.mark.parametrize("query", BAD)
def test_the_shape_refuses_a_query_of_the_wrong_form(query: str) -> None:
    assert QUERY.match(query) is None
