from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import HostedAgentDefinition, ProtocolVersionRecord, AgentProtocol, ContainerConfiguration
from azure.identity import DefaultAzureCredential


PROJECT_ENDPOINT = "https://aiservices7jz4.services.ai.azure.com/api/projects/project7jz4"
AGENT_NAME = "maf-backup-policy-workflow"
CONTAINER_IMAGE = "anildwapremacr.azurecr.io/maf-backup-policy-workflow:202608171500"

# Create project client
credential = DefaultAzureCredential()
project = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=credential,
    allow_preview=True,
)

# Create a hosted agent version
agent = project.agents.create_version(
    agent_name=AGENT_NAME,
    definition=HostedAgentDefinition(
        protocol_versions=[
            ProtocolVersionRecord(protocol=AgentProtocol.INVOCATIONS, version="2.0.0")
        ],
        cpu="1",
        memory="2Gi",
        container_configuration=ContainerConfiguration(
            image=CONTAINER_IMAGE
        ),
        environment_variables={
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-5.4",
            "TOOLBOX_NAME": "backup-discovery-tools",
            "USE_FOUNDRY_TOOLBOX": "true",
        }
    )
)

print(f"Agent created: {agent.name}, version: {agent.version}")