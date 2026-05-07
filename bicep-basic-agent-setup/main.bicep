// Basic agent setup 
@description('The name of the Azure AI Foundry resource.')
@maxLength(9)
param aiServicesName string = 'foundry'

@description('The name of your project')
param projectName string = 'project'

@description('The description of your project')
param projectDescription string = 'some description'

@description('The display name of your project')
param projectDisplayName string = 'project_display_name'

//ensures unique name for the account
// Create a short, unique suffix, that will be unique to each resource group
param deploymentTimestamp string = utcNow('yyyyMMddHHmmss')
var uniqueSuffix = substring(uniqueString('${resourceGroup().id}-${deploymentTimestamp}'), 0, 4)
var accountName = toLower('${aiServicesName}${uniqueSuffix}')
@allowed([
  'australiaeast'
  'canadaeast'
  'eastus'
  'eastus2'
  'francecentral'
  'japaneast'
  'koreacentral'
  'norwayeast'
  'polandcentral'
  'southindia'
  'swedencentral'
  'switzerlandnorth'
  'uaenorth'
  'uksouth'
  'westus'
  'westus2'
  'westus3'
  'westeurope'
  'southeastasia'
  'brazilsouth'
  'germanywestcentral'
  'italynorth'
  'southafricanorth'
  'southcentralus'
])
@description('The Azure region where your AI Foundry resource and project will be created.')
param location string = 'westus'

@description('The name of the OpenAI model you want to deploy')
param modelName string = 'gpt-5.4'

@description('The model format of the model you want to deploy. Example: OpenAI')
param modelFormat string = 'OpenAI'

@description('The version of the model you want to deploy. Example: 2024-11-20')
param modelVersion string = '2026-03-05'

@description('The SKU name for the model deployment. Example: GlobalStandard')
param modelSkuName string = 'GlobalStandard'

@description('The capacity of the model deployment in TPM.')
param modelCapacity int = 40

module aiAccount 'ai-account.bicep' = {
  name: 'ai-${accountName}-deployment'
  params: {
    accountName: accountName
    location: location
    modelName: modelName
    modelFormat: modelFormat
    modelVersion: modelVersion
    modelSkuName: modelSkuName
    modelCapacity: modelCapacity
  }
}

/*
  Step 2: Deploy model
  
  - Agents will use the build-in model deployments
  - Model deployment is inside the ai-account module to avoid pre-flight validation issues
*/ 



/*
  Step 3: Create a Cognitive Services Project
    
*/
resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: accountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: account
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    description: projectDescription
    displayName: projectDisplayName
  }
  dependsOn: [aiAccount]
}

output accountName string = aiAccount.outputs.accountName
output projectName string = project.name
output accountEndpoint string = aiAccount.outputs.accountEndpoint
