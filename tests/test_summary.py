from pathlib import Path

import pytest

from tests.conftest import git
from tether.changes import snapshot_baseline
from tether.config import Config
from tether.summary import (
    FileChange,
    extract_symbols,
    one_line,
    render_markdown,
    summarize_changes,
)
from tether.tamper import turn_diff

ORDERS = (
    "import json\n\n\n"
    "def total(x):\n    return x * 2\n\n\n"
    "def legacy():\n    pass\n\n\n"
    "class Cart:\n    def add(self, item):\n        pass\n"
)


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "test")
    write(tmp_path, "src/shop/__init__.py", "")
    write(tmp_path, "src/shop/orders.py", ORDERS)
    write(tmp_path, "README.md", "hi\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def changes_for(
    repo: Path, baseline: str, changed: list[str]
) -> list[FileChange]:
    config = Config(root=repo)
    return summarize_changes(
        config, baseline, turn_diff(config, baseline, changed)
    )


def test_extract_symbols() -> None:
    symbols = extract_symbols(ORDERS)

    assert symbols is not None
    assert symbols.signatures == {
        "total": "total(x)",
        "legacy": "legacy()",
        "Cart": "class Cart",
        "Cart.add": "Cart.add(self, item)",
    }
    assert symbols.imports == {"json"}
    assert extract_symbols("def (:") is None


def test_symbol_level_changes(repo: Path) -> None:
    baseline = snapshot_baseline(repo)
    write(
        repo,
        "src/shop/orders.py",
        "import json\nimport requests\nfrom shop import models\n\n\n"
        "def total(x, tax: float) -> int:\n    return x * 2\n\n\n"
        "async def refund(order_id):\n    pass\n\n\n"
        "class Cart:\n    def add(self, item):\n        pass\n",
    )
    write(repo, "src/shop/models.py", "x = 1\n")

    changes = changes_for(repo, baseline, ["src/shop/models.py"])

    assert [(c.path, c.status) for c in changes] == [
        ("src/shop/models.py", "added"),
        ("src/shop/orders.py", "modified"),
    ]
    orders = changes[1]
    assert orders.added == ("async refund(order_id)",)
    assert orders.removed == ("legacy",)
    assert orders.changed == ("total(x) -> total(x, tax: float) -> int",)
    assert orders.new_imports == ("requests",)


def test_deleted_and_non_python_files(repo: Path) -> None:
    baseline = snapshot_baseline(repo)
    (repo / "src/shop/orders.py").unlink()
    write(repo, "README.md", "hi\nmore\n")

    changes = changes_for(repo, baseline, [])

    assert [(c.path, c.status, c.lines_added) for c in changes] == [
        ("README.md", "modified", 1),
        ("src/shop/orders.py", "deleted", 0),
    ]
    assert changes[1].removed == ("Cart", "Cart.add", "legacy", "total")


def test_render_markdown_and_one_line() -> None:
    changes = [
        FileChange(
            "src/shop/orders.py",
            "modified",
            5,
            1,
            added=("refund(order_id)",),
            new_imports=("requests",),
        ),
        FileChange("README.md", "modified", 1, 0),
    ]

    text = render_markdown(changes)

    assert one_line(changes) == (
        "tether: 2 file(s) (+6 -1), 1 symbol(s) added, new imports: requests"
    )
    assert "## (root)\n- `README.md` modified (+1 -0)" in text
    assert "## src/shop\n- `orders.py` modified (+5 -1)" in text
    assert "  - added: `refund(order_id)`" in text
    assert "  - new import: `requests`" in text


def test_render_markdown_without_changes() -> None:
    assert "No changes." in render_markdown([])
