"""The documentation is checked against the code, so it cannot drift.

The README's API table, ER diagram and configuration tables, the two
``.env.example`` files, and every link between the Markdown documents.
"""

import re
from pathlib import Path

from fastapi.routing import APIRoute
from sqlmodel import SQLModel

from app.core.config import Settings
from app.main import app
from app.models.settings import AppSettings

REPO = Path(__file__).resolve().parents[2]
README = (REPO / "README.md").read_text()
DOCUMENTS = [REPO / "README.md", REPO / "CHANGELOG.md", *sorted((REPO / "docs").glob("*.md"))]


def _access(route: APIRoute) -> str:
    """Who may call a route, read off the dependencies it declares."""
    names, pending = [], list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        names.append(getattr(dependency.call, "__qualname__", ""))
        pending.extend(dependency.dependencies)
    if any("require_role" in name for name in names):
        return "admin"
    if any("get_stream_user" in name for name in names):
        return "ticket"
    return "user" if any("get_authenticated_user" in name for name in names) else "public"


def test_the_api_table_lists_every_route_with_its_access_level():
    documented = {
        (method, re.sub(r"\{[^}]*\}", "{}", path.split("?")[0]), access.strip("* "))
        for method, path, access in re.findall(r"^\| `([A-Z]+)`\s*\| `(/api/[^`]+)`\s*\|([^|]+)\|", README, re.MULTILINE)
    }
    actual = {
        (method, re.sub(r"\{[^}]*\}", "{}", route.path), _access(route))
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert documented == actual


def test_the_er_diagram_has_every_table_and_column():
    diagram = re.search(r"```mermaid\nerDiagram\n(.*?)```", README, re.DOTALL).group(1)
    documented = {
        table: [line.split() for line in body.strip().splitlines()]
        for table, body in re.findall(r"^    (\w+) \{\n(.*?)^    \}", diagram, re.DOTALL | re.MULTILINE)
    }

    assert set(documented) == set(SQLModel.metadata.tables)
    for name, table in SQLModel.metadata.tables.items():
        assert [column[1] for column in documented[name]] == [column.name for column in table.columns], name
        keys = {column[1]: column[2] for column in documented[name] if len(column) > 2}
        assert {name for name, key in keys.items() if key == "PK"} == {c.name for c in table.primary_key.columns}
        assert {name for name, key in keys.items() if key == "FK"} == {c.name for c in table.columns if c.foreign_keys}


def test_every_setting_is_in_the_readme_and_in_the_example_files():
    backend_example = (REPO / "backend" / ".env.example").read_text()
    infra_example = (REPO / "infra" / ".env.example").read_text()
    compose = (REPO / "infra" / "docker-compose.yml").read_text()

    for name in Settings.model_fields:
        assert f"| `{name}` |" in README, f"{name} is not in the README's configuration table"
        assert re.search(rf"^#? ?{name}=", backend_example, re.MULTILINE), f"{name} is not in backend/.env.example"
    for name in AppSettings.model_fields:
        assert name == "id" or f"| `{name}` |" in README, f"{name} is not in the README's settings table"
    # COMPOSE_PROJECT_NAME is set by Compose itself.
    for name in set(re.findall(r"\$\{([A-Z_]+)", compose)) - {"COMPOSE_PROJECT_NAME"}:
        assert re.search(rf"^#? ?{name}=", infra_example, re.MULTILINE), f"{name} is not in infra/.env.example"


def _outside_code(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _anchors(document: Path) -> set[str]:
    """The anchors GitHub gives the headings of a document."""
    headings = re.findall(r"^#{1,6} (.+)$", _outside_code(document.read_text()), re.MULTILINE)
    return {re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-") for heading in headings}


def test_every_link_between_the_documents_leads_somewhere():
    broken = []
    for document in DOCUMENTS:
        for target in re.findall(r"\]\(([^)\s]+)\)", _outside_code(document.read_text())):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path, _, anchor = target.partition("#")
            linked = (document.parent / path).resolve() if path else document
            if not linked.exists() or (anchor and anchor not in _anchors(linked)):
                broken.append(f"{document.relative_to(REPO)}: {target}")

    assert broken == []
