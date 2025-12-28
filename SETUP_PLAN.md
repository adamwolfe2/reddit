# Reddit Growth Engine - Setup & Deployment Plan

## QA Summary

**Status: READY FOR DEPLOYMENT**

### Issues Fixed During QA:
1. Fixed Dockerfile CMD path (`main:app` -> `workers.main:app`)
2. Created `.gitignore` file

### Verified Components:
- 20 Python modules - all syntax valid
- 12 database tables with RLS policies
- 6 N8N workflow files
- 23 API endpoints
- Complete documentation

---

## DEPLOYMENT STEPS

### YOUR TASKS (Manual Steps Required)

#### Step 1: GitHub Repository Setup
```bash
cd /Users/adamwolfe/reddit/reddit-growth-engine
git init
git add .
git commit -m "Initial commit: Reddit Growth Engine v1.0.0"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/reddit-growth-engine.git
git push -u origin main
```

#### Step 2: Supabase Setup
1. Go to https://supabase.com/dashboard
2. Create new project
3. Wait for project creation (~2 minutes)
4. Go to **Settings > API** and copy:
   - Project URL: `https://xxx.supabase.co`
   - `service_role` key (NOT anon key)
5. Go to **SQL Editor**
6. Run `supabase/001_schema.sql` (copy/paste entire file)
7. Run `supabase/002_rls_policies.sql` (copy/paste entire file)
8. Verify tables in **Table Editor**

#### Step 3: Get API Keys
| Service | URL | What You Need |
|---------|-----|---------------|
| Anthropic | https://console.anthropic.com | API Key |
| Firecrawl | https://www.firecrawl.dev | API Key |
| F5Bot | https://f5bot.com | Account + RSS URL |

#### Step 4: Generate Encryption Key
Run locally:
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Save this key securely - you'll need it for Railway.

#### Step 5: Railway Deployment
1. Go to https://railway.app
2. **New Project > Deploy from GitHub repo**
3. Select your `reddit-growth-engine` repo
4. Add environment variables (see list below)
5. Deploy and get your Railway URL

**Required Environment Variables for Railway:**
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=eyJhbG...
ANTHROPIC_API_KEY=sk-ant-api03-...
ANTHROPIC_MODEL=claude-sonnet-4-20250514
FIRECRAWL_API_KEY=fc-...
ENCRYPTION_KEY=<your-generated-key>
PORT=8000
DEBUG=false
```

#### Step 6: N8N Setup
1. Sign up at https://n8n.io (cloud) or self-host
2. Add environment variables:
   - `WORKER_URL`: Your Railway URL
   - `F5BOT_RSS_URL`: Your F5Bot RSS feed
   - `SUPABASE_URL`: Your Supabase URL
3. Import each workflow from `n8n-workflows/`
4. Configure Supabase credentials in N8N
5. Configure Slack credentials (optional)
6. Activate workflows

#### Step 7: F5Bot Setup
1. Create account at https://f5bot.com
2. Add your product keywords
3. Get your RSS feed URL from account settings

---

### MY TASKS (What I Can Do For You)

Tell me which of these you need:

#### Code Enhancements
- [ ] **Add unit tests** - pytest test suite for all modules
- [ ] **Add logging configuration** - structured logging with log levels
- [ ] **Add Sentry integration** - error tracking
- [ ] **Create seed data scripts** - SQL to populate test data
- [ ] **Add health check improvements** - database connectivity checks

#### Additional N8N Workflows
- [ ] **Error notification workflow** - Alert on failures
- [ ] **Weekly report workflow** - Automated performance summaries
- [ ] **Account rotation workflow** - Auto-switch accounts on issues

#### Documentation
- [ ] **Troubleshooting guide** - Common issues and fixes
- [ ] **Video/screen recording scripts** - Step-by-step instructions
- [ ] **API Postman collection** - Ready-to-import API testing

#### Security Hardening
- [ ] **API authentication** - Add API key validation to endpoints
- [ ] **Rate limiting middleware** - Protect API from abuse
- [ ] **Input validation** - Enhanced request validation

---

## VERIFICATION CHECKLIST

After deployment, verify each component:

### 1. Railway API
```bash
# Health check
curl https://your-railway-url.railway.app/health

# Expected: {"status": "healthy", "service": "reddit-growth-engine", ...}
```

### 2. Database Connection
```bash
curl https://your-railway-url.railway.app/status

# Expected: {"healthy": true, "configuration_errors": []}
```

### 3. First Client Test
```sql
-- In Supabase SQL Editor
INSERT INTO organizations (name, slug, subscription_tier)
VALUES ('Test Org', 'test-org', 'starter')
RETURNING id;

-- Then create a client with the returned org ID
```

### 4. N8N Workflows
- Test each workflow manually before activating
- Check Slack notifications work
- Verify API endpoints are reachable from N8N

---

## COST ESTIMATES (Per Month)

| Service | Free Tier | Paid |
|---------|-----------|------|
| Supabase | 500MB DB, 1GB bandwidth | From $25/mo |
| Railway | $5 credit | ~$5-10/mo |
| Anthropic | None | ~$2-5/mo per client |
| Firecrawl | 100 scrapes | ~$0.50/mo per client |
| N8N | 5 workflows | From $20/mo |

**Total per client: ~$7-15/month**

---

## IMPORTANT NOTES

1. **Railway vs Vercel**: This project uses **Railway**, not Vercel. Railway supports Docker and long-running Python processes. Vercel is for frontend/serverless only.

2. **Service Role Key**: Always use the `service_role` key, NOT the `anon` key. The service role bypasses RLS for backend operations.

3. **Reddit App**: You'll need Reddit API credentials for each account:
   - Go to https://www.reddit.com/prefs/apps
   - Create a "script" type application
   - Note the client ID and secret

4. **Account Warmup**: New accounts start at stage 0 and take ~14 days to fully warm up before marketing activities.

---

## NEXT STEPS AFTER DEPLOYMENT

1. Create your first organization and client in Supabase
2. Add a Reddit account with encrypted password
3. Trigger onboarding via API
4. Monitor warmup progress
5. Set up F5Bot keywords
6. Activate N8N workflows

---

*Generated: December 27, 2024*
*Version: 1.0.0*
