"""Pytest tests for agent.insights_digest — daily digest formatter."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.insights_digest import DIGEST_VERSION, render_digest

REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"


@pytest.fixture(scope="module", autouse=True)
def _require_pipeline():
    if not WAREHOUSE.exists():
        pytest.skip("warehouse not built — run `make resolve` first")


def test_text_digest_renders_header_and_top_block() -> None:
    out = render_digest(top_n=3, fmt="text")
    assert "IndiaStox insights digest" in out
    assert "week 2024-W01" in out
    assert f"digest_version={DIGEST_VERSION}" in out
    # At least one insight block rendered
    assert "surprise=" in out
    assert "->" in out


def test_markdown_digest_uses_md_syntax() -> None:
    out = render_digest(top_n=3, fmt="markdown")
    assert "# IndiaStox insights digest" in out
    assert "## Top" in out
    assert "**Suggested experiment:**" in out
    assert f"digest v{DIGEST_VERSION}" in out


def test_top_n_caps_visible_insights() -> None:
    short = render_digest(top_n=2, fmt="text")
    long = render_digest(top_n=10, fmt="text")
    assert short.count("surprise=") <= 2 + 1  # +1 for the header "top surprise=" line
    assert long.count("surprise=") >= short.count("surprise=")
