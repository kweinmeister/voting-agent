# Workload Identity Federation — lets GitHub Actions authenticate to GCP
# without storing long-lived service account keys as secrets.
#
# Usage:
#   terraform apply -var="github_repo=your-org/voting-agent"
#
# After apply, set these GitHub Actions variables in your repo settings:
#   WIF_PROVIDER  → output.wif_provider
#   GHA_SERVICE_ACCOUNT → output.gha_service_account
#   GCP_PROJECT_ID → var.project_id

resource "google_project_service" "wif_apis" {
  for_each = var.github_repo != "" ? toset([
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
  ]) : toset([])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
  depends_on         = [time_sleep.api_propagation]
}

resource "google_iam_workload_identity_pool" "github" {
  count                     = var.github_repo != "" ? 1 : 0
  project                   = var.project_id
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  depends_on                = [google_project_service.wif_apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  count                              = var.github_repo != "" ? 1 : 0
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }

  # Only tokens from this repo can use the identity pool
  attribute_condition = "assertion.repository == '${var.github_repo}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Dedicated service account for GitHub Actions CI/CD
resource "google_service_account" "github_actions" {
  count        = var.github_repo != "" ? 1 : 0
  project      = var.project_id
  account_id   = "voting-agent-cicd"
  display_name = "Voting Agent CI/CD (GitHub Actions)"
  depends_on   = [time_sleep.api_propagation]
}

# Allow the GitHub repo to impersonate this service account
resource "google_service_account_iam_member" "github_wif_binding" {
  count              = var.github_repo != "" ? 1 : 0
  service_account_id = google_service_account.github_actions[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_repo}"
}

# Permissions the CI/CD service account needs
locals {
  gha_roles = var.github_repo != "" ? [
    "roles/run.admin",                  # deploy Cloud Run services
    "roles/artifactregistry.writer",    # push container images
    "roles/cloudbuild.builds.editor",   # submit Cloud Build jobs
    "roles/storage.admin",              # Cloud Build source upload
    "roles/aiplatform.admin",           # deploy Agent Runtime
    "roles/iam.serviceAccountUser",     # deploy Cloud Run with specific SA
  ] : []
}

resource "google_project_iam_member" "github_actions_roles" {
  for_each = toset(local.gha_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.github_actions[0].email}"
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "wif_provider" {
  description = "Set as WIF_PROVIDER in GitHub Actions repo variables"
  value = (
    var.github_repo != ""
    ? google_iam_workload_identity_pool_provider.github[0].name
    : "Run terraform apply -var=github_repo=owner/repo to create WIF resources"
  )
}

output "gha_service_account" {
  description = "Set as GHA_SERVICE_ACCOUNT in GitHub Actions repo variables"
  value = (
    var.github_repo != ""
    ? google_service_account.github_actions[0].email
    : "Run terraform apply -var=github_repo=owner/repo to create WIF resources"
  )
}
