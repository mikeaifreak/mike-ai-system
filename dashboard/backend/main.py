import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import auth
from routes import agents, alerts, chat, finance, metrics, reports, stores

app = FastAPI(title="Mike AI Mission Control")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(metrics.router)
app.include_router(agents.router)
app.include_router(alerts.router)
app.include_router(finance.router)
app.include_router(reports.router)
app.include_router(chat.router)
app.include_router(stores.router)


# ── Auth ──────────────────────────────────────────────────────────────────────
class LoginForm(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
def login(form: LoginForm):
    try:
        token = auth.login(form.username, form.password)
        return {
            "success": True,
            "data": {"token": token, "expires_in": 86400},
            "error": None,
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"success": True, "data": {"status": "ok"}, "error": None}


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
