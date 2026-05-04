"""Voting Agent frontend — serves UI and proxies streaming to agent backend."""

import asyncio
import json
import logging
import os
import sys
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import vertexai
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai.types import Content, Part

try:
    from google.api_core.client_options import ClientOptions
    from google.cloud import modelarmor_v1

    _MODELARMOR_AVAILABLE = True
except ImportError:
    _MODELARMOR_AVAILABLE = False
    modelarmor_v1 = None
    ClientOptions = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_modelarmor_client: "modelarmor_v1.ModelArmorClient | None" = None

AGENT_RESOURCE_NAME = os.environ.get("AGENT_RESOURCE_NAME")
GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
if not GCP_PROJECT:
    sys.exit("ERROR: GOOGLE_CLOUD_PROJECT env var is required.")
GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
MODEL_ARMOR_TEMPLATE = os.environ.get("MODEL_ARMOR_TEMPLATE")
MODEL_ARMOR_LOCATION = os.environ.get("MODEL_ARMOR_LOCATION", "us-central1")


if _MODELARMOR_AVAILABLE and MODEL_ARMOR_TEMPLATE:
    _modelarmor_client = modelarmor_v1.ModelArmorClient(
        transport="rest",
        client_options=ClientOptions(
            api_endpoint=f"modelarmor.{MODEL_ARMOR_LOCATION}.rep.googleapis.com",
        ),
    )


# Extract the region from AGENT_RESOURCE_NAME so vertexai.init uses the correct
# endpoint — GOOGLE_CLOUD_LOCATION may differ (e.g. frontend in us-central1,
# agent in us-east1).
def _agent_location() -> str:
    if AGENT_RESOURCE_NAME:
        parts = AGENT_RESOURCE_NAME.split("/")
        try:
            return parts[parts.index("locations") + 1]
        except (ValueError, IndexError):
            pass
    return GCP_LOCATION


SECTION_HEADERS = {
    "## HUMOROUS": "humorous",
    "## PROFESSIONAL": "professional",
    "## URGENT": "urgent",
    "## JUDGE": "judge",
}

app = FastAPI(title="Voting Agent")

_static_dir = Path(__file__).parent / "static"
_templates_dir = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
templates = Jinja2Templates(directory=str(_templates_dir))

_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "connect-src 'self' https://cdn.jsdelivr.net; "
    "img-src 'self' data:; "
    "frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    return response


class SectionParser:
    """Detect section headers in a streaming token buffer and emit routing events."""

    def __init__(self) -> None:
        self.current_section: str | None = None
        self.buffer = ""

    def process(self, chunk: str) -> list[dict]:
        events: list[dict] = []
        self.buffer += chunk

        # Loop until no more section headers remain in the buffer
        found = True
        while found:
            found = False
            for header, section_name in SECTION_HEADERS.items():
                if header in self.buffer:
                    before, _, after = self.buffer.partition(header)
                    if before.strip() and self.current_section:
                        events.append(
                            {
                                "type": "step",
                                "agent": self.current_section,
                                "content": before,
                            },
                        )
                    self.current_section = section_name
                    self.buffer = after.lstrip("\n")
                    found = True
                    break

        # Emit safe portion, keep tail in case it's a partial header
        safe_len = max(0, len(self.buffer) - 20)
        if safe_len > 0 and self.current_section:
            events.append(
                {
                    "type": "step",
                    "agent": self.current_section,
                    "content": self.buffer[:safe_len],
                },
            )
            self.buffer = self.buffer[safe_len:]

        return events

    def flush(self) -> list[dict]:
        if self.buffer and self.current_section:
            return [
                {"type": "step", "agent": self.current_section, "content": self.buffer},
            ]
        return []


def _screen_prompt_sync(prompt: str) -> bool:
    """Returns True if prompt is safe, False if blocked. Runs in thread executor."""
    assert _modelarmor_client is not None
    request = modelarmor_v1.SanitizeUserPromptRequest(
        name=MODEL_ARMOR_TEMPLATE,
        user_prompt_data=modelarmor_v1.DataItem(text=prompt),
    )
    response = _modelarmor_client.sanitize_user_prompt(request=request)
    return (
        response.sanitization_result.filter_match_state
        != modelarmor_v1.FilterMatchState.MATCH_FOUND
    )


async def screen_prompt(prompt: str) -> bool:
    """Returns True if safe to proceed, False if Model Armor blocked the prompt."""
    if not _MODELARMOR_AVAILABLE or not MODEL_ARMOR_TEMPLATE:
        return True
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _screen_prompt_sync, prompt)
    except Exception as e:
        logger.warning("Model Armor screening failed (fail open): %s", e)
        return True


async def stream_locally(prompt: str) -> AsyncGenerator[str, None]:
    """Run the agent in-process using ADK Runner (local dev)."""
    from app.agent import root_agent  # imported here to avoid circular issues

    session_service = InMemorySessionService()
    app_name = f"voting_{uuid.uuid4().hex[:8]}"
    session = await session_service.create_session(app_name=app_name, user_id="user")
    runner = Runner(
        app_name=app_name,
        agent=root_agent,
        session_service=session_service,
    )
    message = Content(role="user", parts=[Part.from_text(text=prompt)])
    parser = SectionParser()

    async for event in runner.run_async(
        user_id="user",
        session_id=session.id,
        new_message=message,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    for sse in parser.process(part.text):
                        yield f"data: {json.dumps(sse)}\n\n"

    for sse in parser.flush():
        yield f"data: {json.dumps(sse)}\n\n"

    yield f"data: {json.dumps({'type': 'complete'})}\n\n"


async def stream_from_agent_runtime(prompt: str) -> AsyncGenerator[str, None]:
    """Call a deployed Agent Runtime resource and stream events."""
    from vertexai import agent_engines

    vertexai.init(project=GCP_PROJECT, location=_agent_location())
    try:
        from typing import Any

        remote_agent: Any = agent_engines.get(AGENT_RESOURCE_NAME or "")
        session = await remote_agent.async_create_session(user_id="demo-user")
    except Exception as e:
        logger.exception(
            "Failed to connect to Agent Runtime %s: %s",
            AGENT_RESOURCE_NAME,
            e,
        )
        yield f"data: {json.dumps({'type': 'error', 'message': 'Agent backend unavailable. The agent may need to be redeployed. Check Cloud Run logs for details.'})}\n\n"
        return

    yield f"data: {json.dumps({'type': 'session', 'session_id': session['id'], 'user_id': 'demo-user'})}\n\n"
    parser = SectionParser()

    try:
        async for event in remote_agent.async_stream_query(
            user_id="demo-user",
            session_id=session["id"],
            message=prompt,
        ):
            # Remote agent events mirror local ADK structure: {'content': {'parts': [{'text': '...'}]}, ...}
            content = (
                event.get("content")
                if isinstance(event, dict)
                else getattr(event, "content", None)
            )
            if not content:
                continue
            parts = (
                content.get("parts", [])
                if isinstance(content, dict)
                else getattr(content, "parts", [])
            )
            for part in parts:
                text = (
                    part.get("text")
                    if isinstance(part, dict)
                    else getattr(part, "text", None)
                )
                if text:
                    for sse in parser.process(text):
                        yield f"data: {json.dumps(sse)}\n\n"
    except Exception as e:
        logger.exception("Agent Runtime stream error: %s", e)
        yield f"data: {json.dumps({'type': 'error', 'message': 'Agent stream interrupted. Please try again.'})}\n\n"
        return

    for sse in parser.flush():
        yield f"data: {json.dumps(sse)}\n\n"

    yield f"data: {json.dumps({'type': 'complete'})}\n\n"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/feedback")
async def submit_feedback(request: Request) -> JSONResponse:
    body = await request.json()
    logger.info("Feedback received: %s", body)

    session_id = body.get("session_id")
    user_id = body.get("user_id", "demo-user")
    agreed = body.get("agreed")
    style = body.get("style", "the winner")

    if AGENT_RESOURCE_NAME and session_id:
        from typing import Any

        from vertexai import agent_engines

        vertexai.init(project=GCP_PROJECT, location=_agent_location())
        remote_agent: Any = agent_engines.get(AGENT_RESOURCE_NAME or "")
        verdict = "agreed" if agreed else "disagreed"
        feedback_msg = (
            f"User feedback: {verdict} with the judge's selection of {style.upper()}."
        )
        if not await screen_prompt(feedback_msg):
            logger.info("Model Armor blocked feedback style: %.80s...", style)
            return JSONResponse({"ok": False, "reason": "blocked"}, status_code=400)
        try:
            async for _ in remote_agent.async_stream_query(
                user_id=user_id,
                session_id=session_id,
                message=feedback_msg,
            ):
                pass  # drain response to trigger after_agent_callback → Memory Bank
        except Exception as e:
            logger.warning("Could not save feedback to memory: %s", e)

    return JSONResponse({"ok": True})


@app.get("/stream_voting")
async def stream_voting(prompt: str) -> StreamingResponse:
    if not await screen_prompt(prompt):
        logger.info("Model Armor blocked prompt: %.80s...", prompt)

        async def blocked_gen() -> AsyncGenerator[str, None]:
            yield f"data: {json.dumps({'type': 'blocked', 'message': 'Your prompt was flagged by our content policy. Please rephrase and try again.'})}\n\n"

        return StreamingResponse(blocked_gen(), media_type="text/event-stream")

    if AGENT_RESOURCE_NAME:
        generator = stream_from_agent_runtime(prompt)
    else:
        generator = stream_locally(prompt)

    return StreamingResponse(generator, media_type="text/event-stream")
