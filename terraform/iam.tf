# ── Cloud Run service account ─────────────────────────────────────────────────

resource "google_service_account" "cloud_run" {
  account_id   = "voting-agent-frontend"
  display_name = "Voting Agent Frontend (Cloud Run)"
  project      = var.project_id
  depends_on   = [time_sleep.api_propagation]
}

resource "google_project_iam_member" "cloud_run_aiplatform" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

resource "google_project_iam_member" "cloud_run_modelarmor" {
  project = var.project_id
  role    = "roles/modelarmor.user"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Allow the Vertex AI service agent to call Model Armor so the floor-settings
# integration can screen generateContent calls made inside Agent Engine.
resource "google_project_iam_member" "aiplatform_modelarmor" {
  project    = var.project_id
  role       = "roles/modelarmor.user"
  member     = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
  depends_on = [google_project_service_identity.aiplatform]
}

resource "google_project_iam_member" "cloud_run_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

# ── Cloud Build service accounts ──────────────────────────────────────────────
# GCP uses different default SAs for Cloud Build depending on project age:
#   - Newer projects (post-April 2024): PROJECT_NUMBER-compute@developer.gserviceaccount.com
#   - Older projects:                  PROJECT_NUMBER@cloudbuild.gserviceaccount.com
# Both are granted Artifact Registry writer so the image push works either way.

resource "google_project_iam_member" "cloudbuild_registry" {
  for_each = toset([
    "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com",
    "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com",
  ])
  project    = var.project_id
  role       = "roles/artifactregistry.writer"
  member     = each.key
  depends_on = [time_sleep.api_propagation]
}

resource "google_project_iam_member" "cloudbuild_logging" {
  for_each = toset([
    "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com",
    "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com",
  ])
  project    = var.project_id
  role       = "roles/logging.logWriter"
  member     = each.key
  depends_on = [time_sleep.api_propagation]
}
