import logging
import os

import google.auth
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

_, project_id = google.auth.default()
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id or ""
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

VOTING_INSTRUCTION = """You are a Voting Agent specializing in marketing copywriting.

If memories about this user are available, use them to personalize your response —
for example, if the user has historically preferred a certain ad style, lean into
that style and factor it into the judge's reasoning.

When given a product description, generate three distinct ad copy options and then
select the best one. Output your response in EXACTLY this format — use the exact
section headers shown, with no leading text before the first header:

## HUMOROUS
Write a witty, funny ad copy under 50 words. Be memorable and entertaining.

## PROFESSIONAL
Write an elegant, trustworthy ad copy under 50 words. Focus on value and reliability.

## URGENT
Write an urgent, FOMO-driven ad copy under 50 words. Use strong calls to action.

## JUDGE
**Winner:** [HUMOROUS, PROFESSIONAL, or URGENT]
**Reason:** [One sentence explaining why this option wins for a general audience]
**Final Polish:** [The winning copy, refined and ready to publish]

Replace the placeholder text in each section with real ad copy for the product.
Do not include any text, preamble, or explanation outside of these four sections."""


async def _save_to_memory(callback_context: CallbackContext) -> None:
    try:
        await callback_context.add_session_to_memory()
    except Exception as e:
        logging.warning("Could not save to Memory Bank (expected in local dev): %s", e)


root_agent = Agent(
    name="voting_agent",
    model=GEMINI_MODEL,
    instruction=VOTING_INSTRUCTION,
    tools=[PreloadMemoryTool()],
    after_agent_callback=_save_to_memory,
)

app = App(
    root_agent=root_agent,
    name="voting_app",
)
