"""Shared OpenAI client, split out from agent.py so the specialist agents
(document_agent, credit_agent, mortgage_agent) can use it without importing
agent.py itself and creating a circular import."""

from openai import OpenAI

from . import config

client = OpenAI(api_key=config.OPENROUTER_API_KEY, base_url=config.OPENROUTER_BASE_URL)
