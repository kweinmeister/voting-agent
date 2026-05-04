output "frontend_url" {
  description = "Public URL of the Cloud Run frontend"
  value       = google_cloud_run_v2_service.frontend.uri
}

output "image_url" {
  description = "Container image deployed to Cloud Run"
  value       = local.image_url
}

output "model_armor_template" {
  description = "Model Armor template resource name wired into the frontend"
  value       = local.model_armor_template_name
}

output "agent_resource_name" {
  description = "Agent Runtime resource name wired into the frontend (empty = local-dev mode)"
  value       = local.effective_agent_name
}

output "cloud_run_service_account" {
  description = "Service account used by the Cloud Run frontend"
  value       = google_service_account.cloud_run.email
}

output "eval_bucket" {
  description = "GCS URI for Agent Platform eval output — use as GCS_EVAL_BUCKET"
  value       = "gs://${google_storage_bucket.eval_output.name}/evals"
}

output "next_steps" {
  description = "What to do after a fresh deploy without an Agent Runtime"
  value = (
    local.effective_agent_name == ""
    ? "Run `agents-cli deploy` from the project root, then `terraform apply` again to wire up AGENT_RESOURCE_NAME."
    : "All set. Open ${google_cloud_run_v2_service.frontend.uri} to use the app."
  )
}
