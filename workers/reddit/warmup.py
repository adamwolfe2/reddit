"""
Reddit account warmup functionality
"""
import praw
from typing import Dict, List
from datetime import datetime, timedelta
import time
import random
import logging

from workers.config import config
from workers.reddit.auth import RedditClient
from workers.database.supabase_client import db
from workers.ai.content import ContentGenerator

logger = logging.getLogger(__name__)


class WarmupManager:
    """Manages Reddit account warmup process"""

    def __init__(self, reddit_client: RedditClient):
        """
        Initialize WarmupManager with a Reddit client

        Args:
            reddit_client: Authenticated RedditClient instance
        """
        self.client = reddit_client
        self.reddit = reddit_client.reddit
        self.content_gen = ContentGenerator()
        self.safe_subs = config.WARMUP_SAFE_SUBREDDITS
        self.stages = config.WARMUP_STAGES

    def get_current_stage(self) -> int:
        """
        Get current warmup stage based on account age and karma

        Returns:
            Current stage number (0-5)
        """
        # Sync latest stats
        self.client.sync_account_stats()
        account = db.get_account(self.client.account_id)

        age_days = account.get("account_age_days", 0)
        karma = account.get("karma", 0)
        current_stage = account.get("warmup_stage", 0)

        # Determine appropriate stage
        new_stage = current_stage

        for stage_num in range(5, -1, -1):
            stage = self.stages[stage_num]
            if age_days >= stage["min_days"] and karma >= stage.get("min_karma", 0):
                new_stage = stage_num
                break

        # Update stage if changed
        if new_stage != current_stage:
            db.update_account(self.client.account_id, {"warmup_stage": new_stage})
            logger.info(
                f"Account {self.client.username} advanced from stage {current_stage} to {new_stage}"
            )

            # Log the stage change
            db.log_activity(
                activity_type="account_warmup",
                account_id=self.client.account_id,
                details={
                    "old_stage": current_stage,
                    "new_stage": new_stage,
                    "karma": karma,
                    "age_days": age_days,
                },
            )

        return new_stage

    def perform_warmup_action(self) -> Dict:
        """
        Perform appropriate warmup action based on current stage

        Returns:
            Result of warmup action
        """
        stage = self.get_current_stage()
        stage_config = self.stages[stage]

        if stage >= 5:
            # Account is fully warmed up, update status
            db.update_account(self.client.account_id, {"status": "active"})
            return {
                "success": True,
                "message": "Account fully warmed up",
                "stage": stage,
                "ready": True,
            }

        allowed_actions = stage_config["actions"]

        if not allowed_actions:
            return {
                "success": True,
                "message": "Stage 0: No actions allowed yet",
                "stage": stage,
            }

        # Pick a random safe subreddit
        subreddit_name = random.choice(self.safe_subs)

        try:
            subreddit = self.reddit.subreddit(subreddit_name)
        except Exception as e:
            # Try another subreddit
            subreddit_name = random.choice(self.safe_subs)
            try:
                subreddit = self.reddit.subreddit(subreddit_name)
            except Exception as e2:
                return {
                    "success": False,
                    "error": f"Cannot access subreddits: {e2}",
                    "stage": stage,
                }

        result = {"success": False, "stage": stage, "action": None, "subreddit": subreddit_name}

        try:
            # Get hot posts
            hot_posts = list(subreddit.hot(limit=25))

            if not hot_posts:
                return {
                    "success": False,
                    "error": "No posts found",
                    "stage": stage,
                    "subreddit": subreddit_name,
                }

            # Filter for suitable posts (not stickied, has comments)
            suitable_posts = [
                p for p in hot_posts if not p.stickied and p.num_comments > 5
            ]

            if not suitable_posts:
                suitable_posts = [p for p in hot_posts if not p.stickied]

            if not suitable_posts:
                suitable_posts = hot_posts

            post = random.choice(suitable_posts)

            # Determine which action to take based on probabilities
            action_weights = {
                "upvote": 0.6,
                "comment": 0.3,
                "save": 0.1,
            }

            # Only include actions that are allowed for this stage
            available_actions = {
                k: v for k, v in action_weights.items() if k in allowed_actions
            }

            if not available_actions:
                # Default to upvote if nothing else is available
                if "upvote" in allowed_actions:
                    available_actions = {"upvote": 1.0}
                else:
                    return {
                        "success": False,
                        "error": "No valid actions for this stage",
                        "stage": stage,
                    }

            # Weighted random selection
            total = sum(available_actions.values())
            r = random.uniform(0, total)
            cumulative = 0
            selected_action = list(available_actions.keys())[0]

            for action, weight in available_actions.items():
                cumulative += weight
                if r <= cumulative:
                    selected_action = action
                    break

            # Perform the selected action
            if selected_action == "upvote":
                post.upvote()
                result["action"] = "upvote"
                result["success"] = True
                result["post_title"] = post.title[:100]

            elif selected_action == "comment":
                # Generate a generic, safe comment
                comment_text = self.content_gen.generate_warmup_comment(
                    post_title=post.title,
                    post_content=post.selftext[:500] if post.selftext else "",
                    subreddit=subreddit_name,
                )

                if comment_text and comment_text.lower().strip() != "skip":
                    post.reply(comment_text)
                    result["action"] = "comment"
                    result["success"] = True
                    result["comment"] = comment_text[:200]
                else:
                    # Fall back to upvote
                    post.upvote()
                    result["action"] = "upvote"
                    result["success"] = True
                    result["note"] = "AI skipped comment, fell back to upvote"

            elif selected_action == "save":
                post.save()
                result["action"] = "save"
                result["success"] = True

            # Record action
            if result["success"]:
                self.client.record_action()

                # Log activity
                db.log_activity(
                    activity_type="account_warmup",
                    account_id=self.client.account_id,
                    details={
                        "stage": stage,
                        "action": result["action"],
                        "subreddit": subreddit_name,
                    },
                )

        except praw.exceptions.RedditAPIException as e:
            error_str = str(e)
            result["error"] = error_str
            logger.error(f"Reddit API error during warmup: {error_str}")

            # Check for shadowban indicators
            if "USER_REQUIRED" in error_str:
                self.client.update_status("shadowbanned", error_str)
            elif "RATELIMIT" in error_str:
                self.client.update_status("rate_limited", error_str)

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Error during warmup action: {e}")

        return result


def process_warmup_accounts() -> Dict:
    """
    Process all accounts that need warmup

    Returns:
        Summary of warmup actions
    """
    accounts = db.get_accounts_for_warmup()

    results = {
        "processed": 0,
        "actions_performed": 0,
        "errors": [],
        "fully_warmed": 0,
        "stages": {},  # Track how many accounts at each stage
    }

    logger.info(f"Processing warmup for {len(accounts)} accounts")

    for account in accounts:
        results["processed"] += 1
        account_id = account["id"]
        username = account["username"]

        try:
            client = RedditClient(account)
            manager = WarmupManager(client)

            # Get current stage for tracking
            current_stage = account.get("warmup_stage", 0)
            stage_key = f"stage_{current_stage}"
            results["stages"][stage_key] = results["stages"].get(stage_key, 0) + 1

            # Perform 1-3 warmup actions per account
            num_actions = random.randint(1, 3)

            for i in range(num_actions):
                result = manager.perform_warmup_action()

                if result.get("ready"):
                    results["fully_warmed"] += 1
                    logger.info(f"Account {username} is now fully warmed up!")
                    break

                if result["success"]:
                    results["actions_performed"] += 1
                    logger.debug(
                        f"Account {username}: {result.get('action')} in r/{result.get('subreddit')}"
                    )
                else:
                    results["errors"].append(
                        {
                            "account_id": account_id,
                            "username": username,
                            "error": result.get("error"),
                        }
                    )
                    # Don't continue with more actions if there's an error
                    break

                # Delay between actions for same account (30-120 seconds)
                if i < num_actions - 1:  # Don't delay after last action
                    delay = random.uniform(30, 120)
                    logger.debug(f"Waiting {delay:.1f}s before next action for {username}")
                    time.sleep(delay)

            # Delay between accounts (1-5 minutes)
            delay = random.uniform(60, 300)
            logger.debug(f"Waiting {delay:.1f}s before next account")
            time.sleep(delay)

        except Exception as e:
            results["errors"].append(
                {
                    "account_id": account_id,
                    "username": username,
                    "error": str(e),
                }
            )
            logger.error(f"Error processing warmup for {username}: {e}")

    logger.info(
        f"Finished warmup processing: {results['actions_performed']} actions, "
        f"{results['fully_warmed']} now ready, {len(results['errors'])} errors"
    )

    return results


def check_warmup_status(account_id: str) -> Dict:
    """
    Check the warmup status of a specific account

    Args:
        account_id: Account UUID

    Returns:
        Status dict
    """
    account = db.get_account(account_id)
    if not account:
        return {"error": "Account not found"}

    client = RedditClient(account)
    client.sync_account_stats()

    # Refresh account data after sync
    account = db.get_account(account_id)

    current_stage = account.get("warmup_stage", 0)
    stage_config = config.WARMUP_STAGES.get(current_stage, {})

    # Calculate progress to next stage
    next_stage = min(current_stage + 1, 5)
    next_stage_config = config.WARMUP_STAGES.get(next_stage, {})

    days_needed = next_stage_config.get("min_days", 0)
    karma_needed = next_stage_config.get("min_karma", 0)

    current_days = account.get("account_age_days", 0)
    current_karma = account.get("karma", 0)

    return {
        "account_id": account_id,
        "username": account.get("username"),
        "status": account.get("status"),
        "current_stage": current_stage,
        "stage_name": stage_config.get("name"),
        "karma": current_karma,
        "account_age_days": current_days,
        "is_ready": current_stage >= 5,
        "next_stage": {
            "stage": next_stage if current_stage < 5 else None,
            "days_required": days_needed,
            "days_remaining": max(0, days_needed - current_days),
            "karma_required": karma_needed,
            "karma_remaining": max(0, karma_needed - current_karma),
        } if current_stage < 5 else None,
    }
