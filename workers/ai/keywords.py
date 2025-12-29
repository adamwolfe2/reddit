"""
AI-powered keyword generation and subreddit discovery
"""
import anthropic
from typing import Dict, List
import json
import logging

from workers.config import config

logger = logging.getLogger(__name__)


class KeywordGenerator:
    """Generates keywords for Reddit monitoring using Claude"""

    def __init__(self):
        """Initialize KeywordGenerator with Anthropic client"""
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = config.ANTHROPIC_MODEL

    def generate_keywords(
        self,
        product_name: str,
        product_description: str,
        target_audience: str,
        competitors: List[str] = None,
    ) -> List[Dict]:
        """
        Generate keywords for Reddit monitoring

        Args:
            product_name: Name of the product
            product_description: Description of what it does
            target_audience: Who the product is for
            competitors: List of competitor names

        Returns:
            List of keyword dicts with keyword, type, and priority
        """
        system = """You are an expert at identifying keywords and phrases that people use when
discussing products, problems, and solutions on Reddit.

Your goal is to generate keywords that will help find:
1. People actively asking about problems the product solves
2. People looking for product recommendations in this space
3. Discussions about competitors where our product could be relevant
4. Industry/niche discussions where the product would add value
5. Questions that could be genuinely answered with product knowledge

KEYWORD TYPES:
- product: Direct product name variations and misspellings
- competitor: Competitor names and "X alternative" phrases
- industry: Industry terms and general category discussions
- problem: Pain points and problems the product solves
- solution: "Looking for", "recommendation", "best X for Y" type phrases

Output valid JSON array only, no markdown formatting."""

        competitors_text = ", ".join(competitors) if competitors else "Unknown"

        user = f"""Generate Reddit monitoring keywords for:

PRODUCT: {product_name}
DESCRIPTION: {product_description}
TARGET AUDIENCE: {target_audience}
COMPETITORS: {competitors_text}

Return a JSON array with objects containing:
- keyword: the keyword or phrase (case-insensitive matching)
- type: one of [product, competitor, industry, problem, solution]
- priority: 1-10 (10 being highest priority - most likely to find hot leads)

Guidelines:
- Include 5-8 product keywords (name variations, misspellings)
- Include 3-5 keywords per competitor
- Include 8-12 problem/solution keywords (these often have highest conversion)
- Include 5-8 industry keywords
- Total should be 25-40 diverse keywords

Return JSON array only."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )

            response = message.content[0].text.strip()

            # Clean and parse JSON
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            keywords = json.loads(response)

            # Validate and clean
            validated = []
            for kw in keywords:
                if "keyword" in kw and "type" in kw:
                    validated.append(
                        {
                            "keyword": kw["keyword"].strip().lower(),
                            "type": kw.get("type", "industry"),
                            "priority": min(10, max(1, int(kw.get("priority", 5)))),
                        }
                    )

            logger.info(f"Generated {len(validated)} keywords for {product_name}")
            return validated

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse keyword response: {e}")
            # Return basic keywords as fallback
            return [
                {"keyword": product_name.lower(), "type": "product", "priority": 10},
                {
                    "keyword": f"{product_name.lower()} review",
                    "type": "product",
                    "priority": 9,
                },
                {
                    "keyword": f"{product_name.lower()} alternative",
                    "type": "product",
                    "priority": 8,
                },
            ]
        except Exception as e:
            logger.error(f"Error generating keywords: {e}")
            raise


class SubredditDiscovery:
    """Discovers and scores relevant subreddits"""

    def __init__(self):
        """Initialize SubredditDiscovery with Anthropic client"""
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = config.ANTHROPIC_MODEL

    def suggest_subreddits(
        self, product_info: Dict, num_suggestions: int = 20
    ) -> List[Dict]:
        """
        Suggest potentially relevant subreddits based on product info

        Args:
            product_info: Product context
            num_suggestions: Number of subreddits to suggest

        Returns:
            List of subreddit suggestions with name and reasoning
        """
        system = """You are a Reddit expert who knows the major subreddits for every industry and topic.
Suggest subreddits where:
1. The target audience is likely to be active
2. Discussions about the problem space occur
3. Product recommendations are welcomed or tolerated
4. The community is active and engaged

Output valid JSON array only."""

        product_name = product_info.get("name", "Unknown")
        product_desc = product_info.get("description", "")
        target_audience = product_info.get("target_audience", "")
        use_cases = product_info.get("use_cases", [])

        user = f"""Suggest {num_suggestions} subreddits for:

PRODUCT: {product_name}
DESCRIPTION: {product_desc}
TARGET AUDIENCE: {target_audience}
USE CASES: {', '.join(use_cases) if use_cases else 'General'}

Return JSON array with objects containing:
- name: subreddit name (without r/)
- reasoning: why this subreddit is relevant (1 sentence)
- estimated_relevance: 0.0-1.0 score
- category: one of [industry, audience, problem, general, competitor]

Focus on active, relevant subreddits. Include both large and niche communities.
Return JSON array only."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )

            response = message.content[0].text.strip()

            # Clean and parse JSON
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            suggestions = json.loads(response)

            # Validate
            validated = []
            for sub in suggestions:
                if "name" in sub:
                    validated.append(
                        {
                            "name": sub["name"].replace("r/", ""),
                            "reasoning": sub.get("reasoning", ""),
                            "estimated_relevance": float(
                                sub.get("estimated_relevance", 0.5)
                            ),
                            "category": sub.get("category", "general"),
                        }
                    )

            logger.info(f"Suggested {len(validated)} subreddits for {product_name}")
            return validated

        except Exception as e:
            logger.error(f"Error suggesting subreddits: {e}")
            return []

    def score_subreddits(
        self, subreddits: List[Dict], product_info: Dict
    ) -> List[Dict]:
        """
        Score subreddits for relevance to a product

        Args:
            subreddits: List of subreddit dicts with name, description, subscribers
            product_info: Product context

        Returns:
            Subreddits with relevance_score added
        """
        if not subreddits:
            return []

        system = """You are an expert at evaluating subreddit relevance for product marketing.
Score each subreddit from 0.0 to 1.0 based on:
- Relevance to the product/service
- Likelihood of finding potential customers
- Engagement quality (not just size)
- Self-promotion friendliness
- Community receptiveness to recommendations

Output valid JSON array only."""

        subs_text = "\n".join(
            [
                f"- r/{s['name']}: {s.get('description', 'No description')[:200]} ({s.get('subscribers', 0):,} subscribers)"
                for s in subreddits[:30]
            ]
        )

        user = f"""Score these subreddits for:

PRODUCT: {product_info.get('name')}
DESCRIPTION: {product_info.get('description')}
TARGET AUDIENCE: {product_info.get('target_audience')}

SUBREDDITS:
{subs_text}

Return a JSON array with objects containing:
- name: subreddit name
- relevance_score: 0.0-1.0
- reasoning: brief explanation (1 sentence)
- self_promo_friendly: boolean

Return JSON array only."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=3000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )

            response = message.content[0].text.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            scored = json.loads(response)

            # Merge scores back into original subreddits
            score_map = {s["name"].lower(): s for s in scored}

            for sub in subreddits:
                name_lower = sub["name"].lower()
                if name_lower in score_map:
                    sub["relevance_score"] = score_map[name_lower].get(
                        "relevance_score", 0.5
                    )
                    sub["allows_self_promotion"] = score_map[name_lower].get(
                        "self_promo_friendly", True
                    )
                else:
                    sub["relevance_score"] = 0.5

            return subreddits

        except Exception as e:
            logger.error(f"Error scoring subreddits: {e}")
            # Return with default scores
            for sub in subreddits:
                sub["relevance_score"] = 0.5
            return subreddits

    def analyze_subreddit_rules(self, rules_text: str, product_info: Dict) -> Dict:
        """
        Analyze subreddit rules to understand posting guidelines

        Args:
            rules_text: Raw rules text from subreddit
            product_info: Product context

        Returns:
            Analysis of rules
        """
        system = """You are an expert at interpreting Reddit subreddit rules.
Analyze the rules to determine posting guidelines.
Output valid JSON only."""

        user = f"""Analyze these subreddit rules for a product called {product_info.get('name', 'Unknown')}:

RULES:
{rules_text[:3000]}

Return JSON with:
- allows_self_promotion: boolean
- self_promo_restrictions: string (any restrictions on self-promotion)
- minimum_karma: number or null
- minimum_account_age_days: number or null
- required_flair: boolean
- content_restrictions: array of strings (any content restrictions)
- summary: 1-2 sentence summary of key rules

Return JSON only."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                system=system,
                messages=[{"role": "user", "content": user}],
            )

            response = message.content[0].text.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            return json.loads(response)

        except Exception as e:
            logger.error(f"Error analyzing rules: {e}")
            return {
                "allows_self_promotion": True,
                "self_promo_restrictions": "Unknown",
                "minimum_karma": None,
                "minimum_account_age_days": None,
                "required_flair": False,
                "content_restrictions": [],
                "summary": "Could not analyze rules",
            }
