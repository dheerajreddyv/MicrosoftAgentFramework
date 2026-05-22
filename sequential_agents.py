# Copyright (c) Microsoft. All rights reserved.

import asyncio
import os

from agent_framework import AgentResponse
from agent_framework.foundry import FoundryAgent
from agent_framework.orchestrations import SequentialBuilder
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

"""
Sample: Sequential workflow (agent-focused API)

Mirrors the official docs:
https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/sequential?pivots=programming-language-python

Prerequisites:
- FOUNDRY_PROJECT_ENDPOINT: your Azure AI Foundry project endpoint.
- FOUNDRY_MODEL_NAME: your model deployment name.
- Run `az login --scope https://ai.azure.com/.default` before executing.
"""


async def main() -> None:
    # 1) Reference pre-deployed Foundry agents (created via create_agents.py)
    project_endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

    # Pick credentials. If AZURE_TENANT_ID is set, use AzureCliCredential pinned
    # to that tenant (DefaultAzureCredential does not accept tenant_id directly).
    # This avoids "Tenant provided in token does not match resource token".
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    credential = (
        AzureCliCredential(tenant_id=tenant_id) if tenant_id else DefaultAzureCredential()
    )

    async with credential, AIProjectClient(
        endpoint=project_endpoint, credential=credential
    ) as project_client:
        # Create one Foundry Conversation per agent. Each id (starts with
        # "conv_") shows up in the Microsoft Foundry portal.
        openai_client = project_client.get_openai_client()
        writer_conv = await openai_client.conversations.create()
        reviewer_conv = await openai_client.conversations.create()

        writer = FoundryAgent(
            project_client=project_client,
            agent_name="writer",
            name="writer",
            default_options={"conversation_id": writer_conv.id},
        )

        reviewer = FoundryAgent(
            project_client=project_client,
            agent_name="reviewer",
            name="reviewer",
            default_options={"conversation_id": reviewer_conv.id},
        )

        # 2) Build sequential workflow: writer -> reviewer
        workflow = SequentialBuilder(participants=[writer, reviewer]).build()

        # 3) Run and print the last agent's response
        events = await workflow.run("Write a tagline for a budget-friendly eBike.")
        outputs = events.get_outputs()

        print("===== Workflow Run =====")
        print(f"writer.conversation:   {writer_conv.id}")
        print(f"reviewer.conversation: {reviewer_conv.id}")

        if outputs:
            print("===== Final Response =====")
            final: AgentResponse = outputs[0]
            print(f"response_id: {final.response_id}")
            print(f"agent_id:    {final.agent_id}")
            for msg in final.messages:
                name = msg.author_name or "assistant"
                print(f"[{name}]\n{msg.text}")
        else:
            print("(no response captured)")


if __name__ == "__main__":
    asyncio.run(main())