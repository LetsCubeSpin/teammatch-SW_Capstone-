"""FastAPI application entrypoint for TeamMatch AI."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import auth, classes, matching, matching_v2, surveys

settings = get_settings()

app = FastAPI(
    title="TeamMatch AI API",
    version="0.1.0",
    description="Backend for the TeamMatch AI university team-matching frontend.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(classes.router)
app.include_router(surveys.router)
app.include_router(matching.router)
app.include_router(matching_v2.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
