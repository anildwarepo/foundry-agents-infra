using './main.bicep'

param location = 'westus'
param isolationMode = 'AllowOnlyApprovedOutbound'
param aiServices = 'aiservices'
param firstProjectName = 'project'
param projectDescription = 'A project for the AI Foundry account with managed network secured deployed Agent'
param displayName = 'project'
param peSubnetName = 'pe-subnet'

// Resource IDs for existing resources
param existingVnetResourceId = '/subscriptions/e4718866-4e88-411f-a0b8-10c8051dc165/resourceGroups/vnet/providers/Microsoft.Network/virtualNetworks/vnet-westus'
param vnetName = 'vnet-westus'
param aiSearchResourceId = ''
param azureStorageAccountResourceId = ''
param azureCosmosDBAccountResourceId = ''

// API Management configuration (optional)
param apiManagementResourceId = ''

// Pass the DNS zone map here
// Use existing DNS zones from the 'vnet' resource group where available
param existingDnsZones = {
  'privatelink.services.ai.azure.com': 'vnet'
  'privatelink.openai.azure.com': 'vnet'
  'privatelink.cognitiveservices.azure.com': 'vnet'
  'privatelink.search.windows.net': 'ai-foundry-vnet'
  'privatelink.blob.core.windows.net': 'vnet'
  'privatelink.documents.azure.com': 'vnet'
  'privatelink.azure-api.net': ''
}

//DNSZones names for validating if they exist
param dnsZoneNames = [
  'privatelink.services.ai.azure.com'
  'privatelink.openai.azure.com'
  'privatelink.cognitiveservices.azure.com'
  'privatelink.search.windows.net'
  'privatelink.blob.core.windows.net'
  'privatelink.documents.azure.com'
  'privatelink.azure-api.net'
]


// Network configuration: subnet prefix for the new pe-subnet in the existing VNet
param vnetAddressPrefix = ''
param peSubnetPrefix = '10.0.4.0/24'

