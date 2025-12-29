"""
Reddit posting functionality
"""
import praw
from typing import Dict, Optional, List
from datetime import datetime
import time
import random
import logging

from workers.reddit.auth import RedditClient
from workers.database.supabase_client import db
from workers.ai.content import ContentGenerator

logger = logging.getLogger(__name__)


class PostManager:
    """Manages Reddit post creation and publishing"""

    def __init__(self, reddit_client: RedditClient):
        """
        Initialize PostManager with a Reddit client

        Args:
            reddit_client: Authenticated RedditClient instance
        """
        self.client = reddit_client
        self.reddit = reddit_client.reddit
        self.content_gen = ContentGenerator()

    def submit_post(
        self,
        subreddit_name: str,
        title: str,
        content: str,
        content_type: str = "text",
        link_url: str = None,
        flair_id: str = None,
        flair_text: str = None,
    ) -> Dict:
        """
        Submit a post to a subreddit

        Args:
            subreddit_name: Name of subreddit (without r/)
            title: Post title
            content: Post body (for text posts) or will be ignored for links
            content_type: 'text' or 'link'
            link_url: URL for link posts
            flair_id: Optional flair ID
            flair_text: Optional flair text

        Returns:
            Dict with post info or error
        """
        try:
            subreddit = self.reddit.subreddit(subreddit_name)

            if content_type == "link" and link_url:
                submission = subreddit.submit(
                    title=title,
                    url=link_url,
                    flair_id=flair_id,
                    flair_text=flair_text,
                )
            else:
                submission = subreddit.submit(
                    title=title,
                    selftext=content,
                    flair_id=flair_id,
                    flair_text=flair_text,
                )

            # Record action
            self.client.record_action()

            logger.info(
                f"Successfully posted to r/{subreddit_name}: {submission.id}"
            )

            return {
                "success": True,
                "reddit_post_id": submission.id,
                "reddit_url": f"https://reddit.com{submission.permalink}",
                "reddit_permalink": submission.permalink,
            }

        except praw.exceptions.RedditAPIException as e:
            error_msg = str(e)
            logger.error(f"Reddit API error posting to r/{subreddit_name}: {error_msg}")

            # Handle specific errors
            if "RATELIMIT" in error_msg:
                return {
                    "success": False,
                    "error": "rate_limited",
                    "message": error_msg,
                    "retry": True,
                }
            elif "SUBREDDIT_NOTALLOWED" in error_msg:
                return {
                    "success": False,
                    "error": "not_allowed",
                    "message": f"Cannot post to r/{subreddit_name}",
                    "retry": False,
                }
            elif "SUBREDDIT_NOEXIST" in error_msg:
                return {
                    "success": False,
                    "error": "subreddit_not_found",
                    "message": f"Subreddit r/{subreddit_name} does not exist",
                    "retry": False,
                }
            elif "NO_TEXT" in error_msg or "NO_SELFS" in error_msg:
                return {
                    "success": False,
                    "error": "text_not_allowed",
                    "message": f"Text posts not allowed in r/{subreddit_name}",
                    "retry": False,
                }
            elif "NO_LINKS" in error_msg:
                return {
                    "success": False,
                    "error": "links_not_allowed",
                    "message": f"Link posts not allowed in r/{subreddit_name}",
                    "retry": False,
                }
            else:
                return {
                    "success": False,
                    "error": "api_error",
                    "message": error_msg,
                    "retry": True,
                }
        except Exception as e:
            logger.error(f"Unknown error posting to r/{subreddit_name}: {e}")
            return {
                "success": False,
                "error": "unknown",
                "message": str(e),
                "retry": True,
            }

    def publish_scheduled_post(self, post: Dict) -> Dict:
        """
        Publish a scheduled post from the database

        Args:
            post: Post record from database (with clients and subreddits joined)

        Returns:
            Result dict
        """
        post_id = post["id"]
        client_data = post.get("clients", {})
        subreddit_data = post.get("subreddits", {})

        logger.info(f"Publishing post {post_id} to r/{subreddit_data.get('name')}")

        # Update status to posting
        db.update_post(post_id, {"status": "posting"})

        # Customize content for this subreddit if needed
        final_content = post["content"]
        final_title = post["title"]

        if client_data and subreddit_data:
            try:
                customized = self.content_gen.customize_for_subreddit(
                    content=post["content"],
                    subreddit_name=subreddit_data["name"],
                    subreddit_rules=subreddit_data.get("rules_summary"),
                    product_info={
                        "name": client_data.get("product_name"),
                        "description": client_data.get("product_description"),
                    },
                )
                if customized:
                    final_content = customized
            except Exception as e:
                logger.warning(f"Failed to customize content: {e}")
                # Continue with original content

        # Submit the post
        result = self.submit_post(
            subreddit_name=subreddit_data["name"],
            title=final_title,
            content=final_content,
            content_type=post.get("content_type", "text"),
            link_url=post.get("link_url"),
        )

        if result["success"]:
            # Update post record
            db.update_post(
                post_id,
                {
                    "status": "posted",
                    "account_id": self.client.account_id,
                    "reddit_post_id": result["reddit_post_id"],
                    "reddit_url": result["reddit_url"],
                    "reddit_permalink": result["reddit_permalink"],
                    "posted_at": datetime.utcnow().isoformat(),
                },
            )

            # Update subreddit last posted
            db.update_subreddit(
                subreddit_data["id"],
                {
                    "last_posted_at": datetime.utcnow().isoformat(),
                    "posts_count": subreddit_data.get("posts_count", 0) + 1,
                },
            )

            # Log activity
            db.log_activity(
                activity_type="post_published",
                client_id=post["client_id"],
                account_id=self.client.account_id,
                entity_type="post",
                entity_id=post_id,
                details={
                    "subreddit": subreddit_data["name"],
                    "reddit_post_id": result["reddit_post_id"],
                },
            )

            logger.info(f"Post {post_id} published successfully: {result['reddit_url']}")
        else:
            # Update with error
            db.update_post(
                post_id,
                {
                    "status": "failed",
                    "error_message": result.get("message", "Unknown error"),
                },
            )

            db.log_activity(
                activity_type="post_failed",
                client_id=post["client_id"],
                account_id=self.client.account_id,
                entity_type="post",
                entity_id=post_id,
                details={"error": result.get("message"), "subreddit": subreddit_data["name"]},
            )

            logger.error(f"Post {post_id} failed: {result.get('message')}")

        return result

    def get_post_stats(self, reddit_post_id: str) -> Optional[Dict]:
        """
        Get current stats for a Reddit post

        Args:
            reddit_post_id: Reddit submission ID

        Returns:
            Dict with upvotes, comments, ratio, or None on error
        """
        try:
            submission = self.reddit.submission(id=reddit_post_id)
            return {
                "upvotes": submission.score,
                "upvote_ratio": submission.upvote_ratio,
                "comments_count": submission.num_comments,
                "is_removed": submission.removed_by_category is not None,
            }
        except Exception as e:
            logger.error(f"Error getting stats for post {reddit_post_id}: {e}")
            return None


def process_pending_posts(limit: int = 10) -> Dict:
    """
    Process all pending posts that are due

    Args:
        limit: Maximum number of posts to process

    Returns:
        Summary of processed posts
    """
    pending = db.get_pending_posts(limit=limit)

    results = {
        "processed": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
    }

    logger.info(f"Processing {len(pending)} pending posts")

    # Group posts by client for efficient account usage
    posts_by_client: Dict[str, List[Dict]] = {}
    for post in pending:
        client_id = post["client_id"]
        if client_id not in posts_by_client:
            posts_by_client[client_id] = []
        posts_by_client[client_id].append(post)

    for client_id, client_posts in posts_by_client.items():
        for post in client_posts:
            results["processed"] += 1

            # Get available account for this client
            reddit_client = RedditClient.get_available_for_client(client_id)

            if not reddit_client:
                results["skipped"] += 1
                results["errors"].append(
                    {"post_id": post["id"], "error": "No available account"}
                )
                logger.warning(f"No available account for client {client_id}")
                continue

            # Publish the post
            manager = PostManager(reddit_client)
            result = manager.publish_scheduled_post(post)

            if result["success"]:
                results["success"] += 1
            else:
                results["failed"] += 1
                results["errors"].append(
                    {"post_id": post["id"], "error": result.get("message")}
                )

            # Random delay between posts (5-15 seconds)
            delay = random.uniform(5, 15)
            logger.debug(f"Waiting {delay:.1f}s before next post")
            time.sleep(delay)

    logger.info(
        f"Finished processing posts: {results['success']} success, "
        f"{results['failed']} failed, {results['skipped']} skipped"
    )

    return results


def create_scheduled_post(
    client_id: str,
    subreddit_id: str,
    title: str,
    content: str,
    scheduled_at: str,
    content_type: str = "text",
    link_url: str = None,
    generated_by: str = "manual",
) -> Dict:
    """
    Create a new scheduled post

    Args:
        client_id: Client UUID
        subreddit_id: Subreddit UUID
        title: Post title
        content: Post content
        scheduled_at: ISO timestamp for when to post
        content_type: 'text' or 'link'
        link_url: URL for link posts
        generated_by: 'manual', 'ai', or 'template'

    Returns:
        Created post record
    """
    post_data = {
        "client_id": client_id,
        "subreddit_id": subreddit_id,
        "title": title,
        "content": content,
        "content_type": content_type,
        "link_url": link_url,
        "status": "scheduled",
        "scheduled_at": scheduled_at,
        "generated_by": generated_by,
    }

    post = db.create_post(post_data)

    db.log_activity(
        activity_type="post_scheduled",
        client_id=client_id,
        entity_type="post",
        entity_id=post["id"],
        details={"scheduled_at": scheduled_at},
    )

    logger.info(f"Created scheduled post {post['id']} for {scheduled_at}")

    return post
