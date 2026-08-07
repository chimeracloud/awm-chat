"""AWM Chat backend ... FastAPI on Cloud Run."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .api import router as api_router
from .chat import router as chat_router
from .attachments import router as attachments_router
from .secrets_admin import router as secrets_router

settings = get_settings()

app = FastAPI(title="AWM Chat API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/healthz")
async def health():
    return {"status": "ok", "service": "awm-chat-api"}


app.include_router(api_router)
app.include_router(secrets_router)
app.include_router(chat_router, prefix="/chat")
app.include_router(attachments_router, prefix="/attachments")


# Empty init file marker
