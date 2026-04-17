"""ArXiv collector — uses the official Atom API.

- Categories: cs.AI, cs.LG, cs.CL
- Papers submitted within the past 48 hours
- Atom feed parsed with httpx + lxml
"""

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from lxml import etree

from newsbot.collection.base import BaseCollector
from newsbot.models import RawItem

logger = logging.getLogger(__name__)

_ARXIV_API = "https://export.arxiv.org/api/query"
_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL"]
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class ArxivCollector(BaseCollector):
    """Collects AI/ML papers from ArXiv."""

    def __init__(
        self,
        max_results: int = 50,
        hours_back: int = 48,
        timeout: float = 15.0,
    ) -> None:
        self._max_results = max_results
        self._hours_back = hours_back
        self._timeout = timeout

    @property
    def source_name(self) -> str:
        return "arxiv"

    async def collect(self) -> list[RawItem]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                feed_xml = await self._fetch_feed(client)
        except Exception as exc:
            self._log_error("failed to fetch arXiv feed", exc)
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._hours_back)
        items = self._parse_feed(feed_xml, cutoff)
        self._log_collected(len(items))
        return items

    async def _fetch_feed(self, client: httpx.AsyncClient) -> bytes:
        # combine categories with OR into a single query
        cat_query = " OR ".join(f"cat:{c}" for c in _CATEGORIES)
        params = {
            "search_query": cat_query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": self._max_results,
        }
        url = f"{_ARXIV_API}?{urlencode(params)}"
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content

    def _parse_feed(self, xml_bytes: bytes, cutoff: datetime) -> list[RawItem]:
        try:
            root = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError as exc:
            self._log_error("XML parse error", exc)
            return []

        items: list[RawItem] = []
        for entry in root.findall("atom:entry", _NS):
            item = self._parse_entry(entry, cutoff)
            if item is not None:
                items.append(item)
        return items

    def _parse_entry(
        self, entry: etree._Element, cutoff: datetime
    ) -> RawItem | None:
        try:
            title_el = entry.find("atom:title", _NS)
            summary_el = entry.find("atom:summary", _NS)
            published_el = entry.find("atom:published", _NS)
            id_el = entry.find("atom:id", _NS)

            if title_el is None or id_el is None:
                return None

            title = (title_el.text or "").strip().replace("\n", " ")
            summary = (summary_el.text or "").strip() if summary_el is not None else ""
            arxiv_url = (id_el.text or "").strip()

            if not title or not arxiv_url:
                return None

            # parse publication date
            published_str = (published_el.text or "").strip() if published_el is not None else ""
            published_at = self._parse_datetime(published_str)

            if published_at < cutoff:
                return None

            # category list
            categories = [
                el.get("term", "")
                for el in entry.findall("atom:category", _NS)
            ]

            # author list (up to 3)
            authors = [
                (el.findtext("atom:name", namespaces=_NS) or "").strip()
                for el in entry.findall("atom:author", _NS)
            ][:3]

            return RawItem(
                title=title,
                url=arxiv_url,
                body=summary[:1000] if summary else f"ArXiv paper: {title}",
                source=self.source_name,
                published_at=published_at,
                raw_score=0.0,  # arXiv has no native score
                metadata={
                    "categories": categories,
                    "authors": authors,
                },
            )
        except Exception as exc:
            self._log_error("failed to parse entry", exc)
            return None

    @staticmethod
    def _parse_datetime(dt_str: str) -> datetime:
        """Parse ISO 8601 datetime string. Returns epoch on failure."""
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return datetime.fromtimestamp(0, tz=timezone.utc)
