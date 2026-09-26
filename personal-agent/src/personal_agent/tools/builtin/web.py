"""web.search (self-hosted SearXNG) and web.fetch. Output is untrusted."""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, Field

from personal_agent.netpolicy import domain_allowed, host_of, is_private_host, registrable_domain
from personal_agent.tools.base import ToolContext, ToolOutput


class WebSearchParams(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    max_results: int = Field(default=8, ge=1, le=20)


class WebFetchParams(BaseModel):
    url: str = Field(pattern=r"^https?://")


_SCRIPT = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def html_to_text(html: str) -> str:
    return _WS.sub(" ", unescape(_TAG.sub(" ", _SCRIPT.sub(" ", html)))).strip()


def web_search(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    p = WebSearchParams.model_validate(args)
    if not ctx.searxng_url:
        raise RuntimeError("web.search disabled: PA_SEARXNG_URL not configured")
    r = httpx.get(f"{ctx.searxng_url.rstrip('/')}/search", params={"q": p.query, "format": "json"}, timeout=20)
    r.raise_for_status()
    results = [
        {"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")[:300]}
        for x in r.json().get("results", [])[: p.max_results]
    ]
    domains = sorted({registrable_domain(host_of(x["url"])) for x in results if x["url"]})
    return ToolOutput(output=results, discovered_domains=domains)


def web_fetch(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    p = WebFetchParams.model_validate(args)
    url = p.url
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        for _ in range(4):
            host = host_of(url)
            if is_private_host(host) or not domain_allowed(host, ctx.allowed_domains):
                raise PermissionError(f"egress to {host} not allowed")
            r = client.get(url, headers={"User-Agent": "personal-agent/0.1"})
            if r.is_redirect and "location" in r.headers:
                url = urljoin(url, r.headers["location"])
                continue
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            text = html_to_text(r.text) if "html" in ctype else r.text
            return {"url": url, "content": text[:20000]}
    raise RuntimeError("too many redirects")
