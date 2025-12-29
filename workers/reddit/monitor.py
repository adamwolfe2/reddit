"""
Reddit Keyword Monitoring System
In-house replacement for F5Bot - monitors Reddit for keyword mentions
"""
import praw
from prawcore.exceptions import PrawcoreException
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging
import asyncio
import re

logger = logging.getLogger(__name__)


@dataclass
class MentionResult:
    """Represents a detected mention"""
    reddit_post_id: str
    reddit_url: str
    subreddit: str
    title: str
    content: str
    author: str
    post_type: str  # 'submission' or 'comment'
    created_utc: datetime
    score: int
    num_comments: int
    matched_keywords: List[str]
    parent_post_id: Optional[str] = None  # For comments
    parent_title: Optional[str] = None  # For comments


class RedditMonitor:
    """
    Monitors Reddit for keyword mentions across subreddits.
    Designed to be a robust, in-house alternative to F5Bot.
    """

    def __init__(self):
        self._reddit: Optional[praw.Reddit] = None
        self._db = None

    @property
    def db(self):
        """Lazy load database client"""
        if self._db is None:
            from database.supabase_client import db
            self._db = db
        return self._db

    def _get_reddit_client(self) -> praw.Reddit:
        """Get a Reddit client for searching (read-only operations)"""
        if self._reddit is None:
            from config import config
            # Use app-only auth for search (no user context needed)
            # This requires at least one account's credentials
            accounts = self.db.get_accounts_for_warmup()
            if not accounts:
                # Try to get any active account
                from database.supabase_client import db
                result = db.client.table("reddit_accounts").select("*").limit(1).execute()
                accounts = result.data if result.data else []

            if not accounts:
                raise ValueError("No Reddit accounts configured for monitoring")

            account = accounts[0]

            # Decrypt password
            from utils.encryption import decrypt_password
            password = decrypt_password(account["password_encrypted"])

            self._reddit = praw.Reddit(
                client_id=account["reddit_client_id"],
                client_secret=account["reddit_client_secret"],
                user_agent=account.get("user_agent", "RedditGrowthEngine/1.0"),
                username=account["username"],
                password=password,
            )
        return self._reddit

    async def scan_for_keywords(
        self,
        client_id: str,
        limit_per_keyword: int = 25,
        time_filter: str = "day",
        include_comments: bool = True,
    ) -> Dict[str, Any]:
        """
        Scan Reddit for all active keywords for a client.

        Args:
            client_id: The client to scan keywords for
            limit_per_keyword: Max results per keyword search
            time_filter: 'hour', 'day', 'week', 'month', 'year', 'all'
            include_comments: Whether to also search comments

        Returns:
            Summary of scan results
        """
        # Get client info
        client = self.db.get_client(client_id)
        if not client:
            raise ValueError(f"Client {client_id} not found")

        # Get active keywords for this client
        keywords = self.db.get_keywords_for_client(client_id, active_only=True)
        if not keywords:
            logger.info(f"No active keywords for client {client_id}")
            return {
                "client_id": client_id,
                "keywords_scanned": 0,
                "mentions_found": 0,
                "mentions_new": 0,
                "mentions_duplicate": 0,
            }

        logger.info(f"Scanning {len(keywords)} keywords for client {client_id}")

        # Get target subreddits (if any configured)
        target_subreddits = self.db.get_subreddits_for_client(client_id, active_only=True)
        subreddit_names = [s["name"] for s in target_subreddits] if target_subreddits else None

        all_mentions: List[MentionResult] = []
        keywords_scanned = 0

        for keyword_record in keywords:
            keyword = keyword_record["keyword"]
            keyword_id = keyword_record["id"]

            try:
                mentions = await self._search_keyword(
                    keyword=keyword,
                    limit=limit_per_keyword,
                    time_filter=time_filter,
                    subreddits=subreddit_names,
                    include_comments=include_comments,
                )

                # Tag mentions with keyword info
                for mention in mentions:
                    mention.matched_keywords = [keyword]

                all_mentions.extend(mentions)
                keywords_scanned += 1

                # Update keyword last scanned timestamp
                self.db.update_keyword(keyword_id, {
                    "last_scanned_at": datetime.utcnow().isoformat()
                })

                logger.info(f"Keyword '{keyword}' found {len(mentions)} mentions")

                # Small delay to respect rate limits
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Error scanning keyword '{keyword}': {e}")
                continue

        # Deduplicate mentions (same post might match multiple keywords)
        unique_mentions = self._deduplicate_mentions(all_mentions)

        # Save new mentions to database
        new_count, duplicate_count = await self._save_mentions(
            client_id=client_id,
            organization_id=client["organization_id"],
            mentions=unique_mentions,
        )

        # Log activity
        self.db.log_activity(
            activity_type="keyword_scan_completed",
            client_id=client_id,
            organization_id=client["organization_id"],
            details={
                "keywords_scanned": keywords_scanned,
                "mentions_found": len(unique_mentions),
                "mentions_new": new_count,
                "mentions_duplicate": duplicate_count,
            }
        )

        return {
            "client_id": client_id,
            "keywords_scanned": keywords_scanned,
            "mentions_found": len(unique_mentions),
            "mentions_new": new_count,
            "mentions_duplicate": duplicate_count,
            "scan_time": datetime.utcnow().isoformat(),
        }

    async def _search_keyword(
        self,
        keyword: str,
        limit: int = 25,
        time_filter: str = "day",
        subreddits: Optional[List[str]] = None,
        include_comments: bool = True,
    ) -> List[MentionResult]:
        """
        Search Reddit for a specific keyword.
        """
        reddit = self._get_reddit_client()
        mentions = []

        # Build subreddit target
        if subreddits:
            subreddit_target = reddit.subreddit("+".join(subreddits))
        else:
            subreddit_target = reddit.subreddit("all")

        # Search submissions
        try:
            for submission in subreddit_target.search(
                keyword,
                sort="new",
                time_filter=time_filter,
                limit=limit,
            ):
                # Check if keyword is in title or selftext
                title_lower = submission.title.lower()
                selftext_lower = (submission.selftext or "").lower()
                keyword_lower = keyword.lower()

                if keyword_lower in title_lower or keyword_lower in selftext_lower:
                    mentions.append(MentionResult(
                        reddit_post_id=submission.id,
                        reddit_url=f"https://reddit.com{submission.permalink}",
                        subreddit=submission.subreddit.display_name,
                        title=submission.title,
                        content=submission.selftext or "",
                        author=str(submission.author) if submission.author else "[deleted]",
                        post_type="submission",
                        created_utc=datetime.utcfromtimestamp(submission.created_utc),
                        score=submission.score,
                        num_comments=submission.num_comments,
                        matched_keywords=[keyword],
                    ))
        except PrawcoreException as e:
            logger.error(f"Error searching submissions for '{keyword}': {e}")

        # Search comments if enabled
        if include_comments:
            try:
                # Use Reddit's comment search via pushshift alternative or subreddit comments
                # Note: Reddit's native search doesn't search comments well,
                # so we search recent comments in target subreddits
                for comment in subreddit_target.comments(limit=min(limit * 4, 100)):
                    if keyword.lower() in comment.body.lower():
                        # Get parent submission info
                        submission = comment.submission
                        mentions.append(MentionResult(
                            reddit_post_id=comment.id,
                            reddit_url=f"https://reddit.com{comment.permalink}",
                            subreddit=comment.subreddit.display_name,
                            title=f"Comment in: {submission.title[:100]}",
                            content=comment.body,
                            author=str(comment.author) if comment.author else "[deleted]",
                            post_type="comment",
                            created_utc=datetime.utcfromtimestamp(comment.created_utc),
                            score=comment.score,
                            num_comments=0,
                            matched_keywords=[keyword],
                            parent_post_id=submission.id,
                            parent_title=submission.title,
                        ))
            except PrawcoreException as e:
                logger.error(f"Error searching comments for '{keyword}': {e}")

        return mentions

    def _deduplicate_mentions(self, mentions: List[MentionResult]) -> List[MentionResult]:
        """
        Deduplicate mentions, merging matched keywords for same posts.
        """
        seen: Dict[str, MentionResult] = {}

        for mention in mentions:
            if mention.reddit_post_id in seen:
                # Merge keywords
                existing = seen[mention.reddit_post_id]
                for kw in mention.matched_keywords:
                    if kw not in existing.matched_keywords:
                        existing.matched_keywords.append(kw)
            else:
                seen[mention.reddit_post_id] = mention

        return list(seen.values())

    async def _save_mentions(
        self,
        client_id: str,
        organization_id: str,
        mentions: List[MentionResult],
    ) -> tuple[int, int]:
        """
        Save mentions to database, skipping duplicates.
        Returns (new_count, duplicate_count)
        """
        new_count = 0
        duplicate_count = 0

        for mention in mentions:
            # Check if already exists
            if self.db.mention_exists(client_id, mention.reddit_post_id):
                duplicate_count += 1
                continue

            # Score the mention for relevance
            try:
                from ai.scoring import RelevanceScorer
                scorer = RelevanceScorer()
                score_result = await scorer.score_mention(
                    title=mention.title,
                    content=mention.content,
                    subreddit=mention.subreddit,
                    client_id=client_id,
                )
                relevance_score = score_result.get("relevance_score", 0.5)
                should_reply = score_result.get("should_reply", False)
                sentiment = score_result.get("sentiment", "neutral")
            except Exception as e:
                logger.warning(f"Scoring failed for mention {mention.reddit_post_id}: {e}")
                relevance_score = 0.5
                should_reply = False
                sentiment = "neutral"

            # Find matching keyword record to link
            keywords = self.db.get_keywords_for_client(client_id)
            keyword_id = None
            for kw in keywords:
                if kw["keyword"] in mention.matched_keywords:
                    keyword_id = kw["id"]
                    # Increment mention count
                    self.db.increment_keyword_mention(keyword_id)
                    break

            # Save to database
            try:
                self.db.create_mention({
                    "client_id": client_id,
                    "organization_id": organization_id,
                    "keyword_id": keyword_id,
                    "reddit_post_id": mention.reddit_post_id,
                    "reddit_url": mention.reddit_url,
                    "subreddit": mention.subreddit,
                    "post_title": mention.title,
                    "post_content": mention.content[:10000],  # Limit content length
                    "post_author": mention.author,
                    "post_type": mention.post_type,
                    "post_score": mention.score,
                    "post_comments": mention.num_comments,
                    "detected_at": datetime.utcnow().isoformat(),
                    "relevance_score": relevance_score,
                    "sentiment": sentiment,
                    "should_reply": should_reply,
                    "replied": False,
                    "matched_keywords": mention.matched_keywords,
                })
                new_count += 1

            except Exception as e:
                logger.error(f"Error saving mention {mention.reddit_post_id}: {e}")
                continue

        return new_count, duplicate_count

    async def scan_all_clients(
        self,
        limit_per_keyword: int = 25,
        time_filter: str = "day",
    ) -> Dict[str, Any]:
        """
        Scan keywords for all active clients.
        Called by N8N on a schedule.
        """
        # Get all active clients
        result = self.db.client.table("clients").select("*").eq("status", "active").execute()
        clients = result.data if result.data else []

        if not clients:
            logger.info("No active clients to scan")
            return {
                "clients_scanned": 0,
                "total_mentions_found": 0,
                "total_new_mentions": 0,
            }

        total_found = 0
        total_new = 0
        client_results = []

        for client in clients:
            try:
                result = await self.scan_for_keywords(
                    client_id=client["id"],
                    limit_per_keyword=limit_per_keyword,
                    time_filter=time_filter,
                )
                total_found += result["mentions_found"]
                total_new += result["mentions_new"]
                client_results.append({
                    "client_id": client["id"],
                    "client_name": client["name"],
                    **result,
                })
            except Exception as e:
                logger.error(f"Error scanning client {client['id']}: {e}")
                client_results.append({
                    "client_id": client["id"],
                    "client_name": client["name"],
                    "error": str(e),
                })

        return {
            "clients_scanned": len(clients),
            "total_mentions_found": total_found,
            "total_new_mentions": total_new,
            "scan_time": datetime.utcnow().isoformat(),
            "client_results": client_results,
        }

    async def search_subreddits_for_opportunities(
        self,
        client_id: str,
        query_templates: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Search for high-intent posts that are opportunities for engagement.
        Uses templates like "looking for", "recommend", "alternative to", etc.
        """
        client = self.db.get_client(client_id)
        if not client:
            raise ValueError(f"Client {client_id} not found")

        # Default high-intent query templates
        if query_templates is None:
            product_name = client.get("name", "")
            industry = client.get("product_info", {}).get("industry", "")

            query_templates = [
                "looking for recommendation",
                "can anyone recommend",
                "what do you use for",
                "alternative to",
                "best tool for",
                "need help with",
                "suggestion for",
                f"looking for {industry}" if industry else None,
            ]
            query_templates = [q for q in query_templates if q]

        reddit = self._get_reddit_client()
        opportunities = []

        # Get target subreddits
        target_subreddits = self.db.get_subreddits_for_client(client_id, active_only=True)

        if target_subreddits:
            subreddit_target = reddit.subreddit("+".join([s["name"] for s in target_subreddits]))
        else:
            subreddit_target = reddit.subreddit("all")

        for query in query_templates:
            try:
                for submission in subreddit_target.search(
                    query,
                    sort="new",
                    time_filter="week",
                    limit=limit // len(query_templates),
                ):
                    # Skip if already replied or too old
                    post_age = datetime.utcnow() - datetime.utcfromtimestamp(submission.created_utc)
                    if post_age > timedelta(days=3):
                        continue

                    opportunities.append({
                        "reddit_post_id": submission.id,
                        "reddit_url": f"https://reddit.com{submission.permalink}",
                        "subreddit": submission.subreddit.display_name,
                        "title": submission.title,
                        "content": submission.selftext[:500] if submission.selftext else "",
                        "author": str(submission.author) if submission.author else "[deleted]",
                        "score": submission.score,
                        "num_comments": submission.num_comments,
                        "created_utc": datetime.utcfromtimestamp(submission.created_utc).isoformat(),
                        "matched_query": query,
                        "post_age_hours": post_age.total_seconds() / 3600,
                    })

                await asyncio.sleep(0.5)  # Rate limit

            except Exception as e:
                logger.error(f"Error searching for '{query}': {e}")
                continue

        # Sort by recency and score
        opportunities.sort(key=lambda x: (-x["score"], x["post_age_hours"]))

        return opportunities[:limit]


class SubredditAnalyzer:
    """
    Analyzes subreddits to find the best ones for a client.
    """

    def __init__(self):
        self._reddit: Optional[praw.Reddit] = None
        self._db = None

    @property
    def db(self):
        if self._db is None:
            from database.supabase_client import db
            self._db = db
        return self._db

    def _get_reddit_client(self) -> praw.Reddit:
        """Get Reddit client"""
        if self._reddit is None:
            accounts = self.db.client.table("reddit_accounts").select("*").limit(1).execute()
            if not accounts.data:
                raise ValueError("No Reddit accounts configured")

            account = accounts.data[0]
            from utils.encryption import decrypt_password
            password = decrypt_password(account["password_encrypted"])

            self._reddit = praw.Reddit(
                client_id=account["reddit_client_id"],
                client_secret=account["reddit_client_secret"],
                user_agent=account.get("user_agent", "RedditGrowthEngine/1.0"),
                username=account["username"],
                password=password,
            )
        return self._reddit

    async def analyze_subreddit(self, subreddit_name: str) -> Dict[str, Any]:
        """
        Analyze a subreddit's characteristics for marketing suitability.
        """
        reddit = self._get_reddit_client()

        try:
            subreddit = reddit.subreddit(subreddit_name)

            # Get basic info
            info = {
                "name": subreddit.display_name,
                "title": subreddit.title,
                "description": subreddit.public_description[:500] if subreddit.public_description else "",
                "subscribers": subreddit.subscribers,
                "active_users": subreddit.accounts_active or 0,
                "created_utc": datetime.utcfromtimestamp(subreddit.created_utc).isoformat(),
                "over18": subreddit.over18,
                "subreddit_type": subreddit.subreddit_type,
            }

            # Analyze posting rules
            rules = []
            try:
                for rule in subreddit.rules:
                    rules.append({
                        "name": rule.short_name,
                        "description": rule.description[:200] if rule.description else "",
                    })
            except:
                pass
            info["rules"] = rules

            # Check if self-promotion is allowed
            self_promo_keywords = ["self-promotion", "self promotion", "spam", "advertising", "promotional"]
            rules_text = " ".join([r.get("description", "") for r in rules]).lower()
            info["self_promotion_restricted"] = any(kw in rules_text for kw in self_promo_keywords)

            # Analyze recent posts
            recent_posts = []
            for post in subreddit.new(limit=20):
                recent_posts.append({
                    "score": post.score,
                    "num_comments": post.num_comments,
                    "post_type": "link" if post.is_self == False else "text",
                })

            if recent_posts:
                info["avg_post_score"] = sum(p["score"] for p in recent_posts) / len(recent_posts)
                info["avg_comments"] = sum(p["num_comments"] for p in recent_posts) / len(recent_posts)
                info["text_post_ratio"] = sum(1 for p in recent_posts if p["post_type"] == "text") / len(recent_posts)

            # Calculate marketing suitability score
            suitability_score = self._calculate_suitability_score(info)
            info["marketing_suitability_score"] = suitability_score

            return info

        except Exception as e:
            logger.error(f"Error analyzing subreddit {subreddit_name}: {e}")
            return {"name": subreddit_name, "error": str(e)}

    def _calculate_suitability_score(self, info: Dict) -> float:
        """Calculate a 0-1 score for marketing suitability"""
        score = 0.5  # Base score

        # Subscriber count (sweet spot: 10k-500k)
        subs = info.get("subscribers", 0)
        if 10000 <= subs <= 500000:
            score += 0.15
        elif 5000 <= subs <= 1000000:
            score += 0.1
        elif subs < 1000:
            score -= 0.1

        # Activity level
        active = info.get("active_users", 0)
        if active > 100:
            score += 0.1

        # Self-promotion restrictions
        if info.get("self_promotion_restricted"):
            score -= 0.15

        # Text posts allowed (better for value content)
        if info.get("text_post_ratio", 0) > 0.3:
            score += 0.1

        # Engagement level
        if info.get("avg_comments", 0) > 10:
            score += 0.1

        # Not NSFW
        if info.get("over18"):
            score -= 0.2

        return max(0.0, min(1.0, score))

    async def find_relevant_subreddits(
        self,
        client_id: str,
        search_terms: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Find relevant subreddits for a client based on their product/industry.
        """
        client = self.db.get_client(client_id)
        if not client:
            raise ValueError(f"Client {client_id} not found")

        # Generate search terms if not provided
        if search_terms is None:
            product_info = client.get("product_info", {})
            search_terms = [
                client.get("name", ""),
                product_info.get("industry", ""),
                product_info.get("category", ""),
            ]
            # Add keywords
            keywords = self.db.get_keywords_for_client(client_id)
            search_terms.extend([k["keyword"] for k in keywords[:5]])
            search_terms = [t for t in search_terms if t]

        reddit = self._get_reddit_client()
        found_subreddits = set()
        results = []

        for term in search_terms:
            try:
                for subreddit in reddit.subreddits.search(term, limit=10):
                    if subreddit.display_name in found_subreddits:
                        continue
                    found_subreddits.add(subreddit.display_name)

                    analysis = await self.analyze_subreddit(subreddit.display_name)
                    if "error" not in analysis:
                        results.append(analysis)

                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error searching subreddits for '{term}': {e}")
                continue

        # Sort by suitability score
        results.sort(key=lambda x: x.get("marketing_suitability_score", 0), reverse=True)

        return results[:limit]


# Singleton instances
monitor = RedditMonitor()
analyzer = SubredditAnalyzer()


# Async wrapper functions for easy calling
async def scan_client_keywords(client_id: str, **kwargs) -> Dict[str, Any]:
    """Scan keywords for a specific client"""
    return await monitor.scan_for_keywords(client_id, **kwargs)


async def scan_all_keywords(**kwargs) -> Dict[str, Any]:
    """Scan keywords for all active clients"""
    return await monitor.scan_all_clients(**kwargs)


async def find_opportunities(client_id: str, **kwargs) -> List[Dict[str, Any]]:
    """Find high-intent posting opportunities"""
    return await monitor.search_subreddits_for_opportunities(client_id, **kwargs)


async def analyze_subreddit(subreddit_name: str) -> Dict[str, Any]:
    """Analyze a subreddit for marketing suitability"""
    return await analyzer.analyze_subreddit(subreddit_name)


async def discover_subreddits(client_id: str, **kwargs) -> List[Dict[str, Any]]:
    """Discover relevant subreddits for a client"""
    return await analyzer.find_relevant_subreddits(client_id, **kwargs)
