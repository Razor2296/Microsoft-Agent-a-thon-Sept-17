"""
app/backend/web_agent.py
Skill 2.3 — Web Automation Agent for Ignite Chat

Autonomously fetches web pages, scrapes HTML structure, cleans page text,
extracts title and hyperlinks using BeautifulSoup and requests.

LLM Reference: See app/skills/02_core_features/SKILLS_CORE.md § 2.3
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from backend.core.libraries import get_assistant_logger
from backend.core.schemas import WebScrapeRequest, WebScrapeResult

logger = get_assistant_logger("web_agent")

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class WebAgent:
    """
    Autonomous Web Agent for fetching dynamic pages, parsing HTML,
    cleaning body text, and extracting structured links.
    """

    def __init__(self, timeout_seconds: float = 10.0, user_agent: str = _DEFAULT_USER_AGENT):
        self.timeout = timeout_seconds
        self.user_agent = user_agent

    def scrape_url(
        self,
        url: str,
        extract_links: bool = True,
        max_length: int = 5000,
    ) -> WebScrapeResult:
        """
        Fetch web page content and return structured WebScrapeResult DTO.

        Args:
            url: Target web page URL.
            extract_links: If True, parse and return list of page hyperlinks.
            max_length: Character limit for extracted text.

        Returns:
            WebScrapeResult envelope.
        """
        req = WebScrapeRequest(url=url, extract_links=extract_links, max_length=max_length)
        target_url = req.url.strip()

        if not target_url.startswith(("http://", "https://")):
            target_url = "https://" + target_url

        headers = {"User-Agent": self.user_agent}

        try:
            logger.info(f"WebAgent scraping URL: {target_url}")
            response = requests.get(target_url, headers=headers, timeout=self.timeout)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove noise tags (scripts, styles, noscript, nav)
            for element in soup(["script", "style", "noscript", "svg", "header", "footer"]):
                element.decompose()

            # Extract title
            title = ""
            if soup.title and soup.title.string:
                title = soup.title.string.strip()

            # Extract clean body text
            text = soup.get_text(separator="\n")
            clean_lines = [line.strip() for line in text.splitlines() if line.strip()]
            clean_text = "\n".join(clean_lines)[: req.max_length]

            # Extract links if requested
            links: List[Dict[str, str]] = []
            if req.extract_links:
                for a_tag in soup.find_all("a", href=True):
                    raw_href = a_tag.get("href", "")
                    href = (raw_href if isinstance(raw_href, str) else " ".join(raw_href) if isinstance(raw_href, list) else str(raw_href)).strip()
                    link_text = a_tag.get_text().strip()
                    if href and not href.startswith(("#", "javascript:")):
                        full_url = urljoin(target_url, href)
                        links.append({"text": link_text or full_url, "href": full_url})
                        if len(links) >= 50:  # Cap at 50 links
                            break

            logger.info(f"WebAgent successfully scraped '{title}' ({len(clean_text)} chars, {len(links)} links)")
            return WebScrapeResult(
                success=True,
                url=target_url,
                title=title,
                text_content=clean_text,
                links=links,
            )

        except requests.exceptions.RequestException as req_err:
            logger.warning(f"WebAgent request failed for {target_url}: {req_err}")
            return WebScrapeResult(
                success=False,
                url=target_url,
                error=f"HTTP Request failed: {str(req_err)}",
            )
        except Exception as err:
            logger.error(f"WebAgent scraping error for {target_url}: {err}", exc_info=True)
            return WebScrapeResult(
                success=False,
                url=target_url,
                error=f"WebAgent error: {str(err)}",
            )
