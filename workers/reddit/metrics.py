"""
Reddit metrics collection and synchronization
"""
import praw
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging

from reddit.auth import RedditClient
from database.supabase_client import db

logger = logging.getLogger(__name__)


class MetricsManager:
    """Manages collection and synchronization of Reddit metrics"""

    def __init__(self, reddit_client: RedditClient):
        """
        Initialize MetricsManager with a Reddit client

        Args:
            reddit_client: Authenticated RedditClient instance
        """
        self.client = reddit_client
        self.reddit = reddit_client.reddit

    def get_post_metrics(self, reddit_post_id: str) -> Optional[Dict]:
        """
        Get current metrics for a Reddit post

        Args:
            reddit_post_id: Reddit submission ID

        Returns:
            Dict with metrics or None on error
        """
        try:
            submission = self.reddit.submission(id=reddit_post_id)

            # Force refresh the data
            submission._fetch()

            return {
                "upvotes": submission.score,
                "upvote_ratio": submission.upvote_ratio,
                "comments_count": submission.num_comments,
                "is_removed": submission.removed_by_category is not None,
                "is_locked": submission.locked,
                "is_archived": submission.archived,
            }
        except praw.exceptions.PRAWException as e:
            logger.error(f"Error fetching metrics for post {reddit_post_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching metrics for post {reddit_post_id}: {e}")
            return None

    def get_comment_metrics(self, reddit_comment_id: str) -> Optional[Dict]:
        """
        Get current metrics for a Reddit comment

        Args:
            reddit_comment_id: Reddit comment ID

        Returns:
            Dict with metrics or None on error
        """
        try:
            comment = self.reddit.comment(id=reddit_comment_id)

            # Force refresh the data
            comment._fetch()

            return {
                "upvotes": comment.score,
                "is_removed": comment.body == "[removed]",
                "is_deleted": comment.body == "[deleted]",
            }
        except Exception as e:
            logger.error(f"Error fetching metrics for comment {reddit_comment_id}: {e}")
            return None

    def sync_post_metrics(self, post: Dict) -> bool:
        """
        Sync metrics for a single post

        Args:
            post: Post record from database

        Returns:
            True if successful
        """
        reddit_post_id = post.get("reddit_post_id")
        if not reddit_post_id:
            return False

        metrics = self.get_post_metrics(reddit_post_id)
        if not metrics:
            return False

        # Update the post record
        update_data = {
            "upvotes": metrics["upvotes"],
            "upvote_ratio": metrics["upvote_ratio"],
            "comments_count": metrics["comments_count"],
            "metrics_updated_at": datetime.utcnow().isoformat(),
        }

        # If removed, update status
        if metrics["is_removed"]:
            update_data["status"] = "removed"

        db.update_post(post["id"], update_data)

        logger.debug(
            f"Updated metrics for post {post['id']}: "
            f"upvotes={metrics['upvotes']}, comments={metrics['comments_count']}"
        )

        return True

    def sync_reply_metrics(self, reply: Dict) -> bool:
        """
        Sync metrics for a single reply

        Args:
            reply: Reply record from database

        Returns:
            True if successful
        """
        reddit_comment_id = reply.get("reddit_comment_id")
        if not reddit_comment_id:
            return False

        metrics = self.get_comment_metrics(reddit_comment_id)
        if not metrics:
            return False

        # Update the reply record
        update_data = {
            "upvotes": metrics["upvotes"],
            "metrics_updated_at": datetime.utcnow().isoformat(),
        }

        # If removed, update status
        if metrics["is_removed"] or metrics["is_deleted"]:
            update_data["status"] = "removed"

        db.update_reply(reply["id"], update_data)

        logger.debug(f"Updated metrics for reply {reply['id']}: upvotes={metrics['upvotes']}")

        return True


def sync_all_metrics(since_days: int = 30) -> Dict:
    """
    Sync metrics for all posts and replies from the last N days

    Args:
        since_days: Number of days to look back

    Returns:
        Summary of sync results
    """
    results = {
        "posts_processed": 0,
        "posts_updated": 0,
        "replies_processed": 0,
        "replies_updated": 0,
        "errors": [],
        "daily_metrics_updated": 0,
    }

    logger.info(f"Starting metrics sync for last {since_days} days")

    # Get posts to update
    posts = db.get_posts_for_metrics_update(since_days=since_days)

    logger.info(f"Found {len(posts)} posts to update")

    # Group posts by client to use appropriate accounts
    posts_by_client: Dict[str, List[Dict]] = {}
    for post in posts:
        client_id = post.get("client_id")
        if client_id:
            if client_id not in posts_by_client:
                posts_by_client[client_id] = []
            posts_by_client[client_id].append(post)

    # Process each client's posts
    for client_id, client_posts in posts_by_client.items():
        reddit_client = RedditClient.get_available_for_client(client_id)
        if not reddit_client:
            # Try to get any active account for the org
            client = db.get_client(client_id)
            if client:
                accounts = db.get_accounts_for_organization(client.get("organization_id"))
                for account in accounts:
                    if account.get("status") == "active":
                        try:
                            reddit_client = RedditClient(account)
                            break
                        except Exception:
                            continue

        if not reddit_client:
            logger.warning(f"No available account to sync metrics for client {client_id}")
            results["errors"].append({
                "client_id": client_id,
                "error": "No available account",
            })
            continue

        manager = MetricsManager(reddit_client)

        for post in client_posts:
            results["posts_processed"] += 1
            try:
                if manager.sync_post_metrics(post):
                    results["posts_updated"] += 1
            except Exception as e:
                results["errors"].append({
                    "post_id": post["id"],
                    "error": str(e),
                })

    # Sync reply metrics
    # Get all clients with activity in the time period
    clients = db.get_active_clients()

    for client in clients:
        client_id = client["id"]
        replies = db.get_replies_for_client(client_id, limit=100)

        # Filter to recent replies
        cutoff = datetime.utcnow() - timedelta(days=since_days)
        recent_replies = [
            r for r in replies
            if r.get("posted_at") and
            datetime.fromisoformat(r["posted_at"].replace("Z", "+00:00")).replace(tzinfo=None) > cutoff
        ]

        if not recent_replies:
            continue

        reddit_client = RedditClient.get_available_for_client(client_id)
        if not reddit_client:
            continue

        manager = MetricsManager(reddit_client)

        for reply in recent_replies:
            results["replies_processed"] += 1
            try:
                if manager.sync_reply_metrics(reply):
                    results["replies_updated"] += 1
            except Exception as e:
                results["errors"].append({
                    "reply_id": reply["id"],
                    "error": str(e),
                })

    # Update daily metrics aggregates
    results["daily_metrics_updated"] = _compute_daily_metrics()

    logger.info(
        f"Metrics sync complete: "
        f"{results['posts_updated']}/{results['posts_processed']} posts, "
        f"{results['replies_updated']}/{results['replies_processed']} replies, "
        f"{len(results['errors'])} errors"
    )

    return results


def _compute_daily_metrics() -> int:
    """
    Compute and store daily metrics aggregates for all clients

    Returns:
        Number of daily metric records updated
    """
    today = datetime.utcnow().date()
    updated = 0

    clients = db.get_active_clients()

    for client in clients:
        client_id = client["id"]

        # Get today's posts
        posts = db.get_posts_for_client(client_id, status="posted", limit=100)
        today_posts = [
            p for p in posts
            if p.get("posted_at") and
            datetime.fromisoformat(p["posted_at"].replace("Z", "+00:00")).date() == today
        ]

        # Get today's replies
        replies = db.get_replies_for_client(client_id, limit=100)
        today_replies = [
            r for r in replies
            if r.get("posted_at") and
            datetime.fromisoformat(r["posted_at"].replace("Z", "+00:00")).date() == today
        ]

        # Get today's mentions
        mentions = db.get_mentions_for_client(client_id, limit=100)
        today_mentions = [
            m for m in mentions
            if m.get("detected_at") and
            datetime.fromisoformat(m["detected_at"].replace("Z", "+00:00")).date() == today
        ]

        # Calculate metrics
        metrics = {
            "posts_count": len(today_posts),
            "replies_count": len(today_replies),
            "mentions_found": len(today_mentions),
            "mentions_replied": len([m for m in today_mentions if m.get("replied")]),
            "total_upvotes": sum(p.get("upvotes", 0) for p in today_posts),
            "total_comments": sum(p.get("comments_count", 0) for p in today_posts),
        }

        # Get karma gained (would need yesterday's karma to calculate properly)
        # For now, just track active accounts
        accounts = db.get_active_accounts_for_client(client_id)
        metrics["accounts_active"] = len(accounts)

        # Upsert daily metrics
        try:
            db.upsert_daily_metrics(client_id, today.isoformat(), metrics)
            updated += 1
        except Exception as e:
            logger.error(f"Error updating daily metrics for client {client_id}: {e}")

    return updated


def get_client_stats(client_id: str, days: int = 30) -> Dict:
    """
    Get comprehensive stats for a client

    Args:
        client_id: Client UUID
        days: Number of days to include

    Returns:
        Dict with comprehensive stats
    """
    # Get aggregate metrics
    metrics = db.get_aggregate_metrics(client_id, days)

    # Get daily metrics for chart data
    daily = db.get_metrics_for_client(client_id, days)

    # Get account info
    accounts = db.get_active_accounts_for_client(client_id)
    total_karma = sum(a.get("karma", 0) for a in accounts)

    # Get subreddit performance
    subreddits = db.get_subreddits_for_client(client_id)
    top_subreddits = sorted(
        subreddits,
        key=lambda s: s.get("avg_upvotes", 0),
        reverse=True
    )[:5]

    # Get recent activity
    activity = db.get_activity_log(client_id=client_id, limit=20)

    return {
        "period_days": days,
        "summary": {
            **metrics,
            "total_karma": total_karma,
            "active_accounts": len(accounts),
            "active_subreddits": len([s for s in subreddits if s.get("is_active")]),
        },
        "daily_metrics": daily,
        "top_subreddits": [
            {
                "name": s.get("name"),
                "avg_upvotes": s.get("avg_upvotes"),
                "posts_count": s.get("posts_count"),
            }
            for s in top_subreddits
        ],
        "recent_activity": activity,
    }
