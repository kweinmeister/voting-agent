variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "Primary region for Cloud Run and Artifact Registry"
  type        = string
  default     = "us-central1"
}

variable "agent_region" {
  description = "Region for Agent Runtime and Model Armor (must match the agents-cli deployment)"
  type        = string
  default     = "us-east1"
}

variable "gemini_model" {
  description = "Gemini model used by the voting agent"
  type        = string
  default     = "gemini-3-flash-preview"
}

variable "agent_resource_name" {
  description = <<-EOT
    Full resource name of the deployed Agent Runtime, e.g.
    "projects/123/locations/us-east1/reasoningEngines/456".
    If empty, Terraform reads deployment_metadata.json (written by agents-cli deploy).
  EOT
  type        = string
  default     = ""
}

variable "deploy_agent" {
  description = <<-EOT
    Run `agents-cli deploy` automatically during terraform apply.
    Set to false if the agent is already deployed or you prefer to deploy separately.
    Requires agents-cli to be installed and authenticated.
  EOT
  type        = bool
  default     = false
}

variable "allow_unauthenticated" {
  description = "Allow public (unauthenticated) access to the Cloud Run frontend"
  type        = bool
  default     = true
}

variable "github_repo" {
  description = <<-EOT
    GitHub repository in "owner/repo" format.
    Set this to create Workload Identity Federation resources for GitHub Actions CI/CD.
    Leave empty to skip WIF setup.
  EOT
  type        = string
  default     = ""
}
