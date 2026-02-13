from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import review, decision

app = FastAPI(
    title="Prior Authorization Review API",
    description="Prior auth review powered by Claude via Microsoft Agent Framework",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review.router, prefix="/api")
app.include_router(decision.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
