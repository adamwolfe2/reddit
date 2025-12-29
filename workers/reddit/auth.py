"""
Reddit authentication and account management
"""
import praw
from typing import Optional, Dict
from datetime import datetime
import logging

from workers.config import config
from workers.database.supabase_client import db
from workers.utils.encryption import decrypt_password

logger = logging.getLogger(__name__)


class RedditClient:
    """Wrapper for PRAW Reddit client with account management"""

    def __init__(self, account: Dict):
        """
        Initialize Reddit client from account data

        Args:
            account: Account record from database containing credentials
        """
        self.account = account
        self.account_id = account["id"]
        self.username = account["username"]

        # Decrypt password
        password = decrypt_password(account["password_encrypted"])

        # Initialize PRAW
        self.reddit = praw.Reddit(
            client_id=account["reddit_client_id"],
            client_secret=account["reddit_client_secret"],
            username=account["username"],
            password=password,
            user_agent=account["user_agent"],
        )

        # Set rate limit handling - PRAW will automatically wait
        self.reddit.config.ratelimit_seconds = 300

        logger.info(f"Initialized Reddit client for u/{self.username}")

    @classmethod
    def from_account_id(cls, account_id: str) -> Optional["RedditClient"]:
        """
        Create a RedditClient from an account ID

        Args:
            account_id: UUID of the account in the database

        Returns:
            RedditClient instance or None if account not found
        """
        account = db.get_account(account_id)
        if not account:
            logger.warning(f"Account not found: {account_id}")
            return None
        return cls(account)

    @classmethod
    def get_available_for_client(cls, client_id: str) -> Optional["RedditClient"]:
        """
        Get an available Reddit client for a client

        Args:
            client_id: UUID of the client

        Returns:
            RedditClient instance or None if no account available
        """
        account = db.get_available_account(
            client_id, min_cooldown_minutes=config.MIN_COOLDOWN_MINUTES
        )
        if not account:
            logger.warning(f"No available account for client: {client_id}")
            return None
        return cls(account)

    def verify_credentials(self) -> Dict:
        """
        Verify credentials and return account info

        Returns:
            Dict with account info or error details
        """
        try:
            me = self.reddit.user.me()
            return {
                "valid": True,
                "username": me.name,
                "karma": me.link_karma + me.comment_karma,
                "link_karma": me.link_karma,
                "comment_karma": me.comment_karma,
                "created_utc": me.created_utc,
                "is_suspended": getattr(me, "is_suspended", False),
                "has_verified_email": getattr(me, "has_verified_email", False),
            }
        except praw.exceptions.RedditAPIException as e:
            logger.error(f"Reddit API error verifying credentials: {e}")
            return {"valid": False, "error": str(e), "error_type": "api_error"}
        except Exception as e:
            logger.error(f"Error verifying credentials: {e}")
            return {"valid": False, "error": str(e), "error_type": "unknown"}

    def get_account_age_days(self) -> int:
        """
        Get account age in days

        Returns:
            Number of days since account creation
        """
        me = self.reddit.user.me()
        created = datetime.utcfromtimestamp(me.created_utc)
        return (datetime.utcnow() - created).days

    def get_karma(self) -> int:
        """
        Get total karma

        Returns:
            Combined link and comment karma
        """
        me = self.reddit.user.me()
        return me.link_karma + me.comment_karma

    def get_detailed_karma(self) -> Dict:
        """
        Get detailed karma breakdown

        Returns:
            Dict with link_karma, comment_karma, and total
        """
        me = self.reddit.user.me()
        return {
            "link_karma": me.link_karma,
            "comment_karma": me.comment_karma,
            "total": me.link_karma + me.comment_karma,
        }

    def record_action(self) -> None:
        """Record that an action was taken"""
        db.record_account_action(self.account_id)
        logger.debug(f"Recorded action for account {self.account_id}")

    def update_status(self, status: str, reason: str = None) -> None:
        """
        Update account status

        Args:
            status: New status (warming_up, active, rate_limited, shadowbanned, suspended, inactive)
            reason: Optional reason for the status change
        """
        data = {
            "status": status,
            "status_reason": reason,
            "last_verified_at": datetime.utcnow().isoformat(),
        }
        db.update_account(self.account_id, data)
        logger.info(f"Updated account {self.account_id} status to {status}: {reason}")

        # Log the activity
        db.log_activity(
            activity_type="account_status_change",
            account_id=self.account_id,
            details={"old_status": self.account.get("status"), "new_status": status, "reason": reason},
        )

    def sync_account_stats(self) -> Dict:
        """
        Sync account stats from Reddit

        Returns:
            Dict with verification info
        """
        info = self.verify_credentials()
        if info["valid"]:
            data = {
                "karma": info["karma"],
                "account_age_days": self.get_account_age_days(),
                "last_verified_at": datetime.utcnow().isoformat(),
            }

            # Check for suspension/shadowban
            if info.get("is_suspended"):
                data["status"] = "suspended"
                data["status_reason"] = "Account suspended by Reddit"

            db.update_account(self.account_id, data)
            logger.info(
                f"Synced stats for {self.username}: karma={info['karma']}"
            )
        else:
            logger.warning(f"Failed to sync stats for {self.username}: {info.get('error')}")

        return info

    def check_shadowban(self) -> bool:
        """
        Check if the account might be shadowbanned

        Returns:
            True if likely shadowbanned
        """
        try:
            # A shadowbanned account's submissions won't appear to others
            # We can check if our own submissions appear in the subreddit
            me = self.reddit.user.me()

            # Try posting to r/test and checking if it appears
            # This is a simple heuristic - if we can't see our own posts, we might be shadowbanned
            recent_submissions = list(self.reddit.redditor(me.name).submissions.new(limit=1))

            if recent_submissions:
                sub = recent_submissions[0]
                # If removed, might indicate issues
                if hasattr(sub, "removed") and sub.removed:
                    return True

            return False
        except Exception as e:
            logger.error(f"Error checking shadowban: {e}")
            return False

    def get_subreddit(self, name: str) -> praw.models.Subreddit:
        """
        Get a subreddit object

        Args:
            name: Subreddit name (without r/)

        Returns:
            PRAW Subreddit object
        """
        return self.reddit.subreddit(name)

    def get_submission(self, submission_id: str) -> praw.models.Submission:
        """
        Get a submission by ID

        Args:
            submission_id: Reddit submission ID

        Returns:
            PRAW Submission object
        """
        return self.reddit.submission(id=submission_id)

    def get_submission_by_url(self, url: str) -> praw.models.Submission:
        """
        Get a submission by URL

        Args:
            url: Full Reddit URL

        Returns:
            PRAW Submission object
        """
        return self.reddit.submission(url=url)

    def get_comment(self, comment_id: str) -> praw.models.Comment:
        """
        Get a comment by ID

        Args:
            comment_id: Reddit comment ID

        Returns:
            PRAW Comment object
        """
        return self.reddit.comment(id=comment_id)


def verify_all_accounts() -> Dict:
    """
    Verify all accounts in the system and update their status

    Returns:
        Summary of verification results
    """
    results = {
        "verified": 0,
        "failed": 0,
        "suspended": 0,
        "errors": [],
    }

    # Get all accounts that aren't already marked as suspended/inactive
    accounts = db.get_accounts_for_warmup()  # This gets warming_up accounts
    active_accounts = []

    # Also get active accounts
    for client in db.get_active_clients():
        active_accounts.extend(db.get_active_accounts_for_client(client["id"]))

    all_accounts = accounts + active_accounts

    for account in all_accounts:
        try:
            client = RedditClient(account)
            info = client.sync_account_stats()

            if info["valid"]:
                if info.get("is_suspended"):
                    results["suspended"] += 1
                else:
                    results["verified"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({
                    "account_id": account["id"],
                    "username": account["username"],
                    "error": info.get("error"),
                })
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({
                "account_id": account["id"],
                "username": account["username"],
                "error": str(e),
            })

    return results
