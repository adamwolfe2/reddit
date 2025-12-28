"""
FastAPI server for Reddit Growth Engine workers
Minimal version for debugging startup issues
"""
from fastapi import FastAPI
import os
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Log startup
logger.info("Starting Reddit Growth Engine API...")
logger.info(f"PORT env var: {os.getenv('PORT', 'not set')}")
logger.info(f"SUPABASE_URL env var: {'set' if os.getenv('SUPABASE_URL') else 'not set'}")

# Initialize FastAPI app
app = FastAPI(
    title="Reddit Growth Engine API",
    description="API for Reddit marketing automation platform",
    version="1.0.0",
)

logger.info("FastAPI app initialized")


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
    """Get service status"""
    return {
        "healthy": True,
        "supabase_configured": bool(os.getenv("SUPABASE_URL")),
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        "timestamp": datetime.utcnow().isoformat(),
    }


logger.info("Routes registered, app ready")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting uvicorn on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
