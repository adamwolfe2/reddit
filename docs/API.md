# Reddit Growth Engine - API Reference

## Base URL
```
https://your-railway-url.railway.app
```

---

## Health & Status

### GET /health
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "service": "reddit-growth-engine",
  "timestamp": "2024-12-27T00:00:00.000Z"
}
```

### GET /status
Service status with configuration validation.

**Response:**
```json
{
  "healthy": true,
  "configuration_errors": [],
  "timestamp": "2024-12-27T00:00:00.000Z"
}
```

---

## Onboarding

### POST /onboard
Start client onboarding process.

**Request:**
```json
{
  "client_id": "uuid",
  "website_url": "https://example.com"
}
```

**Response:**
```json
{
  "status": "onboarding_started",
  "client_id": "uuid"
}
```

---

## Posts

### POST /posts/process
Process pending scheduled posts.

**Request:**
```json
{
  "limit": 10
}
```

**Response:**
```json
{
  "processed": 10,
  "success": 8,
  "failed": 1,
  "skipped": 1,
  "errors": [
    {"post_id": "uuid", "error": "Rate limited"}
  ]
}
```

### POST /posts/create
Create a new post manually.

**Request:**
```json
{
  "client_id": "uuid",
  "subreddit_id": "uuid",
  "title": "Post Title",
  "content": "Post content here",
  "content_type": "text",
  "link_url": null,
  "schedule_at": "2024-12-28T10:00:00Z"
}
```

**Response:**
```json
{
  "post": {
    "id": "uuid",
    "title": "Post Title",
    "status": "scheduled",
    ...
  }
}
```

### POST /posts/generate
Generate a post using AI.

**Request:**
```json
{
  "client_id": "uuid",
  "subreddit_id": "uuid",
  "topic": "Best practices for...",
  "post_type": "value",
  "include_product_mention": true,
  "schedule_at": null
}
```

**Response:**
```json
{
  "post": {...},
  "generated_content": {
    "title": "Generated title",
    "content": "Generated content"
  }
}
```

### GET /posts/{client_id}
Get posts for a client.

**Query Parameters:**
- `status` (optional): Filter by status
- `limit` (default: 50, max: 200)

**Response:**
```json
{
  "posts": [...],
  "total": 25
}
```

---

## Mentions

### POST /mentions/process
Process unreplied mentions.

**Request:**
```json
{
  "client_id": "uuid",
  "limit": 20
}
```

**Response:**
```json
{
  "processed": 20,
  "replied": 15,
  "skipped": 3,
  "failed": 2,
  "errors": [...]
}
```

### POST /mentions/score
Score a mention for relevance.

**Request:**
```json
{
  "title": "Post title",
  "content": "Post content",
  "subreddit": "subredditname",
  "client_id": "uuid"
}
```

**Response:**
```json
{
  "relevance_score": 0.85,
  "sentiment": "question",
  "should_reply": true,
  "urgency": "high",
  "reasoning": "User is actively looking for recommendations",
  "suggested_approach": "Focus on solving their specific problem"
}
```

### GET /mentions/{client_id}
Get mentions for a client.

**Query Parameters:**
- `replied` (optional): Filter by replied status
- `limit` (default: 50, max: 200)

---

## Warmup

### POST /warmup/process
Process account warmup actions.

**Response:**
```json
{
  "processed": 5,
  "actions_performed": 12,
  "fully_warmed": 1,
  "errors": [],
  "stages": {
    "stage_0": 1,
    "stage_2": 2,
    "stage_3": 1,
    "stage_4": 1
  }
}
```

### GET /warmup/status/{account_id}
Get warmup status for an account.

**Response:**
```json
{
  "account_id": "uuid",
  "username": "reddit_user",
  "status": "warming_up",
  "current_stage": 3,
  "stage_name": "commenting",
  "karma": 45,
  "account_age_days": 8,
  "is_ready": false,
  "next_stage": {
    "stage": 4,
    "days_required": 10,
    "days_remaining": 2,
    "karma_required": 50,
    "karma_remaining": 5
  }
}
```

---

## Metrics

### POST /metrics/sync
Sync metrics for all posts.

**Response:**
```json
{
  "posts_processed": 100,
  "posts_updated": 98,
  "replies_processed": 50,
  "replies_updated": 48,
  "errors": [],
  "daily_metrics_updated": 5
}
```

### GET /metrics/{client_id}
Get metrics for a client.

**Query Parameters:**
- `days` (default: 30, max: 365)

**Response:**
```json
{
  "period_days": 30,
  "summary": {
    "posts_count": 45,
    "replies_count": 120,
    "mentions_found": 85,
    "mentions_replied": 60,
    "total_upvotes": 1250,
    "total_comments": 180,
    "total_karma_gained": 890,
    "total_karma": 2500,
    "active_accounts": 3,
    "active_subreddits": 15
  },
  "daily_metrics": [...],
  "top_subreddits": [...],
  "recent_activity": [...]
}
```

---

## Keywords

### POST /keywords/generate
Generate keywords for a client.

**Request:**
```json
{
  "client_id": "uuid"
}
```

**Response:**
```json
{
  "generated": 30,
  "saved": 25,
  "keywords": [
    {"keyword": "product name", "type": "product", "priority": 10},
    {"keyword": "alternative to X", "type": "competitor", "priority": 8},
    ...
  ]
}
```

### GET /keywords/{client_id}
Get keywords for a client.

**Query Parameters:**
- `active_only` (default: true)

---

## Subreddits

### GET /subreddits/{client_id}
Get subreddits for a client.

**Query Parameters:**
- `active_only` (default: true)

### POST /subreddits/discover/{client_id}
Discover new subreddits for a client.

**Response:**
```json
{
  "discovered": 20,
  "new": 12,
  "subreddits": [
    {
      "name": "entrepreneur",
      "reasoning": "Target audience active here",
      "estimated_relevance": 0.85,
      "category": "audience"
    },
    ...
  ]
}
```

---

## Accounts

### POST /accounts/verify
Verify a Reddit account.

**Request:**
```json
{
  "account_id": "uuid"
}
```

**Response:**
```json
{
  "valid": true,
  "username": "reddit_user",
  "karma": 1250,
  "link_karma": 500,
  "comment_karma": 750,
  "created_utc": 1672531200,
  "is_suspended": false,
  "has_verified_email": true
}
```

### POST /accounts/verify-all
Verify all accounts.

**Response:**
```json
{
  "verified": 8,
  "failed": 1,
  "suspended": 1,
  "errors": [...]
}
```

### GET /accounts/{organization_id}
Get accounts for an organization.

---

## Clients

### GET /clients/{client_id}
Get client details.

### GET /clients/org/{organization_id}
Get all clients for an organization.

---

## Content Generation

### POST /content/ideas/{client_id}
Generate post ideas for a subreddit.

**Query Parameters:**
- `subreddit` (required)
- `count` (default: 5, max: 20)

**Response:**
```json
{
  "ideas": [
    {
      "topic": "How to improve your workflow",
      "post_type": "value",
      "description": "Share practical tips...",
      "include_product_mention": true
    },
    ...
  ],
  "subreddit": "productivity"
}
```

---

## Error Responses

All endpoints may return these error formats:

### 400 Bad Request
```json
{
  "detail": "Invalid request data"
}
```

### 404 Not Found
```json
{
  "detail": "Client not found"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error"
}
```

---

## Rate Limits

The API does not impose its own rate limits, but Reddit API limits apply to all operations:
- ~100 requests per minute per OAuth client
- Additional action-specific limits for posting/commenting

The system handles Reddit rate limits automatically with delays and retries.
