"""
Website scraping using Firecrawl
"""
from typing import Dict, Optional, List
import logging
import json

try:
    from firecrawl import FirecrawlApp
    FIRECRAWL_AVAILABLE = True
except ImportError:
    FIRECRAWL_AVAILABLE = False
    FirecrawlApp = None

import anthropic

from workers.config import config

logger = logging.getLogger(__name__)


class WebsiteScraper:
    """Scrapes and extracts information from websites"""

    def __init__(self):
        """Initialize WebsiteScraper with Firecrawl and Anthropic clients"""
        if FIRECRAWL_AVAILABLE and config.FIRECRAWL_API_KEY:
            self.firecrawl = FirecrawlApp(api_key=config.FIRECRAWL_API_KEY)
        else:
            self.firecrawl = None
            logger.warning("Firecrawl not available - using fallback scraping")

        self.anthropic = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def scrape_website(self, url: str) -> Dict:
        """
        Scrape a website and return markdown content

        Args:
            url: Website URL

        Returns:
            Dict with markdown content and metadata
        """
        if not self.firecrawl:
            return {
                "success": False,
                "error": "Firecrawl not configured",
            }

        try:
            result = self.firecrawl.scrape_url(
                url,
                params={
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                },
            )

            return {
                "success": True,
                "markdown": result.get("markdown", ""),
                "metadata": result.get("metadata", {}),
            }
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return {"success": False, "error": str(e)}

    def extract_product_info(self, url: str) -> Dict:
        """
        Scrape a website and extract structured product information

        Args:
            url: Website URL

        Returns:
            Dict with extracted product info
        """
        # First scrape the website
        scrape_result = self.scrape_website(url)

        if not scrape_result["success"]:
            # Return error but try to continue with URL-based extraction
            logger.warning(f"Scrape failed for {url}, using URL-based extraction")
            return self._extract_from_url_only(url)

        content = scrape_result["markdown"]

        # Use Claude to extract structured info
        try:
            message = self.anthropic.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=2000,
                system="""You are an expert at analyzing websites and extracting product/company information.
Extract structured information from the website content.
Output valid JSON only, no markdown formatting.""",
                messages=[
                    {
                        "role": "user",
                        "content": f"""Analyze this website content and extract:

WEBSITE CONTENT:
{content[:12000]}

Return a JSON object with:
- product_name: Name of the main product/service
- product_description: 2-3 sentence description of what it does and who it's for
- value_propositions: Array of 3-5 key value props (benefits, not features)
- target_audience: Who the product is for (be specific)
- use_cases: Array of 3-5 specific use cases
- competitors: Array of likely competitors (if identifiable from content)
- tone: The tone of their marketing (professional/casual/technical/friendly)
- key_features: Array of main features
- pricing_info: Brief description of pricing if available

Return JSON only.""",
                    }
                ],
            )

            response = message.content[0].text.strip()

            # Clean and parse JSON
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            extracted = json.loads(response)
            extracted["website_content"] = content
            extracted["success"] = True
            extracted["url"] = url

            logger.info(f"Successfully extracted product info from {url}")
            return extracted

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse extracted JSON: {e}")
            return {
                "success": False,
                "error": "Failed to parse extracted information",
                "website_content": content,
            }
        except Exception as e:
            logger.error(f"Error extracting product info: {e}")
            return {"success": False, "error": str(e)}

    def _extract_from_url_only(self, url: str) -> Dict:
        """
        Fallback extraction when scraping fails - extract info from URL/domain

        Args:
            url: Website URL

        Returns:
            Basic extracted info
        """
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")

            # Try to extract product name from domain
            product_name = domain.split(".")[0].replace("-", " ").title()

            return {
                "success": True,
                "product_name": product_name,
                "product_description": f"Product from {domain}",
                "value_propositions": [],
                "target_audience": "Unknown",
                "use_cases": [],
                "competitors": [],
                "tone": "professional",
                "url": url,
                "note": "Limited extraction - scraping failed",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def crawl_website(self, url: str, max_pages: int = 10) -> Dict:
        """
        Crawl multiple pages of a website

        Args:
            url: Starting URL
            max_pages: Maximum pages to crawl

        Returns:
            Dict with crawl results
        """
        if not self.firecrawl:
            return {
                "success": False,
                "error": "Firecrawl not configured",
            }

        try:
            crawl_result = self.firecrawl.crawl_url(
                url,
                params={
                    "limit": max_pages,
                    "scrapeOptions": {"formats": ["markdown"]},
                },
                poll_interval=5,
            )

            pages = crawl_result.get("data", [])

            return {
                "success": True,
                "pages": pages,
                "total": len(pages),
                "urls": [p.get("metadata", {}).get("url", "") for p in pages],
            }
        except Exception as e:
            logger.error(f"Error crawling {url}: {e}")
            return {"success": False, "error": str(e)}

    def extract_with_schema(
        self, url: str, schema: Dict
    ) -> Dict:
        """
        Extract structured data using a specific schema

        Args:
            url: Website URL
            schema: JSON schema for extraction

        Returns:
            Extracted data matching schema
        """
        if not self.firecrawl:
            return {
                "success": False,
                "error": "Firecrawl not configured",
            }

        try:
            result = self.firecrawl.scrape_url(
                url,
                params={
                    "formats": ["extract"],
                    "extract": {"schema": schema},
                },
            )

            return {
                "success": True,
                "data": result.get("extract", {}),
                "metadata": result.get("metadata", {}),
            }
        except Exception as e:
            logger.error(f"Error extracting with schema from {url}: {e}")
            return {"success": False, "error": str(e)}

    def get_pricing_info(self, url: str) -> Dict:
        """
        Attempt to find and extract pricing information

        Args:
            url: Website URL (typically pricing page)

        Returns:
            Pricing information
        """
        scrape_result = self.scrape_website(url)

        if not scrape_result["success"]:
            return scrape_result

        content = scrape_result["markdown"]

        try:
            message = self.anthropic.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=1000,
                system="""Extract pricing information from website content.
Output valid JSON only.""",
                messages=[
                    {
                        "role": "user",
                        "content": f"""Extract pricing information from:

{content[:8000]}

Return JSON with:
- has_pricing: boolean
- pricing_model: free/freemium/paid/enterprise/custom
- tiers: array of objects with name, price, features
- notes: any relevant pricing notes

Return JSON only.""",
                    }
                ],
            )

            response = message.content[0].text.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            pricing = json.loads(response)
            pricing["success"] = True
            return pricing

        except Exception as e:
            logger.error(f"Error extracting pricing: {e}")
            return {"success": False, "error": str(e)}

    def analyze_competitors_page(self, url: str, product_info: Dict) -> List[Dict]:
        """
        Analyze a competitors/alternatives page to extract competitor info

        Args:
            url: URL of competitors page
            product_info: Our product context

        Returns:
            List of competitor information
        """
        scrape_result = self.scrape_website(url)

        if not scrape_result["success"]:
            return []

        content = scrape_result["markdown"]

        try:
            message = self.anthropic.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=2000,
                system="""Extract competitor information from comparison/alternatives pages.
Output valid JSON array only.""",
                messages=[
                    {
                        "role": "user",
                        "content": f"""Extract competitor info for {product_info.get('name', 'this product')} from:

{content[:10000]}

Return JSON array with objects containing:
- name: competitor name
- description: what they do
- differentiators: how they differ from our product
- pricing: if mentioned
- target_audience: who they target

Return JSON array only.""",
                    }
                ],
            )

            response = message.content[0].text.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            return json.loads(response)

        except Exception as e:
            logger.error(f"Error analyzing competitors page: {e}")
            return []
