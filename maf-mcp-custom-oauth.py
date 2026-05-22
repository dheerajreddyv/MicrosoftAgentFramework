# pylint: disable=line-too-long,useless-suppression
# ------------------------------------
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# ------------------------------------

"""
Microsoft Agent Framework (MAF) version of the OAuth-protected MCP sample,
WITH OAuth user-consent passthrough.

The Foundry Prompt Agent (with the OAuth-protected MCP tool already attached,
`require_approval="never"`) must already be deployed in your Foundry project.

OAuth consent flow:
    `FoundryAgent.run()` hides raw `oauth_consent_request` items. So before
    invoking the agent we do a lightweight pre-flight call against the raw
    Responses API on a throwaway conversation. If Foundry returns a consent
    link, we print it, wait for the user to sign in, and then re-probe until
    the cached token is valid. Once consent is in place, the real prompt is
    run through `FoundryAgent`.

Usage:
    pip install "azure-ai-projects>=2.0.0b1" agent-framework python-dotenv
    python maf-mcp-custom-oauth.py

Required env vars:
    AZURE_AI_PROJECT_ENDPOINT
Optional:
    AZURE_TENANT_ID
"""

import asyncio
import os

from agent_framework.foundry import FoundryAgent
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

AGENT_NAME = "FoundryNew-MCP-OAuth-Agent"
PROMPT = "Use the multiply tool to compute 17 times 23, then report the exact tool output."
MAX_CONSENT_ROUNDS = 3


def _consent_links(raw_resp) -> list[tuple[str, str]]:
    """Return [(server_label, consent_link), ...] from a raw Responses API result."""
    links: list[tuple[str, str]] = []
    for item in getattr(raw_resp, "output", None) or []:
        if getattr(item, "type", "") == "oauth_consent_request":
            link = getattr(item, "consent_link", None)
            label = getattr(item, "server_label", "(unknown)")
            if link:
                links.append((label, link))
    return links


async def _ensure_consent(openai_client) -> None:
    """Probe via raw Responses API on a throwaway conversation; if consent is
    required, prompt the user. Consent is cached per-user-per-connection, so
    once granted the real run on a fresh conversation will succeed silently."""
    for _ in range(MAX_CONSENT_ROUNDS):
        probe_conv = await openai_client.conversations.create()
        raw_resp = await openai_client.responses.create(
            conversation=probe_conv.id,
            input=PROMPT,
            extra_body={"agent_reference": {"name": AGENT_NAME, "type": "agent_reference"}},
            timeout=200,
        )
        links = _consent_links(raw_resp)
        if not links:
            return  # consent already in place

        print("\n========================================================")
        print(" OAuth user consent required to use the MCP server")
        print("========================================================")
        for label, link in links:
            print(f"\n[{label}] Open this link in a browser, sign in, and approve:")
            print(link)
        input("\nPress Enter AFTER completing consent in the browser to continue... ")

    raise RuntimeError("OAuth consent did not complete after multiple attempts.")


async def main() -> None:
    endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    credential = (
        AzureCliCredential(tenant_id=tenant_id) if tenant_id else DefaultAzureCredential()
    )

    async with credential, AIProjectClient(
        endpoint=endpoint, credential=credential
    ) as project_client:
        openai_client = project_client.get_openai_client()

        # Pre-flight on a throwaway conversation: handle OAuth consent passthrough
        # (FoundryAgent can't surface consent items itself).
        await _ensure_consent(openai_client)

        agent = FoundryAgent(
            project_client=project_client,
            agent_name=AGENT_NAME,
            name=AGENT_NAME,
        )
        print("\nSending prompt to agent (first call can take 60-120s)...")
        response = await agent.run(PROMPT)

        print("\n===== Final Response =====")
        print(f"response_id: {response.response_id}")
        for msg in response.messages:
            name = msg.author_name or "assistant"
            print(f"[{name}] {msg.text}")


if __name__ == "__main__":
    asyncio.run(main())
