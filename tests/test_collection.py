"""Unit tests for the collection layer.

All external HTTP calls are handled with unittest.mock.AsyncMock + patch
instead of httpx.MockTransport / respx.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from newsbot.collection.arxiv import ArxivCollector
from newsbot.collection.base import BaseCollector
from newsbot.collection.hackernews import HackerNewsCollector, _is_ai_related
from newsbot.collection.registry import CollectorRegistry
from newsbot.models import RawItem


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_hn_item(
    item_id: int = 1,
    title: str = "New GPT model released",
    url: str = "https://example.com",
    score: int = 200,
    item_type: str = "story",
    time: int = 1700000000,
) -> dict:
    return {
        "id": item_id,
        "type": item_type,
        "title": title,
        "url": url,
        "score": score,
        "time": time,
        "by": "user123",
        "descendants": 42,
    }


def _arxiv_feed(entries: list[dict]) -> bytes:
    """Create minimal arXiv Atom feed XML."""
    atom_ns = "http://www.w3.org/2005/Atom"
    items_xml = ""
    for e in entries:
        items_xml += f"""
        <entry xmlns="{atom_ns}">
            <id>{e.get("id", "https://arxiv.org/abs/2401.00001")}</id>
            <title>{e.get("title", "Test Paper")}</title>
            <summary>{e.get("summary", "Abstract text.")}</summary>
            <published>{e.get("published", "2026-04-17T00:00:00Z")}</published>
            <category term="{e.get("category", "cs.AI")}" scheme="http://arxiv.org/schemas/atom"/>
            <author><name>{e.get("author", "Author Name")}</name></author>
        </entry>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="{atom_ns}">
        <title>ArXiv Query</title>
        {items_xml}
    </feed>""".encode()


# ── HackerNews keyword filter ──────────────────────────────────────────────────

class TestIsAiRelated:
    def test_recognizes_llm(self) -> None:
        assert _is_ai_related("New LLM benchmark released") is True

    def test_recognizes_machine_learning(self) -> None:
        assert _is_ai_related("Machine learning paper accepted at NeurIPS") is True

    def test_rejects_unrelated(self) -> None:
        assert _is_ai_related("PostgreSQL 17 released") is False

    def test_case_insensitive(self) -> None:
        assert _is_ai_related("GPT-5 IS HERE") is True

    def test_recognizes_model_keyword(self) -> None:
        assert _is_ai_related("New language model from DeepMind") is True


# ── HackerNewsCollector ────────────────────────────────────────────────────────

class TestHackerNewsCollector:
    def _collector(self) -> HackerNewsCollector:
        return HackerNewsCollector(min_score=100, max_items=10, timeout=5.0)

    def test_source_name(self) -> None:
        assert self._collector().source_name == "hackernews"

    @pytest.mark.asyncio
    async def test_collect_returns_raw_items(self) -> None:
        collector = self._collector()
        story_ids = [1, 2, 3]
        items_data = {
            1: _make_hn_item(1, "New GPT release", score=300),
            2: _make_hn_item(2, "PostgreSQL 17 released", score=500),  # Non-AI -> skip
            3: _make_hn_item(3, "LLM inference speedup", score=150),
        }

        async def mock_get(url: str, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "topstories" in url:
                resp.json = MagicMock(return_value=story_ids)
            else:
                item_id = int(url.split("/item/")[1].split(".json")[0])
                resp.json = MagicMock(return_value=items_data[item_id])
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = await collector.collect()

        assert len(results) == 2
        titles = {r.title for r in results}
        assert "New GPT release" in titles
        assert "LLM inference speedup" in titles
        assert all(isinstance(r, RawItem) for r in results)

    @pytest.mark.asyncio
    async def test_collect_skips_low_score(self) -> None:
        collector = self._collector()
        story_ids = [1]
        items_data = {1: _make_hn_item(1, "AI model released", score=50)}

        async def mock_get(url: str, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "topstories" in url:
                resp.json = MagicMock(return_value=story_ids)
            else:
                resp.json = MagicMock(return_value=items_data[1])
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = await collector.collect()

        assert results == []

    @pytest.mark.asyncio
    async def test_collect_returns_empty_on_network_error(self) -> None:
        collector = self._collector()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx_import_error())
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = await collector.collect()

        assert results == []

    def test_parse_skips_non_story(self) -> None:
        collector = self._collector()
        data = _make_hn_item(item_type="job", title="AI Engineer at OpenAI", score=200)
        assert collector._parse(data) is None

    def test_parse_skips_missing_url(self) -> None:
        collector = self._collector()
        data = _make_hn_item()
        data["url"] = ""
        assert collector._parse(data) is None

    def test_parse_metadata(self) -> None:
        collector = self._collector()
        data = _make_hn_item(1, score=200)
        item = collector._parse(data)
        assert item is not None
        assert item.metadata["hn_id"] == 1
        assert item.metadata["comments"] == 42


def httpx_import_error():
    import httpx
    return httpx.ConnectError("connection refused")


# ── ArxivCollector ────────────────────────────────────────────────────────────

class TestArxivCollector:
    def _collector(self) -> ArxivCollector:
        return ArxivCollector(max_results=20, hours_back=48, timeout=10.0)

    def test_source_name(self) -> None:
        assert self._collector().source_name == "arxiv"

    @pytest.mark.asyncio
    async def test_collect_returns_recent_papers(self) -> None:
        collector = self._collector()
        recent_ts = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        feed = _arxiv_feed([
            {"id": "https://arxiv.org/abs/2401.00001", "title": "Attention Is All You Need v2",
             "published": recent_ts, "category": "cs.AI"},
        ])

        async def mock_get(url: str, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.content = feed
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = await collector.collect()

        assert len(results) == 1
        assert results[0].source == "arxiv"
        assert results[0].title == "Attention Is All You Need v2"
        assert results[0].raw_score == 0.0

    @pytest.mark.asyncio
    async def test_collect_filters_old_papers(self) -> None:
        collector = self._collector()
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=72)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        feed = _arxiv_feed([
            {"id": "https://arxiv.org/abs/2401.00002", "title": "Old paper",
             "published": old_ts, "category": "cs.LG"},
        ])

        async def mock_get(url: str, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.content = feed
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = await collector.collect()

        assert results == []

    @pytest.mark.asyncio
    async def test_collect_returns_empty_on_network_error(self) -> None:
        collector = self._collector()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            import httpx
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = await collector.collect()

        assert results == []

    def test_parse_invalid_xml_returns_empty(self) -> None:
        collector = self._collector()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        result = collector._parse_feed(b"<invalid xml", cutoff)
        assert result == []

    def test_parse_datetime_invalid_returns_epoch(self) -> None:
        result = ArxivCollector._parse_datetime("not-a-date")
        assert result == datetime.fromtimestamp(0, tz=timezone.utc)


# ── CollectorRegistry ─────────────────────────────────────────────────────────

class TestCollectorRegistry:
    def _make_collector(self, name: str, items: list[RawItem]) -> BaseCollector:
        class FakeCollector(BaseCollector):
            @property
            def source_name(self) -> str:
                return name

            async def collect(self) -> list[RawItem]:
                return items

        return FakeCollector()

    def _make_raw(self, title: str, source: str) -> RawItem:
        return RawItem(
            title=title,
            url="https://example.com",
            body="body",
            source=source,
            published_at=datetime.now(timezone.utc),
            raw_score=100.0,
        )

    @pytest.mark.asyncio
    async def test_collect_all_merges_results(self) -> None:
        registry = CollectorRegistry()
        registry.register(self._make_collector("a", [self._make_raw("A1", "a"), self._make_raw("A2", "a")]))
        registry.register(self._make_collector("b", [self._make_raw("B1", "b")]))

        results = await registry.collect_all()
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_collect_all_tolerates_failing_collector(self) -> None:
        class FailingCollector(BaseCollector):
            @property
            def source_name(self) -> str:
                return "failing"

            async def collect(self) -> list[RawItem]:
                raise RuntimeError("boom")

        registry = CollectorRegistry()
        registry.register(FailingCollector())
        registry.register(self._make_collector("ok", [self._make_raw("OK", "ok")]))

        results = await registry.collect_all()
        assert len(results) == 1
        assert results[0].title == "OK"

    @pytest.mark.asyncio
    async def test_collect_all_empty_registry(self) -> None:
        registry = CollectorRegistry()
        results = await registry.collect_all()
        assert results == []

    def test_register_appends_collector(self) -> None:
        registry = CollectorRegistry()
        c = self._make_collector("x", [])
        registry.register(c)
        assert len(registry._collectors) == 1
