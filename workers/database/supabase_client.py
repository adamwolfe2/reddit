"""
Supabase client wrapper with helper methods
"""
from supabase import create_client, Client
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import json

from workers.config import config


class SupabaseClient:
    """Wrapper for Supabase client with domain-specific methods"""

    def __init__(self):
        self._client: Optional[Client] = None

    @property
    def client(self) -> Client:
        """Lazy-load the Supabase client"""
        if self._client is None:
            if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
                raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
            self._client = create_client(
                config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY
            )
        return self._client

    # =========================================================================
    # ORGANIZATIONS
    # =========================================================================

    def get_organization(self, org_id: str) -> Optional[Dict]:
        """Get an organization by ID"""
        response = (
            self.client.table("organizations")
            .select("*")
            .eq("id", org_id)
            .single()
            .execute()
        )
        return response.data

    def get_organization_by_slug(self, slug: str) -> Optional[Dict]:
        """Get an organization by slug"""
        response = (
            self.client.table("organizations")
            .select("*")
            .eq("slug", slug)
            .single()
            .execute()
        )
        return response.data

    # =========================================================================
    # CLIENTS
    # =========================================================================

    def get_client(self, client_id: str) -> Optional[Dict]:
        """Get a client by ID"""
        response = (
            self.client.table("clients")
            .select("*")
            .eq("id", client_id)
            .single()
            .execute()
        )
        return response.data

    def get_active_clients(self, organization_id: str = None) -> List[Dict]:
        """Get all active clients, optionally filtered by organization"""
        query = self.client.table("clients").select("*").eq("status", "active")
        if organization_id:
            query = query.eq("organization_id", organization_id)
        response = query.execute()
        return response.data

    def get_clients_for_organization(self, organization_id: str) -> List[Dict]:
        """Get all clients for an organization"""
        response = (
            self.client.table("clients")
            .select("*")
            .eq("organization_id", organization_id)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data

    def update_client(self, client_id: str, data: Dict) -> Dict:
        """Update a client"""
        response = (
            self.client.table("clients").update(data).eq("id", client_id).execute()
        )
        return response.data[0] if response.data else None

    def create_client(self, data: Dict) -> Dict:
        """Create a new client"""
        response = self.client.table("clients").insert(data).execute()
        return response.data[0] if response.data else None

    # =========================================================================
    # REDDIT ACCOUNTS
    # =========================================================================

    def get_account(self, account_id: str) -> Optional[Dict]:
        """Get a Reddit account by ID"""
        response = (
            self.client.table("reddit_accounts")
            .select("*")
            .eq("id", account_id)
            .single()
            .execute()
        )
        return response.data

    def get_accounts_for_organization(self, organization_id: str) -> List[Dict]:
        """Get all Reddit accounts for an organization"""
        response = (
            self.client.table("reddit_accounts")
            .select("*")
            .eq("organization_id", organization_id)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data

    def get_accounts_for_warmup(self) -> List[Dict]:
        """Get all accounts that need warmup (stage < 5)"""
        response = (
            self.client.table("reddit_accounts")
            .select("*")
            .lt("warmup_stage", 5)
            .eq("status", "warming_up")
            .execute()
        )
        return response.data

    def get_active_accounts_for_client(self, client_id: str) -> List[Dict]:
        """Get active, warmed-up accounts for a client"""
        response = (
            self.client.table("reddit_accounts")
            .select("*")
            .eq("client_id", client_id)
            .eq("status", "active")
            .gte("warmup_stage", 5)
            .execute()
        )
        return response.data

    def get_available_account(
        self, client_id: str, min_cooldown_minutes: int = 10
    ) -> Optional[Dict]:
        """Get an account that's ready to post (not rate-limited)"""
        cutoff_time = datetime.utcnow() - timedelta(minutes=min_cooldown_minutes)

        # First get accounts for this client that are active and warmed up
        response = (
            self.client.table("reddit_accounts")
            .select("*")
            .eq("client_id", client_id)
            .eq("status", "active")
            .gte("warmup_stage", 5)
            .execute()
        )

        if not response.data:
            return None

        # Filter by cooldown in Python (Supabase OR queries can be tricky)
        for account in response.data:
            last_action = account.get("last_action_at")
            if last_action is None:
                return account
            last_action_dt = datetime.fromisoformat(last_action.replace("Z", "+00:00"))
            if last_action_dt.replace(tzinfo=None) < cutoff_time:
                return account

        return None

    def update_account(self, account_id: str, data: Dict) -> Dict:
        """Update a Reddit account"""
        response = (
            self.client.table("reddit_accounts")
            .update(data)
            .eq("id", account_id)
            .execute()
        )
        return response.data[0] if response.data else None

    def create_account(self, data: Dict) -> Dict:
        """Create a new Reddit account"""
        response = self.client.table("reddit_accounts").insert(data).execute()
        return response.data[0] if response.data else None

    def record_account_action(self, account_id: str) -> None:
        """Record that an account performed an action"""
        # Call the increment function
        self.client.rpc("increment_daily_actions", {"account_uuid": account_id}).execute()

        # Update last action time
        self.client.table("reddit_accounts").update(
            {"last_action_at": datetime.utcnow().isoformat()}
        ).eq("id", account_id).execute()

    # =========================================================================
    # KEYWORDS
    # =========================================================================

    def get_keywords_for_client(
        self, client_id: str, active_only: bool = True
    ) -> List[Dict]:
        """Get keywords for a client"""
        query = self.client.table("keywords").select("*").eq("client_id", client_id)
        if active_only:
            query = query.eq("is_active", True)
        response = query.order("priority", desc=True).execute()
        return response.data

    def get_f5bot_keywords(self, client_id: str) -> List[Dict]:
        """Get keywords that have F5Bot monitoring enabled"""
        response = (
            self.client.table("keywords")
            .select("*")
            .eq("client_id", client_id)
            .eq("f5bot_enabled", True)
            .eq("is_active", True)
            .execute()
        )
        return response.data

    def get_all_f5bot_keywords(self) -> List[Dict]:
        """Get all keywords with F5Bot enabled across all clients"""
        response = (
            self.client.table("keywords")
            .select("*, clients(id, name, organization_id)")
            .eq("f5bot_enabled", True)
            .eq("is_active", True)
            .execute()
        )
        return response.data

    def create_keywords(self, keywords: List[Dict]) -> List[Dict]:
        """Bulk create keywords"""
        response = self.client.table("keywords").insert(keywords).execute()
        return response.data

    def update_keyword(self, keyword_id: str, data: Dict) -> Dict:
        """Update a keyword"""
        response = (
            self.client.table("keywords").update(data).eq("id", keyword_id).execute()
        )
        return response.data[0] if response.data else None

    def increment_keyword_mention(self, keyword_id: str) -> None:
        """Increment the mention count for a keyword"""
        # Get current count
        keyword = (
            self.client.table("keywords")
            .select("mention_count")
            .eq("id", keyword_id)
            .single()
            .execute()
        )
        if keyword.data:
            new_count = (keyword.data.get("mention_count") or 0) + 1
            self.client.table("keywords").update(
                {"mention_count": new_count, "last_mention_at": datetime.utcnow().isoformat()}
            ).eq("id", keyword_id).execute()

    # =========================================================================
    # SUBREDDITS
    # =========================================================================

    def get_subreddits_for_client(
        self, client_id: str, active_only: bool = True
    ) -> List[Dict]:
        """Get subreddits for a client"""
        query = self.client.table("subreddits").select("*").eq("client_id", client_id)
        if active_only:
            query = query.eq("is_active", True)
        response = query.order("relevance_score", desc=True).execute()
        return response.data

    def get_subreddit(self, subreddit_id: str) -> Optional[Dict]:
        """Get a subreddit by ID"""
        response = (
            self.client.table("subreddits")
            .select("*")
            .eq("id", subreddit_id)
            .single()
            .execute()
        )
        return response.data

    def get_subreddit_by_name(self, client_id: str, name: str) -> Optional[Dict]:
        """Get a subreddit by name for a client"""
        response = (
            self.client.table("subreddits")
            .select("*")
            .eq("client_id", client_id)
            .eq("name", name)
            .single()
            .execute()
        )
        return response.data

    def get_postable_subreddits(
        self, client_id: str, account_karma: int, account_age_days: int
    ) -> List[Dict]:
        """Get subreddits that an account can post to"""
        response = (
            self.client.table("subreddits")
            .select("*")
            .eq("client_id", client_id)
            .eq("is_active", True)
            .eq("is_approved", True)
            .lte("minimum_karma", account_karma)
            .lte("minimum_account_age_days", account_age_days)
            .execute()
        )
        return response.data

    def create_subreddits(self, subreddits: List[Dict]) -> List[Dict]:
        """Bulk create subreddits"""
        response = self.client.table("subreddits").insert(subreddits).execute()
        return response.data

    def update_subreddit(self, subreddit_id: str, data: Dict) -> Dict:
        """Update a subreddit"""
        response = (
            self.client.table("subreddits")
            .update(data)
            .eq("id", subreddit_id)
            .execute()
        )
        return response.data[0] if response.data else None

    # =========================================================================
    # POSTS
    # =========================================================================

    def get_post(self, post_id: str) -> Optional[Dict]:
        """Get a post by ID"""
        response = (
            self.client.table("posts").select("*").eq("id", post_id).single().execute()
        )
        return response.data

    def get_pending_posts(self, limit: int = 10) -> List[Dict]:
        """Get scheduled posts that are ready to publish"""
        now = datetime.utcnow().isoformat()
        response = (
            self.client.table("posts")
            .select("*, clients(*), subreddits(*)")
            .eq("status", "scheduled")
            .lte("scheduled_at", now)
            .order("scheduled_at")
            .limit(limit)
            .execute()
        )
        return response.data

    def get_posts_for_client(
        self, client_id: str, status: str = None, limit: int = 50
    ) -> List[Dict]:
        """Get posts for a client"""
        query = (
            self.client.table("posts")
            .select("*, subreddits(name)")
            .eq("client_id", client_id)
        )
        if status:
            query = query.eq("status", status)
        response = query.order("created_at", desc=True).limit(limit).execute()
        return response.data

    def get_posts_for_metrics_update(self, since_days: int = 30) -> List[Dict]:
        """Get posts that need metrics updated"""
        cutoff = (datetime.utcnow() - timedelta(days=since_days)).isoformat()
        response = (
            self.client.table("posts")
            .select("*")
            .eq("status", "posted")
            .gte("posted_at", cutoff)
            .execute()
        )
        return response.data

    def create_post(self, post: Dict) -> Dict:
        """Create a new post"""
        response = self.client.table("posts").insert(post).execute()
        return response.data[0] if response.data else None

    def update_post(self, post_id: str, data: Dict) -> Dict:
        """Update a post"""
        response = (
            self.client.table("posts").update(data).eq("id", post_id).execute()
        )
        return response.data[0] if response.data else None

    # =========================================================================
    # MENTIONS
    # =========================================================================

    def get_mention(self, mention_id: str) -> Optional[Dict]:
        """Get a mention by ID"""
        response = (
            self.client.table("mentions")
            .select("*")
            .eq("id", mention_id)
            .single()
            .execute()
        )
        return response.data

    def get_unreplied_mentions(
        self, client_id: str = None, limit: int = 50
    ) -> List[Dict]:
        """Get mentions that haven't been replied to"""
        query = (
            self.client.table("mentions")
            .select("*, keywords(*)")
            .eq("replied", False)
            .eq("should_reply", True)
        )

        if client_id:
            query = query.eq("client_id", client_id)

        response = query.order("detected_at", desc=True).limit(limit).execute()
        return response.data

    def get_mentions_for_client(
        self, client_id: str, replied: bool = None, limit: int = 50
    ) -> List[Dict]:
        """Get mentions for a client"""
        query = (
            self.client.table("mentions")
            .select("*, keywords(keyword)")
            .eq("client_id", client_id)
        )
        if replied is not None:
            query = query.eq("replied", replied)
        response = query.order("detected_at", desc=True).limit(limit).execute()
        return response.data

    def mention_exists(self, client_id: str, reddit_post_id: str) -> bool:
        """Check if a mention already exists"""
        response = (
            self.client.table("mentions")
            .select("id")
            .eq("client_id", client_id)
            .eq("reddit_post_id", reddit_post_id)
            .execute()
        )
        return len(response.data) > 0

    def create_mention(self, mention: Dict) -> Dict:
        """Create a new mention"""
        response = self.client.table("mentions").insert(mention).execute()
        return response.data[0] if response.data else None

    def update_mention(self, mention_id: str, data: Dict) -> Dict:
        """Update a mention"""
        response = (
            self.client.table("mentions").update(data).eq("id", mention_id).execute()
        )
        return response.data[0] if response.data else None

    # =========================================================================
    # REPLIES
    # =========================================================================

    def get_reply(self, reply_id: str) -> Optional[Dict]:
        """Get a reply by ID"""
        response = (
            self.client.table("replies")
            .select("*")
            .eq("id", reply_id)
            .single()
            .execute()
        )
        return response.data

    def get_replies_for_client(self, client_id: str, limit: int = 50) -> List[Dict]:
        """Get replies for a client"""
        response = (
            self.client.table("replies")
            .select("*")
            .eq("client_id", client_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data

    def create_reply(self, reply: Dict) -> Dict:
        """Create a new reply"""
        response = self.client.table("replies").insert(reply).execute()
        return response.data[0] if response.data else None

    def update_reply(self, reply_id: str, data: Dict) -> Dict:
        """Update a reply"""
        response = (
            self.client.table("replies").update(data).eq("id", reply_id).execute()
        )
        return response.data[0] if response.data else None

    # =========================================================================
    # METRICS
    # =========================================================================

    def upsert_daily_metrics(self, client_id: str, date: str, metrics: Dict) -> Dict:
        """Upsert daily metrics for a client"""
        data = {"client_id": client_id, "date": date, **metrics}
        response = (
            self.client.table("daily_metrics")
            .upsert(data, on_conflict="client_id,date")
            .execute()
        )
        return response.data[0] if response.data else None

    def get_metrics_for_client(self, client_id: str, days: int = 30) -> List[Dict]:
        """Get daily metrics for a client"""
        cutoff = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        response = (
            self.client.table("daily_metrics")
            .select("*")
            .eq("client_id", client_id)
            .gte("date", cutoff)
            .order("date", desc=True)
            .execute()
        )
        return response.data

    def get_aggregate_metrics(self, client_id: str, days: int = 30) -> Dict:
        """Get aggregate metrics for a client over a period"""
        metrics = self.get_metrics_for_client(client_id, days)

        if not metrics:
            return {
                "posts_count": 0,
                "replies_count": 0,
                "mentions_found": 0,
                "mentions_replied": 0,
                "total_upvotes": 0,
                "total_comments": 0,
                "total_karma_gained": 0,
            }

        return {
            "posts_count": sum(m.get("posts_count", 0) for m in metrics),
            "replies_count": sum(m.get("replies_count", 0) for m in metrics),
            "mentions_found": sum(m.get("mentions_found", 0) for m in metrics),
            "mentions_replied": sum(m.get("mentions_replied", 0) for m in metrics),
            "total_upvotes": sum(m.get("total_upvotes", 0) for m in metrics),
            "total_comments": sum(m.get("total_comments", 0) for m in metrics),
            "total_karma_gained": sum(m.get("total_karma_gained", 0) for m in metrics),
        }

    # =========================================================================
    # ACTIVITY LOG
    # =========================================================================

    def log_activity(
        self,
        activity_type: str,
        organization_id: str = None,
        client_id: str = None,
        account_id: str = None,
        entity_type: str = None,
        entity_id: str = None,
        details: Dict = None,
    ) -> None:
        """Log an activity"""
        self.client.table("activity_log").insert(
            {
                "activity_type": activity_type,
                "organization_id": organization_id,
                "client_id": client_id,
                "account_id": account_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details": details or {},
            }
        ).execute()

    def get_activity_log(
        self,
        client_id: str = None,
        organization_id: str = None,
        activity_type: str = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Get activity log entries"""
        query = self.client.table("activity_log").select("*")

        if client_id:
            query = query.eq("client_id", client_id)
        if organization_id:
            query = query.eq("organization_id", organization_id)
        if activity_type:
            query = query.eq("activity_type", activity_type)

        response = query.order("created_at", desc=True).limit(limit).execute()
        return response.data

    # =========================================================================
    # CONTENT TEMPLATES
    # =========================================================================

    def get_templates_for_client(
        self, client_id: str, template_type: str = None
    ) -> List[Dict]:
        """Get content templates for a client"""
        query = (
            self.client.table("content_templates")
            .select("*")
            .eq("client_id", client_id)
            .eq("is_active", True)
        )
        if template_type:
            query = query.eq("template_type", template_type)
        response = query.execute()
        return response.data

    def get_templates_for_organization(
        self, organization_id: str, template_type: str = None
    ) -> List[Dict]:
        """Get content templates for an organization"""
        query = (
            self.client.table("content_templates")
            .select("*")
            .eq("organization_id", organization_id)
            .eq("is_active", True)
        )
        if template_type:
            query = query.eq("template_type", template_type)
        response = query.execute()
        return response.data

    def create_template(self, template: Dict) -> Dict:
        """Create a new content template"""
        response = self.client.table("content_templates").insert(template).execute()
        return response.data[0] if response.data else None


# Singleton instance
db = SupabaseClient()
