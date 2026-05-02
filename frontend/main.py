"""Voting Agent frontend — serves UI and proxies streaming to agent backend."""

import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import vertexai
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai.types import Content, Part

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AGENT_RESOURCE_NAME = os.environ.get("AGENT_RESOURCE_NAME")
GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "vertical-datum-418119")
GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

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
                            {"type": "step", "agent": self.current_section, "content": before}
                        )
                    self.current_section = section_name
                    self.buffer = after.lstrip("\n")
                    found = True
                    break

        # Emit safe portion, keep tail in case it's a partial header
        safe_len = max(0, len(self.buffer) - 20)
        if safe_len > 0 and self.current_section:
            events.append(
                {"type": "step", "agent": self.current_section, "content": self.buffer[:safe_len]}
            )
            self.buffer = self.buffer[safe_len:]

        return events

    def flush(self) -> list[dict]:
        if self.buffer and self.current_section:
            return [{"type": "step", "agent": self.current_section, "content": self.buffer}]
        return []


async def stream_locally(prompt: str) -> AsyncGenerator[str, None]:
    """Run the agent in-process using ADK Runner (local dev)."""
    from app.agent import root_agent  # imported here to avoid circular issues

    session_service = InMemorySessionService()
    app_name = f"voting_{uuid.uuid4().hex[:8]}"
    session = await session_service.create_session(app_name=app_name, user_id="user")
    runner = Runner(
        app_name=app_name, agent=root_agent, session_service=session_service
    )
    message = Content(role="user", parts=[Part.from_text(text=prompt)])
    parser = SectionParser()

    async for event in runner.run_async(
        user_id="user", session_id=session.id, new_message=message
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
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from vertexai import agent_engines

    vertexai.init(project=GCP_PROJECT, location=GCP_LOCATION)
    remote_agent = agent_engines.get(AGENT_RESOURCE_NAME)

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)

    session = await loop.run_in_executor(
        executor, lambda: remote_agent.create_session(user_id="demo-user")
    )
    session_id = session["id"]

    queue: asyncio.Queue = asyncio.Queue()
    parser = SectionParser()

    def _sync_stream() -> None:
        try:
            for event in remote_agent.stream_query(
                message=prompt,
                session_id=session_id,
                user_id="demo-user",
            ):
                queue.put_nowait(event)
        finally:
            queue.put_nowait(None)

    loop.run_in_executor(executor, _sync_stream)

    while True:
        event = await queue.get()
        if event is None:
            break
        # Agent Runtime events mirror ADK Event structure
        content = event.get("content") if isinstance(event, dict) else getattr(event, "content", None)
        if content:
            parts = content.get("parts", []) if isinstance(content, dict) else getattr(content, "parts", [])
            for part in parts:
                text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                if text:
                    for sse in parser.process(text):
                        yield f"data: {json.dumps(sse)}\n\n"

    for sse in parser.flush():
        yield f"data: {json.dumps(sse)}\n\n"

    yield f"data: {json.dumps({'type': 'complete'})}\n\n"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    mode = "Agent Runtime" if AGENT_RESOURCE_NAME else "local"
    return templates.TemplateResponse(
        "index.html", {"request": request, "mode": mode}
    )


@app.get("/stream_voting")
async def stream_voting(prompt: str) -> StreamingResponse:
    if AGENT_RESOURCE_NAME:
        generator = stream_from_agent_runtime(prompt)
    else:
        generator = stream_locally(prompt)

    return StreamingResponse(generator, media_type="text/event-stream")
