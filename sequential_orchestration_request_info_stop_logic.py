# Copyright (c) Microsoft. All rights reserved.

import asyncio
import os

from agent_framework import AgentExecutorResponse
from agent_framework.foundry import FoundryAgent
from agent_framework.orchestrations import AgentRequestInfoResponse, SequentialBuilder
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import AzureCliCredential
from dotenv import load_dotenv

load_dotenv()

"""
Sequential workflow with human-in-the-loop (Request Info).

Docs:
https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/sequential?pivots=programming-language-python#sequential-orchestration-with-human-in-the-loop
"""


async def process_stream(stream):
    requests: dict[str, AgentExecutorResponse] = {}
    final_text: dict[str, str] = {}

    async for event in stream:
        if event.type == "request_info" and isinstance(event.data, AgentExecutorResponse):
            requests[event.request_id] = event.data
        elif event.type == "output":
            items = event.data if isinstance(event.data, list) else [event.data]
            for msg in items:
                name = getattr(msg, "author_name", None) or getattr(msg, "role", "assistant")
                final_text[name] = final_text.get(name, "") + (getattr(msg, "text", "") or "")

    if final_text:
        print("\n===== Final Output =====")
        for name, text in final_text.items():
            print(f"[{name}]: {text}")

    if not requests:
        return None

    responses: dict[str, AgentRequestInfoResponse] = {}
    for request_id, request in requests.items():
        print(
            f"\n[Feedback] {request.executor_id} said: "
            f"'{request.agent_response.text}'"
        )
        user_input = input("Your guidance (or 'skip' to approve): ")  # noqa: ASYNC250
        if user_input.lower() == "skip":
            responses[request_id] = AgentRequestInfoResponse.approve()
        else:
            responses[request_id] = AgentRequestInfoResponse.from_strings([user_input])
    return responses


async def main() -> None:
    credential = AzureCliCredential(
        tenant_id=os.environ.get("AZURE_TENANT_ID"),
        process_timeout=int(os.environ.get("AZURE_CLI_PROCESS_TIMEOUT", "60")),
    )

    async with credential, AIProjectClient(
        endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=credential
    ) as project_client:
        writer = FoundryAgent(
            project_client=project_client, agent_name="writer", name="writer",
        )
        reviewer = FoundryAgent(
            project_client=project_client, agent_name="reviewer", name="reviewer",
        )

        workflow = (
            SequentialBuilder(participants=[writer, reviewer])
            .with_request_info(agents=["writer"])
            .build()
        )

        stream = workflow.run("Write a tagline for a budget-friendly eBike.", stream=True)
        pending = await process_stream(stream)
        while pending is not None:
            stream = workflow.run(stream=True, responses=pending)
            pending = await process_stream(stream)


if __name__ == "__main__":
    asyncio.run(main())