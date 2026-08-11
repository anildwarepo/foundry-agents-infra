from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import HostedAgentDefinition, ProtocolVersionRecord, AgentProtocol, ContainerConfiguration
from azure.identity import DefaultAzureCredential


PROJECT_ENDPOINT = "https://aiservices7jz4.services.ai.azure.com/api/projects/project7jz4"

# Create project client
credential = DefaultAzureCredential()
project = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=credential,
    allow_preview=True,
)

# Create a hosted agent version
agent = project.agents.create_version(
    agent_name="agent-framework-agent-basic-responses",
    definition=HostedAgentDefinition(
        protocol_versions=[
            ProtocolVersionRecord(protocol=AgentProtocol.RESPONSES, version="1.0.0")
        ],
        cpu="1",
        memory="2Gi",
        container_configuration=ContainerConfiguration(
            image="anildwapremacr.azurecr.io/agent-framework-agent-basic-responses:1.0"
        ),
        environment_variables={
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-5.4"
        }
    )
)

print(f"Agent created: {agent.name}, version: {agent.version}")