# Azure AI Foundry Agent Service: Basic Setup 

## Basic Agent Setup
   

This bicep template provisions required resources for a basic project setup. A new Cognitive Services Account is created, a gpt-4o model is deployed, and a new project is created.

All agents created in this project will automatically use Microsoft managed, multitenant search and storage resources.

### Prerequisites
1. Install the [Azure Developer CLI (`azd`)](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd)
1. To deploy the template, you must have the following roles:
    * **Azure AI Account Owner** or **Contributor** 
1. To create your first agent you must have the permissions:
    * **Azure AI User**

For more information, [see the getting started guide.](https://learn.microsoft.com/en-us/azure/ai-services/agents/environment-setup)
 
### Deploy with `azd up`

From the `bicep-basic-agent-setup` directory, run:

```bash
cd bicep-basic-agent-setup
azd up
```

You will be prompted to select a subscription, location, and environment name. `azd` will create the resource group and deploy all resources automatically.

To customize parameters, edit `main.parameters.json` before deploying.

To tear down all resources:

```bash
azd down
```

### Alternative: Deploy with Azure CLI

[![Deploy To Azure](https://raw.githubusercontent.com/Azure/azure-quickstart-templates/master/1-CONTRIBUTION-GUIDE/images/deploytoazure.svg?sanitize=true)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fazure-ai-foundry%2Ffoundry-samples%2Frefs%2Fheads%2Fmain%2Finfrastructure%2Finfrastructure-setup-bicep%2F40-basic-agent-setup%2Fazuredeploy.json)

* Create new (or use existing) resource group:

```bash
az group create --name <new-rg-name> --location westus
```

* Deploy the template (run from the `bicep-basic-agent-setup` directory):

```bash
cd bicep-basic-agent-setup
az deployment group create --resource-group <new-rg-name> --template-file main.bicep
```
