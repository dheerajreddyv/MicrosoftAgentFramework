# pylint: disable=line-too-long,useless-suppression
# ------------------------------------
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# ------------------------------------

"""
DESCRIPTION:
    This sample demonstrates how to create a Prompt Agent that uses an
    OAuth-protected MCP (Model Context Protocol) server, referenced via a
    Microsoft Foundry project connection.

USAGE:
    python mcp-custom-oauth-create.py

    Before running the sample:

    pip install "azure-ai-projects>=2.0.0b1" python-dotenv

    Set these environment variables with your own values:
    1) AZURE_AI_PROJECT_ENDPOINT - The Azure AI Project endpoint, as found in the Overview
       page of your Microsoft Foundry portal.
    2) AZURE_AI_MODEL_DEPLOYMENT_NAME - The deployment name of the AI model, as found under
       the "Name" column in the "Models + endpoints" tab in your Microsoft Foundry project.
    3) MCP_OAUTH_CONNECTION_ID (optional) - Full ARM resource ID of the OAuth MCP project
       connection. Defaults to the mcp-oauth-server connection on the
       mfbp-ext-eus2-aiml-profx-01 project.
    4) MCP_OAUTH_SERVER_URL (optional) - URL of the remote MCP server. Override if the
       server endpoint changes.
"""

import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool
from openai.types.responses.response_input_param import McpApprovalResponse, ResponseInputParam


load_dotenv()

endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]

DEFAULT_OAUTH_CONNECTION_ID = "/subscriptions/1ebf9966-e5ab-4c5a-bee5-634c68826dfe/resourceGroups/accaifoundry-ncus-rg/providers/Microsoft.CognitiveServices/accounts/foundryiq-test-project-resource/projects/foundryiq-test-project/connections/My-Azure-MCP-Server"

oauth_connection_id = os.environ.get("MCP_OAUTH_CONNECTION_ID", DEFAULT_OAUTH_CONNECTION_ID)
oauth_server_url = os.environ.get(
    "MCP_OAUTH_SERVER_URL",
    "https://app-ext-sout-mcp-profx-01.azurewebsites.net/mcp",
)

with (
    DefaultAzureCredential() as credential,
    AIProjectClient(endpoint=endpoint, credential=credential) as project_client,
    project_client.get_openai_client() as openai_client,
):
    # [START tool_declaration]
    # For OAuth-protected MCP servers, reference a Foundry project connection that holds
    # the OAuth configuration (client id/secret, token endpoint, scopes, etc.).
    mcp_tool = MCPTool(
        server_label="My-Azure-MCP-Server",
        server_url=oauth_server_url,
        require_approval="never",
        project_connection_id=oauth_connection_id,
    )
    # [END tool_declaration]

    agent = project_client.agents.create_version(
        agent_name="FoundryNew-MCP-OAuth-Agent",
        definition=PromptAgentDefinition(
            model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
            instructions="""You are an assistant that MUST use MCP tools for all tasks the
                    user asks about. Follow these rules strictly:
                    1. ALWAYS call an available MCP tool to satisfy the user's request when one applies.
                    2. NEVER fabricate data the MCP server should provide.
                    3. Report the exact values returned by the tool without altering them.
                    4. If no MCP tool is suitable, say so explicitly.""",
            tools=[mcp_tool],
        ),
    )
    print(f"Agent created (id: {agent.id}, name: {agent.name})")

    # Create a conversation thread to maintain context across multiple interactions
    conversation = openai_client.conversations.create()
    print(f"Created conversation (id: {conversation.id})")

    # Send an initial request that will trigger the MCP tool
    print("Sending request to agent (this can take 60-120s on the first call)...")
    import time as _time
    _t0 = _time.monotonic()
    response = openai_client.responses.create(
        conversation=conversation.id,
        input="Use the multiply tool to compute 17 times 23, then report the exact tool output.",
        extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
        timeout=200,
    )
    print(f"Initial response received in {_time.monotonic() - _t0:.1f}s")

    # If the MCP server requires OAuth user consent, pause and wait for the user
    # to complete the consent flow in a browser, then resume the response.
    max_consent_rounds = 3
    for round_idx in range(max_consent_rounds):
        consent_items = [it for it in response.output
                         if getattr(it, "type", "") == "oauth_consent_request"]
        if not consent_items:
            break

        print("\n========================================================")
        print(" OAuth user consent required to use the MCP server")
        print("========================================================")
        for it in consent_items:
            link = getattr(it, "consent_link", None)
            label = getattr(it, "server_label", "(unknown)")
            print(f"\n[{label}] Open this link in a browser, sign in, and approve:")
            print(link)

        input("\nPress Enter AFTER you have completed consent in the browser to continue... ")

        # Resume the agent run on the same conversation so both turns share
        # one trace/conversation in App Insights. (We deliberately do NOT
        # send `previous_response_id` here — the API rejects both together,
        # and `conversation` is what links the trace.)
        print("Resuming agent run on the same conversation...")
        response = openai_client.responses.create(
            conversation=conversation.id,
            input="Please continue and complete the requested task using the MCP tools.",
            extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
            timeout=200,
        )

    # Process MCP approval requests (separate from OAuth consent)
    input_list: ResponseInputParam = []
    needs_followup = False
    for item in response.output:
        if getattr(item, "type", "") == "mcp_approval_request" and getattr(item, "id", None):
            needs_followup = True
            input_list.append(
                McpApprovalResponse(
                    type="mcp_approval_response",
                    approve=True,
                    approval_request_id=item.id,
                )
            )

    if needs_followup and input_list:
        response = openai_client.responses.create(
            input=input_list,
            previous_response_id=response.id,
            extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
        )

    print(f"\nAgent response: {response.output_text}")

    other_items = [getattr(it, "type", "unknown") for it in response.output
                   if getattr(it, "type", "") not in ("message",)]
    if other_items:
        print(f"Other output item types: {other_items}")

    # Clean up resources by deleting the agent version
    # Uncomment to prevent accumulation of unused agent versions in your project
    # project_client.agents.delete_version(agent_name=agent.name, agent_version=agent.version)
    # print("Agent deleted")