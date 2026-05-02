import os

import google.auth
from google.adk.agents import Agent
from google.adk.apps import App

_, project_id = google.auth.default()
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

VOTING_INSTRUCTION = """You are a Voting Agent specializing in marketing copywriting.

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

root_agent = Agent(
    name="voting_agent",
    model=GEMINI_MODEL,
    instruction=VOTING_INSTRUCTION,
)

app = App(
    root_agent=root_agent,
    name="voting_app",
)
