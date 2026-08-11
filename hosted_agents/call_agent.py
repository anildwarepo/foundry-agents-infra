# Before running the sample:
#    pip install azure-ai-projects>=2.1.0

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import VersionRefIndicator

endpoint = "https://aiservices7jz4.services.ai.azure.com/api/projects/project7jz4"
agent_name = "agent-framework-agent-basic-responses"
agent_version = "1"
isolation_key = "my-isolation-key"

print(f"Agent: {agent_name}, version: {agent_version}")

# To get the latest version at runtime instead:
#   agent = project_client.agents.get(agent_name=agent_name)
#   agent_version = agent.versions["latest"].version

with (
    DefaultAzureCredential() as credential,
    AIProjectClient(
        endpoint=endpoint,
        credential=credential,
        allow_preview=True,
    ) as project_client,
):
    # Create a session for conversation state (preview feature)
    session = project_client.beta.agents.create_session(
        agent_name=agent_name,
        isolation_key=isolation_key,
        version_indicator=VersionRefIndicator(agent_version=agent_version),
    )
    print(f"Created session: {session.agent_session_id}")

    try:
        # Create an OpenAI client bound to the agent endpoint
        openai_client = project_client.get_openai_client(agent_name=agent_name)

        # Call Responses API with the session for state continuity
        response = openai_client.responses.create(
            input="Hello, what can you help me with?",
            extra_body={
                "agent_session_id": session.agent_session_id,
            },
        )
        print(f"Response: {response.output_text}")
    finally:
        # Clean up the session when done
        project_client.beta.agents.delete_session(
            agent_name=agent_name,
            session_id=session.agent_session_id,
            isolation_key=isolation_key,
        )