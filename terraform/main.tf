terraform {
  required_version = ">= 1.4"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 7.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

data "google_project" "project" {
  project_id = var.project_id
}

# ── APIs ─────────────────────────────────────────────────────────────────────

resource "google_project_service" "apis" {
  for_each = toset([
    "aiplatform.googleapis.com",
    "modelarmor.googleapis.com",
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudtrace.googleapis.com",
    "bigquery.googleapis.com",
    "logging.googleapis.com",
    "compute.googleapis.com", # ensures compute SA exists for Cloud Build
  ])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# Give APIs time to propagate and create their default service accounts
resource "time_sleep" "api_propagation" {
  depends_on      = [google_project_service.apis]
  create_duration = "30s"
}

# ── Locals ───────────────────────────────────────────────────────────────────

locals {
  # Short hash of key source files — drives image tag and triggers Cloud Run update
  source_hash = substr(sha256(join(",", [
    filemd5("${path.module}/../Dockerfile"),
    filemd5("${path.module}/../uv.lock"),
    filemd5("${path.module}/../app/agent.py"),
    filemd5("${path.module}/../frontend/main.py"),
    filemd5("${path.module}/../frontend/static/voting.js"),
  ])), 0, 8)

  image_url = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}/voting-agent-frontend:${local.source_hash}"

  model_armor_template_id   = "voting-agent-template"
  model_armor_template_name = "projects/${var.project_id}/locations/${var.agent_region}/templates/${local.model_armor_template_id}"

  # Resolve agent resource name: explicit var > deployment_metadata.json > ""
  _metadata_file       = "${path.module}/../deployment_metadata.json"
  _metadata            = try(jsondecode(file(local._metadata_file)), {})
  effective_agent_name = (
    var.agent_resource_name != ""
    ? var.agent_resource_name
    : try(local._metadata["remote_agent_runtime_id"], "")
  )
}
