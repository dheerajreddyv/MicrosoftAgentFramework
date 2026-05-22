# ------------------------------------
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# ------------------------------------

"""
DESCRIPTION:
    Deploys writer and reviewer prompt agents to Microsoft Foundry.
    Agents are created as persistent deployments and verified with a test conversation.

USAGE:
    python create_agents.py

    Before running:

    pip install "azure-ai-projects>=2.0.0" python-dotenv

    Set these environment variables:
    1) FOUNDRY_PROJECT_ENDPOINT - The Azure AI Project endpoint from your Foundry portal.
    2) FOUNDRY_MODEL_NAME - The deployment name of the AI model.
"""

import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition

load_dotenv()

endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
model = os.environ["FOUNDRY_MODEL_NAME"]

AGENTS = [
    {
        "name": "writer",
        "instructions": "You are a concise copywriter. Provide a single, punchy marketing sentence based on the prompt.",
    },
    {
        "name": "reviewer",
        "instructions": "You are a thoughtful reviewer. Give brief feedback on the previous assistant message.",
    },
]

with (
    DefaultAzureCredential() as credential,
    AIProjectClient(endpoint=endpoint, credential=credential) as project_client,
):
    deployed_agents = []

    # Deploy each agent to Foundry
    for agent_config in AGENTS:
        agent = project_client.agents.create_version(
            agent_name=agent_config["name"],
            definition=PromptAgentDefinition(
                model=model,
                instructions=agent_config["instructions"],
            ),
        )
        deployed_agents.append(agent)
        print(f"Deployed agent: {agent.name} (id: {agent.id}, version: {agent.version})")

    # Verify deployment with a test conversation
    with project_client.get_openai_client() as openai_client:
        writer_agent = deployed_agents[0]
        reviewer_agent = deployed_agents[1]

        # Writer generates a tagline
        conversation = openai_client.conversations.create(
            items=[{"type": "message", "role": "user", "content": "Write a tagline for a budget-friendly eBike."}],
        )

        response = openai_client.responses.create(
            conversation=conversation.id,
            extra_body={"agent_reference": {"name": writer_agent.name, "type": "agent_reference"}},
        )
        print(f"\n[writer] {response.output_text}")

        # Reviewer provides feedback on the writer's output
        openai_client.conversations.items.create(
            conversation_id=conversation.id,
            items=[{"type": "message", "role": "user", "content": "Please review the tagline above and give brief feedback."}],
        )

        response = openai_client.responses.create(
            conversation=conversation.id,
            extra_body={"agent_reference": {"name": reviewer_agent.name, "type": "agent_reference"}},
        )
        print(f"[reviewer] {response.output_text}")

        openai_client.conversations.delete(conversation_id=conversation.id)

    print("\nAgents deployed successfully to Microsoft Foundry.")
    print("Deployed agents:")
    for agent in deployed_agents:
        print(f"  - {agent.name} (version: {agent.version})")