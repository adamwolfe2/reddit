"""
Configuration management for Reddit Growth Engine
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Application configuration loaded from environment variables"""

    # Supabase
    SUPABASE_URL: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    SUPABASE_SERVICE_KEY: str = field(
        default_factory=lambda: os.getenv("SUPABASE_SERVICE_KEY", "")
    )

    # Anthropic
    ANTHROPIC_API_KEY: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    ANTHROPIC_MODEL: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    )

    # Firecrawl
    FIRECRAWL_API_KEY: str = field(
        default_factory=lambda: os.getenv("FIRECRAWL_API_KEY", "")
    )

    # Encryption
    ENCRYPTION_KEY: str = field(default_factory=lambda: os.getenv("ENCRYPTION_KEY", ""))

    # Rate Limits
    REDDIT_REQUESTS_PER_MINUTE: int = field(
        default_factory=lambda: int(os.getenv("REDDIT_REQUESTS_PER_MINUTE", "60"))
    )

    # Warmup Settings
    WARMUP_SAFE_SUBREDDITS: List[str] = field(
        default_factory=lambda: [
            "AskReddit",
            "todayilearned",
            "mildlyinteresting",
            "Showerthoughts",
            "explainlikeimfive",
            "LifeProTips",
            "NoStupidQuestions",
            "TrueOffMyChest",
            "CasualConversation",
            "self",
            "test",
            "pics",
            "funny",
            "aww",
            "movies",
            "books",
            "music",
            "gaming",
            "food",
            "travel",
        ]
    )

    WARMUP_STAGES: Dict = field(
        default_factory=lambda: {
            0: {"name": "new", "min_days": 0, "actions": [], "min_karma": 0},
            1: {"name": "browsing", "min_days": 1, "actions": ["upvote"], "min_karma": 0},
            2: {
                "name": "upvoting",
                "min_days": 3,
                "actions": ["upvote", "save"],
                "min_karma": 0,
            },
            3: {
                "name": "commenting",
                "min_days": 5,
                "actions": ["upvote", "comment"],
                "min_karma": 10,
            },
            4: {
                "name": "posting",
                "min_days": 10,
                "actions": ["upvote", "comment", "post"],
                "min_karma": 50,
            },
            5: {
                "name": "ready",
                "min_days": 14,
                "actions": ["all"],
                "min_karma": 100,
            },
        }
    )

    # Posting Settings
    MIN_COOLDOWN_MINUTES: int = field(
        default_factory=lambda: int(os.getenv("MIN_COOLDOWN_MINUTES", "10"))
    )
    MAX_DAILY_POSTS_PER_ACCOUNT: int = field(
        default_factory=lambda: int(os.getenv("MAX_DAILY_POSTS_PER_ACCOUNT", "5"))
    )
    MAX_DAILY_REPLIES_PER_ACCOUNT: int = field(
        default_factory=lambda: int(os.getenv("MAX_DAILY_REPLIES_PER_ACCOUNT", "10"))
    )

    # Content Settings
    MAX_CONTENT_LENGTH: int = field(
        default_factory=lambda: int(os.getenv("MAX_CONTENT_LENGTH", "10000"))
    )
    MAX_TITLE_LENGTH: int = field(
        default_factory=lambda: int(os.getenv("MAX_TITLE_LENGTH", "300"))
    )

    # Server Settings
    PORT: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    DEBUG: bool = field(
        default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true"
    )

    def validate(self) -> List[str]:
        """Validate required configuration values"""
        errors = []

        if not self.SUPABASE_URL:
            errors.append("SUPABASE_URL is required")
        if not self.SUPABASE_SERVICE_KEY:
            errors.append("SUPABASE_SERVICE_KEY is required")
        if not self.ANTHROPIC_API_KEY:
            errors.append("ANTHROPIC_API_KEY is required")
        if not self.ENCRYPTION_KEY:
            errors.append("ENCRYPTION_KEY is required")

        return errors


# Singleton instance
config = Config()
