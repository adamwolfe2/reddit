"""
AI content generation using Claude
"""
import anthropic
from typing import Dict, List, Optional
import logging

from workers.config import config

logger = logging.getLogger(__name__)


class ContentGenerator:
    """Generates content using Claude API"""

    def __init__(self):
        """Initialize ContentGenerator with Anthropic client"""
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = config.ANTHROPIC_MODEL

    def _call_claude(
        self, system: str, user: str, max_tokens: int = 1024
    ) -> str:
        """
        Make a call to Claude API

        Args:
            system: System prompt
            user: User message
            max_tokens: Maximum tokens in response

        Returns:
            Response text
        """
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text

    def generate_reply(
        self,
        post_title: str,
        post_content: str,
        subreddit: str,
        existing_comments: List[Dict],
        product_info: Dict,
        tone: str = "professional",
        disclosure: str = "I work on this product",
    ) -> Optional[str]:
        """
        Generate a reply to a Reddit post

        Args:
            post_title: Title of the post
            post_content: Body of the post
            subreddit: Subreddit name
            existing_comments: List of existing comments
            product_info: Dict with product name, description, value_props
            tone: Tone to use (professional, casual, technical, friendly)
            disclosure: Disclosure text to use when mentioning product

        Returns:
            Reply text or None/skip if not appropriate to reply
        """
        # Format existing comments
        comments_text = "\n".join(
            [
                f"- {c['author']}: {c['body'][:200]}..."
                for c in existing_comments[:10]
            ]
        )

        product_name = product_info.get("name", "the product")
        product_desc = product_info.get("description", "")
        value_props = product_info.get("value_props", [])

        system = f"""You are a helpful Reddit user who genuinely contributes to discussions.
Your tone is {tone}. You write like a real person, not a marketer.

CRITICAL RULES:
1. FIRST: Determine if this post is genuinely relevant to {product_name} or the problem it solves
2. If NOT clearly relevant, respond with exactly "skip" (nothing else)
3. If relevant, provide genuine value FIRST - answer questions, share insights, be helpful
4. Only mention the product if it NATURALLY fits the conversation AND adds value
5. If you mention the product, ALWAYS include disclosure: "{disclosure}"
6. Never be pushy, salesy, or promotional
7. Match the subreddit's culture and communication style
8. Keep responses concise (2-4 sentences typically)
9. Don't start with generic greetings like "Hey!" or "Hi there!"
10. If someone is venting or not looking for solutions, don't recommend products

WHEN TO SKIP:
- Post is not related to the problem {product_name} solves
- Post is a rant/vent where people don't want solutions
- Product wouldn't genuinely help the situation
- The post already has good answers covering the same ground
- Mentioning a product would be out of place or unwelcome

PRODUCT INFO:
Name: {product_name}
Description: {product_desc}
Key Benefits: {', '.join(value_props) if value_props else 'Not specified'}
"""

        user = f"""POST IN r/{subreddit}:
Title: {post_title}

Content: {post_content[:2000]}

EXISTING TOP COMMENTS:
{comments_text}

Generate an appropriate, helpful reply that adds value to the discussion.
If this post is not relevant or you shouldn't reply, respond with exactly "skip"."""

        try:
            response = self._call_claude(system, user)

            if response.lower().strip() == "skip":
                logger.debug(f"AI decided to skip reply for r/{subreddit}")
                return None

            return response.strip()
        except Exception as e:
            logger.error(f"Error generating reply: {e}")
            raise

    def generate_warmup_comment(
        self, post_title: str, post_content: str, subreddit: str
    ) -> Optional[str]:
        """
        Generate a safe, generic comment for account warmup

        Args:
            post_title: Title of the post
            post_content: Body of the post (truncated)
            subreddit: Subreddit name

        Returns:
            Comment text or None
        """
        system = """You are a regular Reddit user making casual comments on posts.
Write short, genuine comments that add to the discussion.

RULES:
- NO promotion, NO links, NO marketing whatsoever
- Be friendly, authentic, and conversational
- 1-2 sentences maximum
- Match the vibe of the subreddit
- Add value: ask a question, share an opinion, or relate to the content
- Don't be generic or boring
- Respond with "skip" if you can't think of something genuine and valuable to say"""

        user = f"""POST IN r/{subreddit}:
Title: {post_title}
Content: {post_content[:500]}

Write a brief, genuine comment that would fit naturally in this discussion."""

        try:
            response = self._call_claude(system, user, max_tokens=200)

            if response.lower().strip() == "skip":
                return None

            return response.strip()
        except Exception as e:
            logger.error(f"Error generating warmup comment: {e}")
            return None

    def customize_for_subreddit(
        self,
        content: str,
        subreddit_name: str,
        subreddit_rules: str = None,
        product_info: Dict = None,
    ) -> str:
        """
        Customize content for a specific subreddit

        Args:
            content: Original content
            subreddit_name: Target subreddit
            subreddit_rules: Summary of subreddit rules
            product_info: Product context

        Returns:
            Customized content
        """
        system = """You are an expert at adapting content for different Reddit communities.
Your job is to rewrite content to match the subreddit's culture and rules.

RULES:
- Keep the core message and information intact
- Adjust tone, style, and formatting to match the community
- Ensure compliance with stated subreddit rules
- Do NOT make it more promotional
- Keep it value-first and authentic
- If the content mentions a product, keep any disclosures intact"""

        user = f"""ORIGINAL CONTENT:
{content}

TARGET SUBREDDIT: r/{subreddit_name}
SUBREDDIT RULES: {subreddit_rules or 'Standard Reddit rules apply'}

Rewrite this content to better fit r/{subreddit_name}'s culture and rules.
Only make necessary changes - if it already fits well, minimal changes are fine."""

        try:
            return self._call_claude(system, user).strip()
        except Exception as e:
            logger.error(f"Error customizing content: {e}")
            return content  # Return original on error

    def generate_post_content(
        self,
        topic: str,
        subreddit: str,
        product_info: Dict,
        post_type: str = "value",  # value, story, question, discussion
        include_product_mention: bool = True,
    ) -> Dict:
        """
        Generate a full Reddit post (title + content)

        Args:
            topic: Topic/angle for the post
            subreddit: Target subreddit
            product_info: Product context
            post_type: Type of post to generate
            include_product_mention: Whether to mention the product

        Returns:
            Dict with title and content
        """
        post_type_prompts = {
            "value": "Write an informative, value-packed post that teaches something useful related to the topic.",
            "story": "Write a personal story or case study that's engaging and relatable. Be authentic and share real insights.",
            "question": "Write a thought-provoking question that sparks discussion. Show genuine curiosity.",
            "discussion": "Start a discussion about an interesting topic or trend. Share your perspective and invite others.",
        }

        product_name = product_info.get("name", "Unknown")
        product_desc = product_info.get("description", "")

        mention_instruction = (
            "Naturally weave in a mention of the product if it genuinely adds value. Include disclosure if mentioning."
            if include_product_mention
            else "Do NOT mention any products or services."
        )

        system = f"""You are a Reddit power user who creates engaging, authentic content.
{post_type_prompts.get(post_type, post_type_prompts['value'])}

RULES:
1. Write like a real person, not a marketer or corporate account
2. Provide genuine value to readers
3. {mention_instruction}
4. Match r/{subreddit}'s style, culture, and expectations
5. Keep titles under 300 characters and make them compelling
6. Format content appropriately (paragraphs, bullet points if helpful)
7. Be specific and concrete, not vague and generic
8. End with something that encourages engagement (question, call for opinions, etc.)

PRODUCT INFO:
Name: {product_name}
Description: {product_desc}
"""

        user = f"""Create a {post_type} post for r/{subreddit} about: {topic}

The post should feel natural and valuable to the community.

Respond in this exact format:
TITLE: [Your compelling title here]
---
CONTENT:
[Your post content here]"""

        try:
            response = self._call_claude(system, user, max_tokens=2000)

            # Parse response
            try:
                parts = response.split("---")
                title_part = parts[0].replace("TITLE:", "").strip()
                content_part = (
                    parts[1].replace("CONTENT:", "").strip() if len(parts) > 1 else ""
                )

                return {"title": title_part, "content": content_part}
            except Exception:
                # If parsing fails, return as-is
                return {"title": topic, "content": response}
        except Exception as e:
            logger.error(f"Error generating post content: {e}")
            raise

    def score_post_relevance(
        self, post_title: str, post_content: str, product_info: Dict
    ) -> Dict:
        """
        Score how relevant a post is for potential reply

        Args:
            post_title: Post title
            post_content: Post content
            product_info: Product context

        Returns:
            Dict with score (0-1) and reasoning
        """
        product_name = product_info.get("name", "the product")
        product_desc = product_info.get("description", "")

        system = """You are an expert at evaluating Reddit posts for relevance to a product.
Score posts on a scale of 0.0 to 1.0 based on how relevant and appropriate they are for engagement.

Scoring guidelines:
- 0.0-0.2: Not relevant at all
- 0.3-0.4: Tangentially related but probably shouldn't engage
- 0.5-0.6: Related but engagement might seem forced
- 0.7-0.8: Good opportunity for helpful engagement
- 0.9-1.0: Perfect opportunity - clear need that the product addresses

Output JSON only with keys: score, reasoning, recommended_action (reply/skip)"""

        user = f"""PRODUCT:
Name: {product_name}
Description: {product_desc}

POST:
Title: {post_title}
Content: {post_content[:1500]}

Evaluate this post's relevance for engagement. Return JSON only."""

        try:
            response = self._call_claude(system, user, max_tokens=300)

            # Clean response
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            import json

            return json.loads(response)
        except Exception as e:
            logger.error(f"Error scoring relevance: {e}")
            return {"score": 0.5, "reasoning": "Error scoring", "recommended_action": "skip"}

    def generate_multiple_post_ideas(
        self, product_info: Dict, subreddit: str, count: int = 5
    ) -> List[Dict]:
        """
        Generate multiple post ideas for a subreddit

        Args:
            product_info: Product context
            subreddit: Target subreddit
            count: Number of ideas to generate

        Returns:
            List of post ideas with topic, type, and brief description
        """
        product_name = product_info.get("name", "Unknown")
        product_desc = product_info.get("description", "")
        use_cases = product_info.get("use_cases", [])

        system = f"""You are a Reddit content strategist.
Generate post ideas that would perform well in the subreddit and naturally allow for product discussion.

Each idea should:
- Provide genuine value to the community
- Feel natural and not promotional
- Have high engagement potential
- Allow for authentic product mention (if appropriate)

Output JSON array with objects containing: topic, post_type (value/story/question/discussion), description, include_product_mention (boolean)"""

        user = f"""PRODUCT:
Name: {product_name}
Description: {product_desc}
Use Cases: {', '.join(use_cases) if use_cases else 'General'}

TARGET SUBREDDIT: r/{subreddit}

Generate {count} unique post ideas that would resonate with this community.
Return JSON array only."""

        try:
            response = self._call_claude(system, user, max_tokens=1500)

            # Clean response
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            import json

            return json.loads(response)
        except Exception as e:
            logger.error(f"Error generating post ideas: {e}")
            return []
