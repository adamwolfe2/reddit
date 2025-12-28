"""
FastAPI server for Reddit Growth Engine workers
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
import uvicorn
import logging
from datetime import datetime

from reddit.post import process_pending_posts, create_scheduled_post, PostManager
from reddit.reply import process_unreplied_mentions, ReplyManager
from reddit.warmup import process_warmup_accounts, check_warmup_status
from reddit.auth import RedditClient, verify_all_accounts
from reddit.metrics import sync_all_metrics, get_client_stats
from scraper.website import WebsiteScraper
from ai.keywords import KeywordGenerator, SubredditDiscovery
from ai.content import ContentGenerator
from ai.scoring import RelevanceScorer
from database.supabase_client import db
from config import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Reddit Growth Engine API",
    description="API for Reddit marketing automation platform",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================


class OnboardClientRequest(BaseModel):
    client_id: str
    website_url: str


class ProcessPostsRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=100)


class ProcessMentionsRequest(BaseModel):
    client_id: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)


class GeneratePostRequest(BaseModel):
    client_id: str
    subreddit_id: str
    topic: str
    post_type: str = Field(default="value", pattern="^(value|story|question|discussion)$")
    include_product_mention: bool = True
    schedule_at: Optional[str] = None


class CreatePostRequest(BaseModel):
    client_id: str
    subreddit_id: str
    title: str
    content: str
    content_type: str = Field(default="text", pattern="^(text|link)$")
    link_url: Optional[str] = None
    schedule_at: Optional[str] = None


class GenerateKeywordsRequest(BaseModel):
    client_id: str


class ScoreMentionRequest(BaseModel):
    title: str
    content: str
    subreddit: str
    client_id: str


class VerifyAccountRequest(BaseModel):
    account_id: str


# ============================================================================
# HEALTH & STATUS ENDPOINTS
# ============================================================================


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
    """Get service status with configuration check"""
    errors = config.validate()
    return {
        "healthy": len(errors) == 0,
        "configuration_errors": errors,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ============================================================================
# ONBOARDING ENDPOINTS
# ============================================================================


@app.post("/onboard")
async def onboard_client(request: OnboardClientRequest, background_tasks: BackgroundTasks):
    """
    Onboard a new client - scrape website, extract info, generate keywords
    """
    client = db.get_client(request.client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Run onboarding in background
    background_tasks.add_task(run_onboarding, request.client_id, request.website_url)

    return {"status": "onboarding_started", "client_id": request.client_id}


async def run_onboarding(client_id: str, website_url: str):
    """Background task to run full onboarding"""
    logger.info(f"Starting onboarding for client {client_id}")

    try:
        # 1. Scrape website
        scraper = WebsiteScraper()
        product_info = scraper.extract_product_info(website_url)

        if not product_info.get("success"):
            db.update_client(client_id, {"status": "onboarding_failed"})
            db.log_activity(
                activity_type="client_onboarded",
                client_id=client_id,
                details={"error": product_info.get("error", "Unknown error"), "step": "scraping"},
            )
            logger.error(f"Onboarding failed for {client_id}: scraping failed")
            return

        # 2. Update client with extracted info
        client = db.get_client(client_id)
        db.update_client(
            client_id,
            {
                "product_name": product_info.get("product_name"),
                "product_description": product_info.get("product_description"),
                "value_propositions": product_info.get("value_propositions", []),
                "target_audience": product_info.get("target_audience"),
                "use_cases": product_info.get("use_cases", []),
                "competitors": product_info.get("competitors", []),
                "tone": product_info.get("tone", "professional"),
                "website_content": product_info.get("website_content", "")[:50000],
                "website_scraped_at": datetime.utcnow().isoformat(),
            },
        )

        logger.info(f"Client {client_id}: website scraped successfully")

        # 3. Generate keywords
        keyword_gen = KeywordGenerator()
        keywords = keyword_gen.generate_keywords(
            product_name=product_info.get("product_name", ""),
            product_description=product_info.get("product_description", ""),
            target_audience=product_info.get("target_audience", ""),
            competitors=product_info.get("competitors", []),
        )

        # Save keywords
        keyword_records = [
            {
                "client_id": client_id,
                "keyword": k["keyword"],
                "keyword_type": k["type"],
                "priority": k["priority"],
                "f5bot_enabled": k["priority"] >= 7,  # Auto-enable F5Bot for high priority
            }
            for k in keywords
        ]
        db.create_keywords(keyword_records)

        logger.info(f"Client {client_id}: {len(keywords)} keywords generated")

        # 4. Suggest subreddits
        subreddit_discovery = SubredditDiscovery()
        suggested_subs = subreddit_discovery.suggest_subreddits(product_info, num_suggestions=20)

        # Save subreddits
        subreddit_records = [
            {
                "client_id": client_id,
                "name": s["name"],
                "description": s.get("reasoning", ""),
                "relevance_score": s.get("estimated_relevance", 0.5),
                "is_approved": True,
                "is_active": True,
            }
            for s in suggested_subs
        ]
        if subreddit_records:
            db.create_subreddits(subreddit_records)

        logger.info(f"Client {client_id}: {len(suggested_subs)} subreddits suggested")

        # 5. Mark onboarding complete
        db.update_client(
            client_id,
            {
                "status": "active",
                "onboarding_completed_at": datetime.utcnow().isoformat(),
            },
        )

        db.log_activity(
            activity_type="client_onboarded",
            client_id=client_id,
            details={
                "keywords_generated": len(keywords),
                "subreddits_suggested": len(suggested_subs),
            },
        )

        logger.info(f"Onboarding complete for client {client_id}")

    except Exception as e:
        logger.error(f"Onboarding failed for {client_id}: {e}")
        db.update_client(client_id, {"status": "onboarding_failed"})
        db.log_activity(
            activity_type="client_onboarded",
            client_id=client_id,
            details={"error": str(e)},
        )


# ============================================================================
# POSTING ENDPOINTS
# ============================================================================


@app.post("/posts/process")
async def process_posts(request: ProcessPostsRequest):
    """Process pending scheduled posts"""
    results = process_pending_posts(limit=request.limit)
    return results


@app.post("/posts/create")
async def create_post(request: CreatePostRequest):
    """Create a new post (manual)"""
    client = db.get_client(request.client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    subreddit = db.get_subreddit(request.subreddit_id)
    if not subreddit:
        raise HTTPException(status_code=404, detail="Subreddit not found")

    post = create_scheduled_post(
        client_id=request.client_id,
        subreddit_id=request.subreddit_id,
        title=request.title,
        content=request.content,
        scheduled_at=request.schedule_at or datetime.utcnow().isoformat(),
        content_type=request.content_type,
        link_url=request.link_url,
        generated_by="manual",
    )

    return {"post": post}


@app.post("/posts/generate")
async def generate_post(request: GeneratePostRequest):
    """Generate a new post using AI"""
    client = db.get_client(request.client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    subreddit = db.get_subreddit(request.subreddit_id)
    if not subreddit:
        raise HTTPException(status_code=404, detail="Subreddit not found")

    gen = ContentGenerator()

    content = gen.generate_post_content(
        topic=request.topic,
        subreddit=subreddit["name"],
        product_info={
            "name": client.get("product_name"),
            "description": client.get("product_description"),
            "value_props": client.get("value_propositions", []),
            "use_cases": client.get("use_cases", []),
        },
        post_type=request.post_type,
        include_product_mention=request.include_product_mention,
    )

    # Create post record
    status = "scheduled" if request.schedule_at else "draft"
    post = db.create_post(
        {
            "client_id": request.client_id,
            "subreddit_id": request.subreddit_id,
            "title": content["title"],
            "content": content["content"],
            "status": status,
            "scheduled_at": request.schedule_at,
            "generated_by": "ai",
        }
    )

    db.log_activity(
        activity_type="post_created",
        client_id=request.client_id,
        entity_type="post",
        entity_id=post["id"],
        details={"generated": True, "topic": request.topic},
    )

    return {"post": post, "generated_content": content}


@app.get("/posts/{client_id}")
async def get_posts(
    client_id: str,
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get posts for a client"""
    posts = db.get_posts_for_client(client_id, status=status, limit=limit)
    return {"posts": posts, "total": len(posts)}


# ============================================================================
# MENTION ENDPOINTS
# ============================================================================


@app.post("/mentions/process")
async def process_mentions(request: ProcessMentionsRequest):
    """Process unreplied mentions"""
    results = process_unreplied_mentions(
        client_id=request.client_id, limit=request.limit
    )
    return results


@app.post("/mentions/score")
async def score_mention(request: ScoreMentionRequest):
    """Score a mention for relevance"""
    client = db.get_client(request.client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    scorer = RelevanceScorer()
    score = scorer.score_mention(
        title=request.title,
        content=request.content,
        subreddit=request.subreddit,
        product_info={
            "name": client.get("product_name"),
            "description": client.get("product_description"),
        },
    )

    return score


@app.get("/mentions/{client_id}")
async def get_mentions(
    client_id: str,
    replied: Optional[bool] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get mentions for a client"""
    mentions = db.get_mentions_for_client(client_id, replied=replied, limit=limit)
    return {"mentions": mentions, "total": len(mentions)}


# ============================================================================
# WARMUP ENDPOINTS
# ============================================================================


@app.post("/warmup/process")
async def process_warmup():
    """Process account warmup actions"""
    results = process_warmup_accounts()
    return results


@app.get("/warmup/status/{account_id}")
async def get_warmup_status(account_id: str):
    """Get warmup status for a specific account"""
    status = check_warmup_status(account_id)
    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])
    return status


# ============================================================================
# METRICS ENDPOINTS
# ============================================================================


@app.post("/metrics/sync")
async def sync_metrics():
    """Sync metrics for all posts"""
    results = sync_all_metrics()
    return results


@app.get("/metrics/{client_id}")
async def get_metrics(client_id: str, days: int = Query(default=30, ge=1, le=365)):
    """Get metrics for a client"""
    stats = get_client_stats(client_id, days=days)
    return stats


# ============================================================================
# KEYWORDS ENDPOINTS
# ============================================================================


@app.post("/keywords/generate")
async def generate_keywords(request: GenerateKeywordsRequest):
    """Generate keywords for a client"""
    client = db.get_client(request.client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    gen = KeywordGenerator()
    keywords = gen.generate_keywords(
        product_name=client.get("product_name", ""),
        product_description=client.get("product_description", ""),
        target_audience=client.get("target_audience", ""),
        competitors=client.get("competitors", []),
    )

    # Save keywords (upsert to avoid duplicates)
    saved = []
    for kw in keywords:
        existing = db.get_keywords_for_client(request.client_id)
        if not any(k["keyword"] == kw["keyword"] for k in existing):
            record = db.create_keywords(
                [
                    {
                        "client_id": request.client_id,
                        "keyword": kw["keyword"],
                        "keyword_type": kw["type"],
                        "priority": kw["priority"],
                        "f5bot_enabled": kw["priority"] >= 7,
                    }
                ]
            )
            saved.extend(record)

    return {"generated": len(keywords), "saved": len(saved), "keywords": keywords}


@app.get("/keywords/{client_id}")
async def get_keywords(client_id: str, active_only: bool = True):
    """Get keywords for a client"""
    keywords = db.get_keywords_for_client(client_id, active_only=active_only)
    return {"keywords": keywords, "total": len(keywords)}


# ============================================================================
# SUBREDDIT ENDPOINTS
# ============================================================================


@app.get("/subreddits/{client_id}")
async def get_subreddits(client_id: str, active_only: bool = True):
    """Get subreddits for a client"""
    subreddits = db.get_subreddits_for_client(client_id, active_only=active_only)
    return {"subreddits": subreddits, "total": len(subreddits)}


@app.post("/subreddits/discover/{client_id}")
async def discover_subreddits(client_id: str):
    """Discover new subreddits for a client"""
    client = db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    discovery = SubredditDiscovery()
    suggestions = discovery.suggest_subreddits(
        product_info={
            "name": client.get("product_name"),
            "description": client.get("product_description"),
            "target_audience": client.get("target_audience"),
            "use_cases": client.get("use_cases", []),
        },
        num_suggestions=20,
    )

    # Save new subreddits
    existing = db.get_subreddits_for_client(client_id, active_only=False)
    existing_names = {s["name"].lower() for s in existing}

    new_subs = []
    for s in suggestions:
        if s["name"].lower() not in existing_names:
            new_subs.append(
                {
                    "client_id": client_id,
                    "name": s["name"],
                    "description": s.get("reasoning", ""),
                    "relevance_score": s.get("estimated_relevance", 0.5),
                    "is_approved": True,
                    "is_active": True,
                }
            )

    if new_subs:
        db.create_subreddits(new_subs)

    return {"discovered": len(suggestions), "new": len(new_subs), "subreddits": suggestions}


# ============================================================================
# ACCOUNT ENDPOINTS
# ============================================================================


@app.post("/accounts/verify")
async def verify_account(request: VerifyAccountRequest):
    """Verify a Reddit account's credentials"""
    account = db.get_account(request.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    client = RedditClient(account)
    info = client.verify_credentials()

    if info["valid"]:
        client.sync_account_stats()

    return info


@app.post("/accounts/verify-all")
async def verify_all():
    """Verify all accounts"""
    results = verify_all_accounts()
    return results


@app.get("/accounts/{organization_id}")
async def get_accounts(organization_id: str):
    """Get all accounts for an organization"""
    accounts = db.get_accounts_for_organization(organization_id)
    # Remove sensitive data
    for account in accounts:
        account.pop("password_encrypted", None)
        account.pop("reddit_client_secret", None)
    return {"accounts": accounts, "total": len(accounts)}


# ============================================================================
# CLIENT ENDPOINTS
# ============================================================================


@app.get("/clients/{client_id}")
async def get_client(client_id: str):
    """Get client details"""
    client = db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@app.get("/clients/org/{organization_id}")
async def get_clients_for_org(organization_id: str):
    """Get all clients for an organization"""
    clients = db.get_clients_for_organization(organization_id)
    return {"clients": clients, "total": len(clients)}


# ============================================================================
# CONTENT GENERATION ENDPOINTS
# ============================================================================


@app.post("/content/ideas/{client_id}")
async def generate_post_ideas(
    client_id: str,
    subreddit: str = Query(...),
    count: int = Query(default=5, ge=1, le=20),
):
    """Generate post ideas for a subreddit"""
    client = db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    gen = ContentGenerator()
    ideas = gen.generate_multiple_post_ideas(
        product_info={
            "name": client.get("product_name"),
            "description": client.get("product_description"),
            "use_cases": client.get("use_cases", []),
        },
        subreddit=subreddit,
        count=count,
    )

    return {"ideas": ideas, "subreddit": subreddit}


# ============================================================================
# RUN SERVER
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=config.PORT,
        reload=config.DEBUG,
    )
