"""
FastAPI server for Reddit Growth Engine workers
Full version with all endpoints - uses lazy loading for imports
"""
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Log startup
logger.info("Starting Reddit Growth Engine API...")
logger.info(f"PORT env var: {os.getenv('PORT', 'not set')}")

# Initialize FastAPI app
app = FastAPI(
    title="Reddit Growth Engine API",
    description="API for Reddit marketing automation platform",
    version="1.0.0",
)

logger.info("FastAPI app initialized")


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class OnboardRequest(BaseModel):
    client_id: str
    website_url: str


class ProcessPostsRequest(BaseModel):
    limit: int = 10


class CreatePostRequest(BaseModel):
    client_id: str
    subreddit_id: str
    title: str
    content: str
    content_type: str = "text"
    link_url: Optional[str] = None
    schedule_at: Optional[str] = None


class GeneratePostRequest(BaseModel):
    client_id: str
    subreddit_id: str
    topic: str
    post_type: str = "value"
    include_product_mention: bool = True
    schedule_at: Optional[str] = None


class ProcessMentionsRequest(BaseModel):
    client_id: Optional[str] = None
    limit: int = 20


class ScoreMentionRequest(BaseModel):
    title: str
    content: str
    subreddit: str
    client_id: str


class VerifyAccountRequest(BaseModel):
    account_id: str


class GenerateKeywordsRequest(BaseModel):
    client_id: str


# =============================================================================
# LAZY LOADING HELPERS
# =============================================================================

_db = None
_config = None


def get_db():
    """Lazy load database client"""
    global _db
    if _db is None:
        from database.supabase_client import db
        _db = db
    return _db


def get_config():
    """Lazy load config"""
    global _config
    if _config is None:
        from config import config
        _config = config
    return _config


# =============================================================================
# HEALTH & STATUS ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Reddit Growth Engine API", "status": "running"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "reddit-growth-engine",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/status")
async def service_status():
    """Get service status with configuration validation"""
    config = get_config()
    errors = config.validate()
    return {
        "healthy": len(errors) == 0,
        "configuration_errors": errors,
        "supabase_configured": bool(config.SUPABASE_URL),
        "anthropic_configured": bool(config.ANTHROPIC_API_KEY),
        "timestamp": datetime.utcnow().isoformat(),
    }


# =============================================================================
# ONBOARDING ENDPOINTS
# =============================================================================

@app.post("/onboard")
async def onboard_client(request: OnboardRequest):
    """Start client onboarding process"""
    try:
        db = get_db()

        # Get client
        client = db.get_client(request.client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        # Update client status
        db.update_client(request.client_id, {"status": "onboarding"})

        # Scrape website
        try:
            from scraper.website import WebsiteScraper
            scraper = WebsiteScraper()
            product_info = await scraper.scrape_and_extract(request.website_url)

            # Update client with product info
            db.update_client(request.client_id, {
                "product_info": product_info,
                "website": request.website_url,
            })
        except Exception as e:
            logger.warning(f"Website scraping failed: {e}")
            product_info = None

        # Generate keywords
        try:
            from ai.keywords import KeywordGenerator
            kg = KeywordGenerator()
            keywords = await kg.generate_keywords(request.client_id)
            logger.info(f"Generated {len(keywords)} keywords")
        except Exception as e:
            logger.warning(f"Keyword generation failed: {e}")
            keywords = []

        # Discover subreddits
        try:
            from ai.keywords import SubredditDiscovery
            sd = SubredditDiscovery()
            subreddits = await sd.discover_subreddits(request.client_id)
            logger.info(f"Discovered {len(subreddits)} subreddits")
        except Exception as e:
            logger.warning(f"Subreddit discovery failed: {e}")
            subreddits = []

        # Update client to active
        db.update_client(request.client_id, {"status": "active"})

        # Log activity
        db.log_activity(
            activity_type="client_onboarded",
            client_id=request.client_id,
            organization_id=client.get("organization_id"),
            details={
                "website_url": request.website_url,
                "keywords_generated": len(keywords),
                "subreddits_discovered": len(subreddits),
            },
        )

        return {
            "status": "onboarding_complete",
            "client_id": request.client_id,
            "keywords_generated": len(keywords),
            "subreddits_discovered": len(subreddits),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Onboarding failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# POSTS ENDPOINTS
# =============================================================================

@app.post("/posts/process")
async def process_posts(request: ProcessPostsRequest):
    """Process pending scheduled posts"""
    try:
        from reddit.post import process_pending_posts
        result = await process_pending_posts(limit=request.limit)
        return result
    except Exception as e:
        logger.error(f"Post processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/posts/create")
async def create_post(request: CreatePostRequest):
    """Create a new post"""
    try:
        db = get_db()

        post = db.create_post({
            "client_id": request.client_id,
            "subreddit_id": request.subreddit_id,
            "title": request.title,
            "content": request.content,
            "content_type": request.content_type,
            "link_url": request.link_url,
            "scheduled_at": request.schedule_at or datetime.utcnow().isoformat(),
            "status": "scheduled",
        })

        return {"post": post}

    except Exception as e:
        logger.error(f"Post creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/posts/generate")
async def generate_post(request: GeneratePostRequest):
    """Generate a post using AI"""
    try:
        db = get_db()

        # Get client and subreddit info
        client = db.get_client(request.client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        subreddit = db.get_subreddit(request.subreddit_id)
        if not subreddit:
            raise HTTPException(status_code=404, detail="Subreddit not found")

        # Generate content
        from ai.content import ContentGenerator
        cg = ContentGenerator()
        generated = await cg.generate_post_content(
            client=client,
            subreddit=subreddit,
            topic=request.topic,
            post_type=request.post_type,
            include_product_mention=request.include_product_mention,
        )

        # Create post
        post = db.create_post({
            "client_id": request.client_id,
            "subreddit_id": request.subreddit_id,
            "title": generated["title"],
            "content": generated["content"],
            "content_type": "text",
            "scheduled_at": request.schedule_at or datetime.utcnow().isoformat(),
            "status": "scheduled",
        })

        return {"post": post, "generated_content": generated}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Post generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/posts/{client_id}")
async def get_posts(
    client_id: str,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
):
    """Get posts for a client"""
    try:
        db = get_db()
        posts = db.get_posts_for_client(client_id, status=status, limit=limit)
        return {"posts": posts, "total": len(posts)}
    except Exception as e:
        logger.error(f"Get posts failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# MENTIONS ENDPOINTS
# =============================================================================

@app.post("/mentions/process")
async def process_mentions(request: ProcessMentionsRequest):
    """Process unreplied mentions"""
    try:
        from reddit.reply import process_unreplied_mentions
        result = await process_unreplied_mentions(
            client_id=request.client_id,
            limit=request.limit,
        )
        return result
    except Exception as e:
        logger.error(f"Mention processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mentions/score")
async def score_mention(request: ScoreMentionRequest):
    """Score a mention for relevance"""
    try:
        from ai.scoring import RelevanceScorer
        scorer = RelevanceScorer()

        score = await scorer.score_mention(
            title=request.title,
            content=request.content,
            subreddit=request.subreddit,
            client_id=request.client_id,
        )

        return score
    except Exception as e:
        logger.error(f"Mention scoring failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/mentions/{client_id}")
async def get_mentions(
    client_id: str,
    replied: Optional[bool] = None,
    limit: int = Query(default=50, le=200),
):
    """Get mentions for a client"""
    try:
        db = get_db()
        mentions = db.get_mentions_for_client(client_id, replied=replied, limit=limit)
        return {"mentions": mentions, "total": len(mentions)}
    except Exception as e:
        logger.error(f"Get mentions failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WARMUP ENDPOINTS
# =============================================================================

@app.post("/warmup/process")
async def process_warmup():
    """Process account warmup actions"""
    try:
        from reddit.warmup import process_warmup_accounts
        result = await process_warmup_accounts()
        return result
    except Exception as e:
        logger.error(f"Warmup processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/warmup/status/{account_id}")
async def get_warmup_status(account_id: str):
    """Get warmup status for an account"""
    try:
        db = get_db()
        config = get_config()

        account = db.get_account(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        current_stage = account.get("warmup_stage", 0)
        stage_info = config.WARMUP_STAGES.get(current_stage, {})
        next_stage = current_stage + 1 if current_stage < 5 else None

        # Calculate account age
        created_at = account.get("created_at_reddit")
        if created_at:
            from datetime import datetime
            created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            account_age_days = (datetime.utcnow().replace(tzinfo=None) - created_dt.replace(tzinfo=None)).days
        else:
            account_age_days = 0

        result = {
            "account_id": account_id,
            "username": account.get("username"),
            "status": account.get("status"),
            "current_stage": current_stage,
            "stage_name": stage_info.get("name", "unknown"),
            "karma": account.get("karma", 0),
            "account_age_days": account_age_days,
            "is_ready": current_stage >= 5,
        }

        if next_stage and next_stage <= 5:
            next_stage_info = config.WARMUP_STAGES.get(next_stage, {})
            result["next_stage"] = {
                "stage": next_stage,
                "days_required": next_stage_info.get("min_days", 0),
                "days_remaining": max(0, next_stage_info.get("min_days", 0) - account_age_days),
                "karma_required": next_stage_info.get("min_karma", 0),
                "karma_remaining": max(0, next_stage_info.get("min_karma", 0) - account.get("karma", 0)),
            }

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get warmup status failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# METRICS ENDPOINTS
# =============================================================================

@app.post("/metrics/sync")
async def sync_metrics():
    """Sync metrics for all posts"""
    try:
        from reddit.metrics import sync_all_metrics
        result = await sync_all_metrics()
        return result
    except Exception as e:
        logger.error(f"Metrics sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics/{client_id}")
async def get_metrics(
    client_id: str,
    days: int = Query(default=30, le=365),
):
    """Get metrics for a client"""
    try:
        db = get_db()

        # Get aggregate metrics
        summary = db.get_aggregate_metrics(client_id, days)

        # Get daily metrics
        daily = db.get_metrics_for_client(client_id, days)

        # Get active accounts count
        client = db.get_client(client_id)
        if client:
            accounts = db.get_active_accounts_for_client(client_id)
            subreddits = db.get_subreddits_for_client(client_id)
        else:
            accounts = []
            subreddits = []

        # Get recent activity
        activity = db.get_activity_log(client_id=client_id, limit=20)

        return {
            "period_days": days,
            "summary": {
                **summary,
                "active_accounts": len(accounts),
                "active_subreddits": len(subreddits),
            },
            "daily_metrics": daily,
            "recent_activity": activity,
        }

    except Exception as e:
        logger.error(f"Get metrics failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# KEYWORDS ENDPOINTS
# =============================================================================

@app.post("/keywords/generate")
async def generate_keywords(request: GenerateKeywordsRequest):
    """Generate keywords for a client"""
    try:
        from ai.keywords import KeywordGenerator
        kg = KeywordGenerator()
        keywords = await kg.generate_keywords(request.client_id)

        return {
            "generated": len(keywords),
            "keywords": keywords,
        }
    except Exception as e:
        logger.error(f"Keyword generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/keywords/{client_id}")
async def get_keywords(
    client_id: str,
    active_only: bool = True,
):
    """Get keywords for a client"""
    try:
        db = get_db()
        keywords = db.get_keywords_for_client(client_id, active_only=active_only)
        return {"keywords": keywords, "total": len(keywords)}
    except Exception as e:
        logger.error(f"Get keywords failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SUBREDDITS ENDPOINTS
# =============================================================================

@app.get("/subreddits/{client_id}")
async def get_subreddits(
    client_id: str,
    active_only: bool = True,
):
    """Get subreddits for a client"""
    try:
        db = get_db()
        subreddits = db.get_subreddits_for_client(client_id, active_only=active_only)
        return {"subreddits": subreddits, "total": len(subreddits)}
    except Exception as e:
        logger.error(f"Get subreddits failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/subreddits/discover/{client_id}")
async def discover_subreddits(client_id: str):
    """Discover new subreddits for a client"""
    try:
        from ai.keywords import SubredditDiscovery
        sd = SubredditDiscovery()
        subreddits = await sd.discover_subreddits(client_id)

        return {
            "discovered": len(subreddits),
            "subreddits": subreddits,
        }
    except Exception as e:
        logger.error(f"Subreddit discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ACCOUNTS ENDPOINTS
# =============================================================================

@app.post("/accounts/verify")
async def verify_account(request: VerifyAccountRequest):
    """Verify a Reddit account"""
    try:
        from reddit.auth import RedditClient

        db = get_db()
        account = db.get_account(request.account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        client = RedditClient(account)
        is_valid = client.verify()

        if is_valid:
            stats = client.get_stats()
            return {
                "valid": True,
                "username": account.get("username"),
                **stats,
            }
        else:
            return {
                "valid": False,
                "username": account.get("username"),
                "error": "Could not authenticate with Reddit",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Account verification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/accounts/verify-all")
async def verify_all_accounts():
    """Verify all accounts"""
    try:
        from reddit.auth import verify_all_accounts
        result = await verify_all_accounts()
        return result
    except Exception as e:
        logger.error(f"Verify all accounts failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/accounts/{organization_id}")
async def get_accounts(organization_id: str):
    """Get accounts for an organization"""
    try:
        db = get_db()
        accounts = db.get_accounts_for_organization(organization_id)

        # Remove sensitive data
        for account in accounts:
            account.pop("password_encrypted", None)
            account.pop("reddit_client_secret", None)

        return {"accounts": accounts, "total": len(accounts)}
    except Exception as e:
        logger.error(f"Get accounts failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CLIENTS ENDPOINTS
# =============================================================================

@app.get("/clients/{client_id}")
async def get_client(client_id: str):
    """Get client details"""
    try:
        db = get_db()
        client = db.get_client(client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        return {"client": client}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get client failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/clients/org/{organization_id}")
async def get_clients_for_org(organization_id: str):
    """Get all clients for an organization"""
    try:
        db = get_db()
        clients = db.get_clients_for_organization(organization_id)
        return {"clients": clients, "total": len(clients)}
    except Exception as e:
        logger.error(f"Get clients failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CONTENT GENERATION ENDPOINTS
# =============================================================================

@app.post("/content/ideas/{client_id}")
async def generate_content_ideas(
    client_id: str,
    subreddit: str = Query(...),
    count: int = Query(default=5, le=20),
):
    """Generate post ideas for a subreddit"""
    try:
        db = get_db()

        client = db.get_client(client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        from ai.content import ContentGenerator
        cg = ContentGenerator()

        ideas = await cg.generate_post_ideas(
            client=client,
            subreddit_name=subreddit,
            count=count,
        )

        return {"ideas": ideas, "subreddit": subreddit}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Content idea generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# STARTUP
# =============================================================================

logger.info("All routes registered, app ready")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting uvicorn on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
