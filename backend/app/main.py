from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.patches import apply as _apply_windows_cli_patch
from app.routers import review, decision

# Fix Windows .CMD subprocess argument mangling (no-op on non-Windows)
_apply_windows_cli_patch()

app = FastAPI(
    title="Prior Authorization Review API",
    description="Prior auth review powered by Claude via Microsoft Agent Framework",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_ORIGIN,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review.router, prefix="/api")
app.include_router(decision.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
