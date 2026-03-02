"""
server.py
---------
FastAPI web server for the Acme Corp HR Chatbot.

Endpoints:
  GET  /                          → Serve the frontend SPA
  POST /api/chat                  → Send a message, get a response
  POST /api/reset                 → Reset conversation history
  POST /api/admin/login           → Authenticate as admin
  GET  /api/admin/files           → List knowledge base files (admin)
  POST /api/admin/upload          → Upload a document (admin)
  DELETE /api/admin/files/{name}  → Delete a document (admin)
  POST /api/admin/reload          → Reload knowledge base after changes

Usage:
  pip install fastapi uvicorn python-multipart anthropic pypdf
  export GROQ_API_KEY=gsk_...
  python server.py
"""

import json
import os
import secrets
import shutil

from dotenv import load_dotenv

load_dotenv()
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────

ADMIN_PASSWORD = "1243"
KB_DIR = Path("knowledge_base")
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}
SESSION_TOKEN_LENGTH = 32

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Trenkwalder HR Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ── State (in-memory for simplicity) ─────────────────────────────────────────

_admin_sessions: set[str] = set()
_employee_sessions: dict[str, str] = {}  # token -> employee_id


# ── Lazy chatbot initialization ───────────────────────────────────────────────
# We delay loading until first request so the server starts fast.

_chatbot = None
_documents = []


def get_chatbot():
    global _chatbot, _documents
    if _chatbot is None:
        _reload_chatbot()
    return _chatbot


def _reload_chatbot():
    global _chatbot, _documents
    from chatbot import Chatbot
    from document_loader import load_knowledge_base
    from mock_services import reload_mock_data
    from tools import reload_tool_definitions
    import rag_engine

    print("Reloading mock data...")
    reload_mock_data()
    print("Reloading tool definitions...")
    reload_tool_definitions()
    print("Loading knowledge base...")
    _documents = load_knowledge_base(str(KB_DIR))
    print(f"Loaded {len(_documents)} document(s).")
    print("Indexing documents for RAG...")
    chunk_count = rag_engine.index_documents(_documents)
    print(f"Indexed {chunk_count} chunks.")
    _chatbot = Chatbot()


# ── Admin auth helpers ────────────────────────────────────────────────────────

def require_admin(admin_session: str | None = Cookie(default=None)):
    if not admin_session or admin_session not in _admin_sessions:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return admin_session


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    employee_id: str | None = None

class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[str] = []

class LoginRequest(BaseModel):
    password: str

class EmployeeLoginRequest(BaseModel):
    email: str
    password: str

class ToolToggleRequest(BaseModel):
    enabled: bool

class TestServiceRequest(BaseModel):
    params: dict = {}


# ── Chat endpoints ────────────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, employee_session: str | None = Cookie(default=None)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    bot = get_chatbot()

    # Resolve employee context from session cookie
    employee_id = None
    if employee_session and employee_session in _employee_sessions:
        employee_id = _employee_sessions[employee_session]

    # Capture tool call logs during this request
    tool_calls_log: list[str] = []
    original_call_service = None

    try:
        import mock_services as ms
        original_call_service = ms.call_service

        def logging_call_service(tool_name, tool_input):
            label = f"{tool_name}({', '.join(f'{k}={v}' for k, v in tool_input.items())})" if tool_input else f"{tool_name}()"
            tool_calls_log.append(label)
            return original_call_service(tool_name, tool_input)

        ms.call_service = logging_call_service

        reply = bot.chat(req.message, employee_id=employee_id)
    finally:
        if original_call_service:
            ms.call_service = original_call_service

    return ChatResponse(reply=reply, tool_calls=tool_calls_log)


@app.post("/api/reset")
def reset_chat():
    bot = get_chatbot()
    bot.reset()
    return {"status": "ok", "message": "Conversation reset."}


# ── Employee auth endpoints ───────────────────────────────────────────────

@app.post("/api/employee/login")
def employee_login(req: EmployeeLoginRequest, response: Response):
    """Authenticate an employee by email + password."""
    from mock_services import get_mock_data, reload_mock_data
    reload_mock_data()  # ensure fresh data from disk
    data = get_mock_data()
    employees = data.get("employees", {})
    for emp_id, emp in employees.items():
        if emp.get("email", "").lower() == req.email.lower() and emp.get("password") == req.password:
            token = secrets.token_hex(SESSION_TOKEN_LENGTH)
            _employee_sessions[token] = emp_id
            response.set_cookie(
                key="employee_session",
                value=token,
                httponly=True,
                samesite="lax",
                max_age=3600,
            )
            return {
                "status": "ok",
                "employee_id": emp_id,
                "name": emp["name"],
                "department": emp.get("department", ""),
            }
    raise HTTPException(status_code=401, detail="Invalid email or password")


@app.get("/api/employee/me")
def employee_me(employee_session: str | None = Cookie(default=None)):
    """Return current logged-in employee info."""
    if not employee_session or employee_session not in _employee_sessions:
        return {"logged_in": False}
    emp_id = _employee_sessions[employee_session]
    from mock_services import get_mock_data
    data = get_mock_data()
    emp = data.get("employees", {}).get(emp_id)
    if not emp:
        return {"logged_in": False}
    return {
        "logged_in": True,
        "employee_id": emp_id,
        "name": emp["name"],
        "email": emp.get("email", ""),
        "department": emp.get("department", ""),
    }


@app.post("/api/employee/logout")
def employee_logout(response: Response, employee_session: str | None = Cookie(default=None)):
    """Log out the employee."""
    if employee_session:
        _employee_sessions.pop(employee_session, None)
    response.delete_cookie("employee_session")
    return {"status": "ok"}


# ── Admin endpoints ───────────────────────────────────────────────────────────

@app.post("/api/admin/login")
def admin_login(req: LoginRequest, response: Response):
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Invalid password")
    token = secrets.token_hex(SESSION_TOKEN_LENGTH)
    _admin_sessions.add(token)
    response.set_cookie(
        key="admin_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=3600,  # 1 hour
    )
    return {"status": "ok", "message": "Logged in as admin"}


@app.post("/api/admin/logout")
def admin_logout(response: Response, session: str = Depends(require_admin)):
    _admin_sessions.discard(session)
    response.delete_cookie("admin_session")
    return {"status": "ok"}


@app.get("/api/admin/files")
def list_files(_: str = Depends(require_admin)):
    KB_DIR.mkdir(exist_ok=True)
    files = []
    for f in sorted(KB_DIR.iterdir()):
        if f.suffix.lower() in ALLOWED_EXTENSIONS:
            files.append({
                "name": f.name,
                "format": f.suffix.lstrip(".").upper(),
                "size_kb": round(f.stat().st_size / 1024, 1),
            })
    return {"files": files}


@app.post("/api/admin/upload")
async def upload_file(
    file: UploadFile = File(...),
    _: str = Depends(require_admin),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    KB_DIR.mkdir(exist_ok=True)
    dest = KB_DIR / file.filename

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return {"status": "ok", "filename": file.filename, "message": f"'{file.filename}' uploaded successfully"}


@app.delete("/api/admin/files/{filename}")
def delete_file(filename: str, _: str = Depends(require_admin)):
    target = KB_DIR / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    target.unlink()
    return {"status": "ok", "message": f"'{filename}' deleted"}


@app.post("/api/admin/reload")
def reload_kb(_: str = Depends(require_admin)):
    global _chatbot
    _chatbot = None  # Force reload on next chat request
    get_chatbot()
    import rag_engine
    collection = rag_engine._get_or_create_collection()
    return {
        "status": "ok",
        "message": f"Knowledge base reloaded. {len(_documents)} document(s), {collection.count()} chunks indexed.",
        "files": [d.filename for d in _documents],
        "chunks": collection.count(),
    }


@app.get("/api/admin/check")
def check_admin(admin_session: str | None = Cookie(default=None)):
    is_admin = bool(admin_session and admin_session in _admin_sessions)
    return {"is_admin": is_admin}


# ── API Configuration endpoints ───────────────────────────────────────────────

@app.get("/api/admin/api-config")
def get_api_configuration(_: str = Depends(require_admin)):
    """Return the full API tool configuration."""
    from tools import get_api_config
    return get_api_config()


@app.put("/api/admin/api-config/tools/{tool_name}")
def toggle_tool(tool_name: str, req: ToolToggleRequest, _: str = Depends(require_admin)):
    """Enable or disable a specific tool."""
    from tools import load_api_config, save_api_config, reload_tool_definitions
    config = load_api_config()
    found = False
    for tool in config.get("tools", []):
        if tool["name"] == tool_name:
            tool["enabled"] = req.enabled
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    save_api_config(config)
    reload_tool_definitions()
    return {"status": "ok", "tool": tool_name, "enabled": req.enabled}


# ── Mock Data endpoints ──────────────────────────────────────────────────────

@app.get("/api/admin/mock-data")
def get_mock_data_endpoint(_: str = Depends(require_admin)):
    """Return the current mock data."""
    from mock_services import get_mock_data
    return get_mock_data()


@app.put("/api/admin/mock-data")
def update_mock_data(data: dict, _: str = Depends(require_admin)):
    """Replace mock data with new content."""
    if "employees" not in data:
        raise HTTPException(status_code=400, detail="Missing 'employees' key")
    from mock_services import save_mock_data
    save_mock_data(data)
    return {"status": "ok", "message": "Mock data updated"}


# ── Test Service endpoint ────────────────────────────────────────────────────

@app.post("/api/admin/test-service/{tool_name}")
def test_service(tool_name: str, req: TestServiceRequest, _: str = Depends(require_admin)):
    """Test a mock service by calling it with given parameters."""
    from mock_services import SERVICE_REGISTRY, call_service as raw_call_service
    if tool_name not in SERVICE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown service: {tool_name}")
    try:
        result = raw_call_service(tool_name, req.params)
        return {
            "status": "ok",
            "tool": tool_name,
            "params": req.params,
            "result": result,
        }
    except Exception as e:
        return {
            "status": "error",
            "tool": tool_name,
            "error": str(e),
        }


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    html_path = Path("frontend.html")
    if html_path.exists():
        resp = HTMLResponse(content=html_path.read_text(encoding="utf-8"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp
    return HTMLResponse("<h1>Frontend not found. Ensure frontend.html exists.</h1>", status_code=404)


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not os.environ.get("GROQ_API_KEY"):
        print("[WARNING] GROQ_API_KEY is not set. Chat will fail.")
        print("   Run: set GROQ_API_KEY=gsk_...\n")
    print("[*] Starting Trenkwalder HR Assistant at http://localhost:8000")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
