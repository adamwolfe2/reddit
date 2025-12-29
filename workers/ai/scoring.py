"""
AI-powered relevance scoring and content analysis
"""
import anthropic
from typing import Dict, List, Optional
import json
import logging

from workers.config import config

logger = logging.getLogger(__name__)


class RelevanceScorer:
    """Scores content relevance and sentiment using Claude"""

    def __init__(self):
        """Initialize RelevanceScorer with Anthropic client"""
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = config.ANTHROPIC_MODEL

    def score_mention(
        self,
        title: str,
        content: str,
        subreddit: str,
        product_info: Dict,
    ) -> Dict:
        """
        Score a mention for relevance and determine if we should reply

        Args:
            title: Post/comment title
            content: Post/comment content
            subreddit: Subreddit name
            product_info: Product context

        Returns:
            Dict with relevance_score, sentiment, should_reply, reasoning
        """
        system = """You are an expert at evaluating Reddit posts for engagement opportunities.
Analyze posts to determine relevance and reply-worthiness.

SCORING CRITERIA:
- Is this person asking about a problem the product solves?
- Are they looking for recommendations in this space?
- Would a reply genuinely help them?
- Is the sentiment receptive to suggestions?
- Is this an appropriate context for product mention?

SENTIMENT TYPES:
- positive: Excited, happy, looking for solutions
- negative: Frustrated, complaining (may or may not want solutions)
- neutral: Just information or discussion
- question: Actively seeking answers/recommendations

Output valid JSON only."""

        product_name = product_info.get("name", "Unknown")
        product_desc = product_info.get("description", "")

        user = f"""Analyze this Reddit post:

SUBREDDIT: r/{subreddit}
TITLE: {title}
CONTENT: {content[:1500]}

PRODUCT CONTEXT:
Name: {product_name}
Description: {product_desc}

Return JSON with:
- relevance_score: 0.0-1.0 (how relevant to our product)
- sentiment: positive/negative/neutral/question
- should_reply: boolean
- urgency: low/medium/high (how time-sensitive)
- reasoning: why we should or shouldn't reply (1-2 sentences)
- suggested_approach: if should_reply is true, brief guidance on reply angle

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

            result = json.loads(response)

            # Validate and ensure required fields
            return {
                "relevance_score": float(result.get("relevance_score", 0.5)),
                "sentiment": result.get("sentiment", "neutral"),
                "should_reply": bool(result.get("should_reply", False)),
                "urgency": result.get("urgency", "low"),
                "reasoning": result.get("reasoning", ""),
                "suggested_approach": result.get("suggested_approach", ""),
            }

        except Exception as e:
            logger.error(f"Error scoring mention: {e}")
            return {
                "relevance_score": 0.5,
                "sentiment": "neutral",
                "should_reply": False,
                "urgency": "low",
                "reasoning": f"Error scoring: {str(e)}",
                "suggested_approach": "",
            }

    def batch_score_mentions(
        self, mentions: List[Dict], product_info: Dict
    ) -> List[Dict]:
        """
        Score multiple mentions efficiently

        Args:
            mentions: List of mention dicts with title, content, subreddit
            product_info: Product context

        Returns:
            Mentions with scores added
        """
        # For small batches, score individually
        if len(mentions) <= 3:
            for mention in mentions:
                score = self.score_mention(
                    title=mention.get("title", ""),
                    content=mention.get("content_preview", ""),
                    subreddit=mention.get("subreddit", ""),
                    product_info=product_info,
                )
                mention.update(score)
            return mentions

        # For larger batches, use batch scoring
        system = """You are an expert at evaluating Reddit posts for engagement.
Analyze multiple posts and score each one.
Output valid JSON array only."""

        product_name = product_info.get("name", "Unknown")
        product_desc = product_info.get("description", "")

        mentions_text = "\n\n".join(
            [
                f"[{i}] r/{m.get('subreddit', 'unknown')}: {m.get('title', '')} - {m.get('content_preview', '')[:200]}"
                for i, m in enumerate(mentions[:10])
            ]
        )

        user = f"""Score these Reddit posts for {product_name} ({product_desc}):

{mentions_text}

For each, return JSON array with objects containing:
- index: the [X] number
- relevance_score: 0.0-1.0
- sentiment: positive/negative/neutral/question
- should_reply: boolean

Return JSON array only."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )

            response = message.content[0].text.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            scores = json.loads(response)

            # Map scores back to mentions
            score_map = {s["index"]: s for s in scores}

            for i, mention in enumerate(mentions[:10]):
                if i in score_map:
                    mention["relevance_score"] = score_map[i].get("relevance_score", 0.5)
                    mention["sentiment"] = score_map[i].get("sentiment", "neutral")
                    mention["should_reply"] = score_map[i].get("should_reply", False)

            return mentions

        except Exception as e:
            logger.error(f"Error batch scoring: {e}")
            return mentions

    def analyze_competitor_mention(
        self,
        title: str,
        content: str,
        competitor_name: str,
        product_info: Dict,
    ) -> Dict:
        """
        Analyze a post mentioning a competitor

        Args:
            title: Post title
            content: Post content
            competitor_name: Name of the competitor mentioned
            product_info: Our product context

        Returns:
            Analysis dict
        """
        system = """You are an expert at analyzing competitor discussions.
Evaluate posts mentioning competitors to find opportunities.
Output valid JSON only."""

        product_name = product_info.get("name", "Unknown")
        product_desc = product_info.get("description", "")

        user = f"""Analyze this post mentioning competitor {competitor_name}:

TITLE: {title}
CONTENT: {content[:1500]}

OUR PRODUCT: {product_name}
DESCRIPTION: {product_desc}

Return JSON with:
- competitor_sentiment: positive/negative/neutral (towards competitor)
- is_comparison_request: boolean (are they comparing options?)
- is_seeking_alternative: boolean
- opportunity_type: none/soft/strong
- recommended_action: skip/monitor/reply
- reasoning: 1-2 sentences

Return JSON only."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=400,
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
            logger.error(f"Error analyzing competitor mention: {e}")
            return {
                "competitor_sentiment": "neutral",
                "is_comparison_request": False,
                "is_seeking_alternative": False,
                "opportunity_type": "none",
                "recommended_action": "skip",
                "reasoning": f"Error analyzing: {str(e)}",
            }

    def score_post_performance(
        self, posts: List[Dict], product_info: Dict
    ) -> Dict:
        """
        Analyze what's working well in our posts

        Args:
            posts: List of posted content with metrics
            product_info: Product context

        Returns:
            Performance analysis
        """
        if not posts:
            return {"error": "No posts to analyze"}

        system = """You are a content performance analyst.
Analyze Reddit posts to identify patterns in what works.
Output valid JSON only."""

        posts_text = "\n".join(
            [
                f"- r/{p.get('subreddit', 'unknown')}: {p.get('title', '')[:100]} (upvotes: {p.get('upvotes', 0)}, comments: {p.get('comments_count', 0)})"
                for p in posts[:20]
            ]
        )

        user = f"""Analyze these posts for {product_info.get('name', 'Unknown')}:

{posts_text}

Return JSON with:
- top_performing_subreddits: array of subreddit names
- best_post_types: array (value/story/question/discussion)
- patterns_that_work: array of observations
- patterns_to_avoid: array of observations
- recommendations: array of actionable suggestions

Return JSON only."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=800,
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
            logger.error(f"Error analyzing post performance: {e}")
            return {"error": str(e)}
