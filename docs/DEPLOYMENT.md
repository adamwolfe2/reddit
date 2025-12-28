# Reddit Growth Engine - Deployment Guide

## Overview

This guide walks you through deploying the Reddit Growth Engine from scratch.

## Prerequisites

Before starting, ensure you have:
- A Supabase account (free tier works)
- A Railway account (or similar hosting)
- An Anthropic API account
- A Firecrawl account (optional but recommended)
- An F5Bot account (free)
- (Optional) N8N Cloud or self-hosted N8N instance

---

## Step 1: Supabase Setup

### 1.1 Create Project
1. Go to https://supabase.com/dashboard
2. Click "New Project"
3. Fill in project details and save the password
4. Wait for project to be created (~2 minutes)

### 1.2 Get API Keys
1. Go to Settings > API
2. Copy these values:
   - **Project URL**: `https://xxx.supabase.co`
   - **service_role key**: `eyJhbG...` (use this for backend, NOT anon key)

### 1.3 Run Database Schema
1. Go to SQL Editor in Supabase dashboard
2. Open `supabase/001_schema.sql` from this repo
3. Copy and paste the entire contents
4. Click "Run"
5. Verify tables were created in Table Editor

### 1.4 Run RLS Policies
1. In SQL Editor, create a new query
2. Open `supabase/002_rls_policies.sql`
3. Copy and paste the entire contents
4. Click "Run"

### 1.5 Create Initial Data
Run this in SQL Editor to create your first organization:

```sql
-- Create organization
INSERT INTO organizations (name, slug, subscription_tier)
VALUES ('My Company', 'my-company', 'starter')
RETURNING id;

-- Note the returned ID for the next step
```

---

## Step 2: Railway Deployment

### 2.1 Create Project
1. Go to https://railway.app
2. Click "New Project"
3. Choose "Deploy from GitHub repo"
4. Connect your GitHub account
5. Select your forked/cloned reddit-growth-engine repo

### 2.2 Configure Environment Variables
In Railway project settings, add these environment variables:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
ANTHROPIC_API_KEY=sk-ant-api03-...
ANTHROPIC_MODEL=claude-sonnet-4-20250514
FIRECRAWL_API_KEY=fc-...
ENCRYPTION_KEY=your-generated-key
PORT=8000
DEBUG=false
```

**Generate Encryption Key:**
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2.3 Deploy
1. Railway will auto-deploy from the Dockerfile
2. Wait for deployment to complete
3. Note your Railway URL (e.g., `https://reddit-growth-xxx.railway.app`)
4. Test the health endpoint: `GET /health`

---

## Step 3: N8N Setup

### 3.1 Install N8N
**Option A: N8N Cloud (Recommended)**
1. Go to https://n8n.io
2. Sign up for cloud hosting
3. Create a new instance

**Option B: Self-hosted**
```bash
docker run -it --rm \
  --name n8n \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  n8nio/n8n
```

### 3.2 Configure Environment Variables
In N8N, add these environment variables:
- `WORKER_URL`: Your Railway URL (e.g., `https://reddit-growth-xxx.railway.app`)
- `F5BOT_RSS_URL`: Your F5Bot RSS feed URL
- `SUPABASE_URL`: Your Supabase project URL
- `DEFAULT_CLIENT_ID`: UUID of your default client (for mention processing)

### 3.3 Import Workflows
1. In N8N, go to Workflows
2. Click "Import from file"
3. Import each workflow from `n8n-workflows/`:
   - `01-client-onboarding.json`
   - `02-daily-posting.json`
   - `03-mention-monitoring.json`
   - `04-daily-warmup.json`
   - `05-daily-metrics.json`
   - `06-account-verification.json`

### 3.4 Configure Credentials
Create these credentials in N8N:
1. **Supabase API**: URL and service key
2. **Slack API** (optional): For notifications

### 3.5 Activate Workflows
1. Test each workflow manually first
2. Activate the workflows to run on schedule

---

## Step 4: F5Bot Configuration

### 4.1 Create Account
1. Go to https://f5bot.com
2. Create account with a dedicated email
3. Confirm your email

### 4.2 Add Keywords
1. Log in to F5Bot
2. Click "Add New Alert"
3. Add your product keywords (start with high-priority ones)
4. Check "only-reddit"

### 4.3 Get RSS Feed
F5Bot provides an RSS feed URL in your account settings.
Add this URL to your N8N environment as `F5BOT_RSS_URL`.

---

## Step 5: First Client Setup

### 5.1 Create Client Record
Run in Supabase SQL Editor:

```sql
-- Get your organization ID first
SELECT id FROM organizations WHERE slug = 'my-company';

-- Create client
INSERT INTO clients (
  organization_id,
  name,
  website,
  status
)
VALUES (
  'YOUR_ORG_ID_HERE',
  'My Product',
  'https://myproduct.com',
  'onboarding'
)
RETURNING id;
```

### 5.2 Add Reddit Account
```sql
-- First encrypt your password using the Python encryption utility
-- Or use this SQL with your ENCRYPTION_KEY

INSERT INTO reddit_accounts (
  organization_id,
  client_id,
  username,
  password_encrypted,
  reddit_client_id,
  reddit_client_secret,
  user_agent,
  status
)
VALUES (
  'YOUR_ORG_ID',
  'YOUR_CLIENT_ID',
  'reddit_username',
  'encrypted_password_here',
  'reddit_app_client_id',
  'reddit_app_client_secret',
  'RedditGrowthEngine/1.0 by /u/your_username',
  'warming_up'
);
```

### 5.3 Trigger Onboarding
```bash
curl -X POST https://your-railway-url.railway.app/onboard \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "YOUR_CLIENT_ID",
    "website_url": "https://myproduct.com"
  }'
```

This will:
1. Scrape the website
2. Extract product information
3. Generate keywords
4. Discover relevant subreddits

### 5.4 Configure F5Bot Keywords
After onboarding completes, check the generated keywords:
```sql
SELECT * FROM keywords WHERE client_id = 'YOUR_CLIENT_ID' ORDER BY priority DESC;
```

Add the high-priority keywords to F5Bot.

---

## Step 6: Verify Everything Works

### 6.1 Check API Health
```bash
curl https://your-railway-url.railway.app/health
# Should return: {"status": "healthy", ...}
```

### 6.2 Check Client Status
```bash
curl https://your-railway-url.railway.app/clients/YOUR_CLIENT_ID
# Should show status: "active" after onboarding
```

### 6.3 Verify Account
```bash
curl -X POST https://your-railway-url.railway.app/accounts/verify \
  -H "Content-Type: application/json" \
  -d '{"account_id": "YOUR_ACCOUNT_ID"}'
# Should return valid: true
```

### 6.4 Test Post Generation
```bash
curl -X POST https://your-railway-url.railway.app/posts/generate \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "YOUR_CLIENT_ID",
    "subreddit_id": "YOUR_SUBREDDIT_ID",
    "topic": "Tips for [your industry]",
    "post_type": "value"
  }'
```

---

## Monitoring & Maintenance

### Daily Checks
- Check N8N workflow executions
- Review any failed posts/replies
- Monitor account karma progression

### Weekly Tasks
- Review F5Bot keyword performance
- Adjust subreddit targeting
- Check for any suspended accounts

### Monthly Reviews
- Analyze post performance metrics
- Adjust AI prompts if needed
- Review and update keywords

---

## Troubleshooting

### Common Issues

**"No available account" errors**
- Check that accounts have `status = 'active'` and `warmup_stage >= 5`
- Verify account cooldowns (last_action_at should be >10 min ago)

**Reddit API Rate Limiting**
- Increase delays between actions
- Use multiple accounts
- Check account karma (low karma = stricter limits)

**F5Bot Not Finding Mentions**
- Verify keywords are set up correctly
- Check F5Bot account is active
- Test by posting keyword to r/test

**AI Generating Poor Content**
- Review and update prompts in `ai/content.py`
- Adjust tone settings per client
- Add more context to product info

**Warmup Failing**
- Check if account is shadowbanned
- Verify credentials are correct
- Ensure safe subreddits are accessible

---

## Security Notes

1. **Never commit `.env` files** - Use `.env.example` as a template
2. **Use service_role key carefully** - It bypasses RLS
3. **Encrypt all passwords** - Use the provided encryption utility
4. **Rotate API keys regularly** - Monthly recommended
5. **Monitor account activity** - Watch for suspicious patterns

---

## Support

For issues:
1. Check this documentation first
2. Review logs in Railway
3. Check N8N workflow executions
4. Review Supabase logs

The system logs all activities to the `activity_log` table for debugging.
