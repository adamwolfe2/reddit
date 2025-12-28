"""
Reddit reply/comment functionality
"""
import praw
from typing import Dict, Optional, List
from datetime import datetime
import time
import random
import logging

from reddit.auth import RedditClient
from database.supabase_client import db
from ai.content import ContentGenerator

logger = logging.getLogger(__name__)


class ReplyManager:
    """Manages Reddit replies and comment engagement"""

    def __init__(self, reddit_client: RedditClient):
        """
        Initialize ReplyManager with a Reddit client

        Args:
            reddit_client: Authenticated RedditClient instance
        """
        self.client = reddit_client
        self.reddit = reddit_client.reddit
        self.content_gen = ContentGenerator()

    def get_post_context(self, reddit_url: str, comment_limit: int = 50) -> Dict:
        """
        Get the full context of a Reddit post/comment

        Args:
            reddit_url: URL to the Reddit post or comment
            comment_limit: Maximum comments to fetch

        Returns:
            Dict with post/comment context
        """
        try:
            # Handle both post URLs and comment URLs
            submission = self.reddit.submission(url=reddit_url)
            submission.comment_sort = "best"
            submission.comments.replace_more(limit=0)

            # Get top-level comments
            comments = []
            for comment in submission.comments[:comment_limit]:
                if hasattr(comment, "body"):
                    comments.append(
                        {
                            "id": comment.id,
                            "author": str(comment.author)
                            if comment.author
                            else "[deleted]",
                            "body": comment.body,
                            "score": comment.score,
                            "created_utc": comment.created_utc,
                        }
                    )

            return {
                "success": True,
                "post": {
                    "id": submission.id,
                    "title": submission.title,
                    "selftext": submission.selftext,
                    "author": str(submission.author)
                    if submission.author
                    else "[deleted]",
                    "subreddit": submission.subreddit.display_name,
                    "score": submission.score,
                    "num_comments": submission.num_comments,
                    "created_utc": submission.created_utc,
                    "url": submission.url,
                    "permalink": submission.permalink,
                },
                "comments": comments,
            }

        except Exception as e:
            logger.error(f"Error fetching post context: {e}")
            return {"success": False, "error": str(e)}

    def submit_reply(
        self, parent_id: str, content: str, is_post: bool = True
    ) -> Dict:
        """
        Submit a reply to a post or comment

        Args:
            parent_id: Reddit ID of the post (without t3_) or comment (without t1_)
            content: Reply content
            is_post: True if replying to a post, False if replying to a comment

        Returns:
            Dict with result
        """
        try:
            if is_post:
                # Reply to post
                submission = self.reddit.submission(id=parent_id)
                comment = submission.reply(content)
            else:
                # Reply to comment
                parent_comment = self.reddit.comment(id=parent_id)
                comment = parent_comment.reply(content)

            # Record action
            self.client.record_action()

            logger.info(f"Successfully replied with comment {comment.id}")

            return {
                "success": True,
                "reddit_comment_id": comment.id,
                "reddit_url": f"https://reddit.com{comment.permalink}",
            }

        except praw.exceptions.RedditAPIException as e:
            error_msg = str(e)
            logger.error(f"Reddit API error submitting reply: {error_msg}")

            if "RATELIMIT" in error_msg:
                return {
                    "success": False,
                    "error": "rate_limited",
                    "message": error_msg,
                    "retry": True,
                }
            elif "DELETED_COMMENT" in error_msg or "THREAD_LOCKED" in error_msg:
                return {
                    "success": False,
                    "error": "cannot_reply",
                    "message": "Post/comment is deleted or locked",
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
            logger.error(f"Unknown error submitting reply: {e}")
            return {
                "success": False,
                "error": "unknown",
                "message": str(e),
                "retry": True,
            }

    def process_mention(self, mention: Dict, client_data: Dict) -> Dict:
        """
        Process a mention and generate/post a reply

        Args:
            mention: Mention record from database
            client_data: Client record for context

        Returns:
            Result dict
        """
        mention_id = mention["id"]
        logger.info(f"Processing mention {mention_id}")

        # Get the post context
        context = self.get_post_context(mention["reddit_url"])

        if not context["success"]:
            db.update_mention(
                mention_id,
                {
                    "should_reply": False,
                    "skip_reason": f"Could not fetch context: {context.get('error')}",
                },
            )
            logger.warning(f"Could not fetch context for mention {mention_id}")
            return {"success": False, "error": "context_fetch_failed", "skipped": True}

        post_data = context["post"]
        comments = context["comments"]

        # Check if we've already replied to this post
        for comment in comments:
            if comment["author"].lower() == self.client.username.lower():
                db.update_mention(
                    mention_id,
                    {
                        "should_reply": False,
                        "skip_reason": "Already replied to this post",
                    },
                )
                logger.info(f"Already replied to post, skipping mention {mention_id}")
                return {"success": True, "skipped": True, "reason": "already_replied"}

        # Generate a reply using AI
        try:
            reply_content = self.content_gen.generate_reply(
                post_title=post_data["title"],
                post_content=post_data["selftext"],
                subreddit=post_data["subreddit"],
                existing_comments=comments,
                product_info={
                    "name": client_data.get("product_name"),
                    "description": client_data.get("product_description"),
                    "value_props": client_data.get("value_propositions", []),
                },
                tone=client_data.get("tone", "professional"),
                disclosure=client_data.get("disclosure_text", "I work on this product"),
            )
        except Exception as e:
            logger.error(f"Error generating reply: {e}")
            db.update_mention(
                mention_id,
                {
                    "should_reply": False,
                    "skip_reason": f"AI generation failed: {str(e)}",
                },
            )
            return {"success": False, "error": "ai_generation_failed"}

        # Check if AI decided to skip
        if reply_content is None or reply_content.lower().strip() == "skip":
            db.update_mention(
                mention_id,
                {
                    "should_reply": False,
                    "skip_reason": "AI determined post is not relevant",
                },
            )
            db.log_activity(
                activity_type="mention_skipped",
                client_id=mention["client_id"],
                entity_type="mention",
                entity_id=mention_id,
                details={"reason": "AI skip", "subreddit": post_data["subreddit"]},
            )
            logger.info(f"AI skipped mention {mention_id} - not relevant")
            return {"success": True, "skipped": True, "reason": "ai_skip"}

        # Post the reply
        result = self.submit_reply(
            parent_id=post_data["id"], content=reply_content, is_post=True
        )

        if result["success"]:
            # Create reply record
            reply = db.create_reply(
                {
                    "client_id": mention["client_id"],
                    "account_id": self.client.account_id,
                    "mention_id": mention_id,
                    "reddit_comment_id": result["reddit_comment_id"],
                    "reddit_url": result["reddit_url"],
                    "parent_type": "post",
                    "parent_reddit_id": post_data["id"],
                    "content": reply_content,
                    "status": "posted",
                    "posted_at": datetime.utcnow().isoformat(),
                }
            )

            # Update mention
            db.update_mention(
                mention_id,
                {
                    "replied": True,
                    "reply_id": reply["id"],
                    "replied_at": datetime.utcnow().isoformat(),
                },
            )

            # Update keyword stats if we have a keyword_id
            if mention.get("keyword_id"):
                keyword = db.update_keyword(
                    mention["keyword_id"],
                    {"reply_count": db.get_mention(mention_id).get("reply_count", 0) + 1},
                )

            db.log_activity(
                activity_type="reply_published",
                client_id=mention["client_id"],
                account_id=self.client.account_id,
                entity_type="reply",
                entity_id=reply["id"],
                details={
                    "subreddit": post_data["subreddit"],
                    "mention_id": mention_id,
                },
            )

            logger.info(f"Reply posted for mention {mention_id}: {result['reddit_url']}")
        else:
            db.update_mention(
                mention_id,
                {
                    "should_reply": False,
                    "skip_reason": f"Reply failed: {result.get('message')}",
                },
            )

            db.log_activity(
                activity_type="reply_failed",
                client_id=mention["client_id"],
                account_id=self.client.account_id,
                entity_type="mention",
                entity_id=mention_id,
                details={"error": result.get("message")},
            )

            logger.error(f"Reply failed for mention {mention_id}: {result.get('message')}")

        return result

    def reply_to_post(
        self, post_id: str, content: str, client_id: str
    ) -> Dict:
        """
        Reply to an existing post in the database

        Args:
            post_id: Database post UUID
            content: Reply content
            client_id: Client UUID

        Returns:
            Result dict
        """
        post = db.get_post(post_id)
        if not post or not post.get("reddit_post_id"):
            return {"success": False, "error": "Post not found or not published"}

        result = self.submit_reply(
            parent_id=post["reddit_post_id"], content=content, is_post=True
        )

        if result["success"]:
            reply = db.create_reply(
                {
                    "client_id": client_id,
                    "account_id": self.client.account_id,
                    "post_id": post_id,
                    "reddit_comment_id": result["reddit_comment_id"],
                    "reddit_url": result["reddit_url"],
                    "parent_type": "post",
                    "parent_reddit_id": post["reddit_post_id"],
                    "content": content,
                    "status": "posted",
                    "posted_at": datetime.utcnow().isoformat(),
                }
            )
            result["reply_id"] = reply["id"]

        return result


def process_unreplied_mentions(client_id: str = None, limit: int = 20) -> Dict:
    """
    Process unreplied mentions

    Args:
        client_id: Optional filter to specific client
        limit: Max mentions to process

    Returns:
        Summary
    """
    mentions = db.get_unreplied_mentions(client_id=client_id, limit=limit)

    results = {
        "processed": 0,
        "replied": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    logger.info(f"Processing {len(mentions)} unreplied mentions")

    # Group mentions by client
    client_mentions: Dict[str, List[Dict]] = {}
    for mention in mentions:
        cid = mention["client_id"]
        if cid not in client_mentions:
            client_mentions[cid] = []
        client_mentions[cid].append(mention)

    for cid, cid_mentions in client_mentions.items():
        # Get client data
        client_data = db.get_client(cid)
        if not client_data:
            logger.warning(f"Client not found: {cid}")
            continue

        # Get available account
        reddit_client = RedditClient.get_available_for_client(cid)
        if not reddit_client:
            for m in cid_mentions:
                results["errors"].append(
                    {"mention_id": m["id"], "error": "No available account"}
                )
            logger.warning(f"No available account for client {cid}")
            continue

        manager = ReplyManager(reddit_client)

        for mention in cid_mentions:
            results["processed"] += 1

            result = manager.process_mention(mention, client_data)

            if result.get("skipped"):
                results["skipped"] += 1
            elif result["success"]:
                results["replied"] += 1
            else:
                results["failed"] += 1
                results["errors"].append(
                    {"mention_id": mention["id"], "error": result.get("message")}
                )

            # Random delay (10-30 seconds)
            delay = random.uniform(10, 30)
            logger.debug(f"Waiting {delay:.1f}s before next reply")
            time.sleep(delay)

    logger.info(
        f"Finished processing mentions: {results['replied']} replied, "
        f"{results['skipped']} skipped, {results['failed']} failed"
    )

    return results
