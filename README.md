# Reddit Growth Engine

A scalable, multi-tenant Reddit marketing automation platform built for AIMS internal service and Cursive AI productized offering.

## Overview

Reddit Growth Engine automates Reddit marketing through:
- **Smart Onboarding**: Automatically scrapes websites and generates keywords
- **Account Warmup**: Gradually builds Reddit account reputation safely
- **Scheduled Posting**: AI-generated posts customized per subreddit
- **Mention Monitoring**: F5Bot integration for real-time keyword alerts
- **Auto-Replies**: Context-aware, AI-generated responses
- **Analytics**: Daily metrics tracking and performance insights

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    REDDIT GROWTH ENGINE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌────────────────────────────────────────┐     │
│  │ Supabase │◄──►│           N8N Orchestrator             │     │
│  │ (DB+Auth)│    │  Onboarding │ Posting │ Monitoring     │     │
│  └──────────┘    └────────────────────┬───────────────────┘     │
│                                       │                          │
│                                       ▼                          │
│                  ┌────────────────────────────────────────┐     │
│                  │          Python Workers (Railway)       │     │
│                  │   Reddit │ AI │ Scraper │ Metrics       │     │
│                  └────────────────────┬───────────────────┘     │
│                                       │                          │
│                  ┌────────────────────┴───────────────────┐     │
│                  │                                         │     │
│            ┌─────┴─────┐  ┌─────────────┐  ┌────────────┐ │     │
│            │ Reddit    │  │ Claude API  │  │ Firecrawl  │ │     │
│            │ API       │  │ (Anthropic) │  │            │ │     │
│            └───────────┘  └─────────────┘  └────────────┘ │     │
│                                                            │     │
└────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Clone Repository
```bash
git clone https://github.com/your-org/reddit-growth-engine.git
cd reddit-growth-engine
```

### 2. Set Up Environment
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Deploy Database
Run `supabase/001_schema.sql` and `supabase/002_rls_policies.sql` in Supabase.

### 4. Deploy Workers
```bash
# Using Railway
railway up
```

### 5. Set Up N8N
Import workflows from `n8n-workflows/` directory.

See [Deployment Guide](docs/DEPLOYMENT.md) for detailed instructions.

## Project Structure

```
reddit-growth-engine/
├── workers/                 # Python FastAPI application
│   ├── reddit/             # Reddit API interactions
│   │   ├── auth.py         # Account management
│   │   ├── post.py         # Post creation
│   │   ├── reply.py        # Reply handling
│   │   ├── warmup.py       # Account warmup
│   │   └── metrics.py      # Metrics collection
│   ├── ai/                 # AI content generation
│   │   ├── content.py      # Content generation
│   │   ├── keywords.py     # Keyword generation
│   │   └── scoring.py      # Relevance scoring
│   ├── scraper/            # Web scraping
│   │   └── website.py      # Website extraction
│   ├── database/           # Database client
│   │   └── supabase_client.py
│   ├── utils/              # Utilities
│   │   ├── encryption.py
│   │   └── rate_limiter.py
│   ├── config.py           # Configuration
│   └── main.py             # FastAPI server
├── supabase/               # Database schema
│   ├── 001_schema.sql      # Tables and functions
│   └── 002_rls_policies.sql # Row Level Security
├── n8n-workflows/          # N8N workflow definitions
│   ├── 01-client-onboarding.json
│   ├── 02-daily-posting.json
│   ├── 03-mention-monitoring.json
│   ├── 04-daily-warmup.json
│   ├── 05-daily-metrics.json
│   └── 06-account-verification.json
├── docs/                   # Documentation
│   ├── DEPLOYMENT.md
│   └── API.md
├── requirements.txt        # Python dependencies
├── Dockerfile             # Container definition
├── railway.json           # Railway configuration
└── .env.example           # Environment template
```

## Key Features

### Multi-Tenant Support
- Organizations and users with role-based access
- Client isolation via Row Level Security
- Per-client configuration and metrics

### Account Management
- 5-stage warmup process (0-5)
- Automatic karma and age tracking
- Cooldown management between actions
- Shadowban and suspension detection

### AI-Powered Content
- Claude-based content generation
- Subreddit-aware customization
- Relevance scoring for mentions
- Natural, non-promotional tone

### Automation
- Scheduled posting (3x daily)
- Real-time mention monitoring (15-min intervals)
- Daily warmup processing
- Nightly metrics sync

## API Reference

See [API Documentation](docs/API.md) for complete endpoint reference.

Key endpoints:
- `POST /onboard` - Start client onboarding
- `POST /posts/process` - Process scheduled posts
- `POST /mentions/process` - Process mentions
- `POST /warmup/process` - Process account warmup
- `GET /metrics/{client_id}` - Get client metrics

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SUPABASE_URL` | Supabase project URL | Yes |
| `SUPABASE_SERVICE_KEY` | Service role key | Yes |
| `ANTHROPIC_API_KEY` | Claude API key | Yes |
| `FIRECRAWL_API_KEY` | Firecrawl API key | No |
| `ENCRYPTION_KEY` | Password encryption key | Yes |

### Warmup Stages

| Stage | Name | Min Days | Min Karma | Actions |
|-------|------|----------|-----------|---------|
| 0 | New | 0 | 0 | None |
| 1 | Browsing | 1 | 0 | Upvote |
| 2 | Upvoting | 3 | 0 | Upvote, Save |
| 3 | Commenting | 5 | 10 | Upvote, Comment |
| 4 | Posting | 10 | 50 | Upvote, Comment, Post |
| 5 | Ready | 14 | 100 | All |

## Cost Estimates

### Per Client/Month
| Service | Estimated Cost |
|---------|---------------|
| Supabase | $0 (free tier) |
| Railway | ~$5 |
| Claude API | $2-5 |
| Firecrawl | ~$0.50 |
| **Total** | **$7-15** |

### Suggested Pricing
| Tier | Price | Margin |
|------|-------|--------|
| Starter | $149/mo | ~93% |
| Growth | $349/mo | ~94% |
| Scale | $599/mo | ~93% |

## Security

- All passwords encrypted with Fernet
- Row Level Security on all tables
- Service role key for backend only
- Rate limiting built-in

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

Proprietary - AIMS / Cursive AI

---

**Version:** 1.0.0
**Created:** December 27, 2024
