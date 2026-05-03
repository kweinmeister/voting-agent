# ── Eval service agent ────────────────────────────────────────────────────────
# Ensures the AI Platform service agent is provisioned before evals run.

resource "google_project_service_identity" "aiplatform" {
  provider = google-beta
  project  = var.project_id
  service  = "aiplatform.googleapis.com"

  depends_on = [google_project_service.apis]
}

# ── GCS bucket for eval output ────────────────────────────────────────────────

resource "google_storage_bucket" "eval_output" {
  project                     = var.project_id
  name                        = "voting-agent-evals-${var.project_id}"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true

  lifecycle_rule {
    condition { age = 90 }
    action { type = "Delete" }
  }

  depends_on = [time_sleep.api_propagation]
}

# ── Artifact Registry ─────────────────────────────────────────────────────────

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "voting-agent"
  format        = "DOCKER"
  description   = "Container images for the Voting Agent frontend"
  depends_on    = [time_sleep.api_propagation]
}

# ── Container image (built via Cloud Build) ───────────────────────────────────

resource "null_resource" "build_image" {
  triggers = {
    source_hash = local.source_hash
  }

  provisioner "local-exec" {
    command = <<-EOT
      gcloud builds submit "${path.module}/.." \
        --tag="${local.image_url}" \
        --project="${var.project_id}" \
        --quiet
    EOT
  }

  depends_on = [
    google_artifact_registry_repository.images,
    google_project_iam_member.cloudbuild_registry,
    google_project_iam_member.cloudbuild_logging,
  ]
}

# ── Model Armor prompt-screening template ─────────────────────────────────────

resource "null_resource" "model_armor_template" {
  triggers = {
    template_id = local.model_armor_template_id
    project     = var.project_id
    location    = var.agent_region
  }

  provisioner "local-exec" {
    # Use REST API directly — gcloud model-armor CLI has known ECP proxy issues
    # Idempotent: checks for HTTP 200 before creating
    command = <<-EOT
      TOKEN=$(gcloud auth application-default print-access-token)
      BASE="https://modelarmor.${var.agent_region}.rep.googleapis.com/v1/projects/${var.project_id}/locations/${var.agent_region}/templates"
      STATUS=$(curl -s -o /dev/null -w "%%{http_code}" \
        -H "Authorization: Bearer $TOKEN" \
        "$BASE/${local.model_armor_template_id}")
      if [ "$STATUS" = "200" ]; then
        echo "Model Armor template already exists, skipping."
      else
        echo "Creating Model Armor template..."
        curl -sf -X POST "$BASE?templateId=${local.model_armor_template_id}" \
          -H "Authorization: Bearer $TOKEN" \
          -H "Content-Type: application/json" \
          -d '{"filterConfig":{"raiSettings":{"raiFilters":[{"filterType":"HATE_SPEECH","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"HARASSMENT","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"SEXUALLY_EXPLICIT","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"DANGEROUS","confidenceLevel":"MEDIUM_AND_ABOVE"}]},"piAndJailbreakFilterSettings":{"filterEnforcement":"ENABLED","confidenceLevel":"HIGH"}}}' \
        || (echo "Failed to create Model Armor template" && exit 1)
        echo "Model Armor template created."
      fi
    EOT
  }

  depends_on = [time_sleep.api_propagation]
}

# ── Model Armor floor settings — Vertex AI (Agent Engine) integration ──────────
# Enables inline Model Armor screening for generateContent calls made by the
# agent runtime, populating the Agent Platform Security dashboard.

resource "null_resource" "model_armor_floor_settings" {
  triggers = {
    project             = var.project_id
    integrated_services = "AI_PLATFORM"
    enforcement         = "inspectAndBlock"
  }

  provisioner "local-exec" {
    command = <<-EOT
      TOKEN=$(gcloud auth application-default print-access-token)
      curl -sf -X PATCH \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{
          "filterConfig": {
            "raiSettings": {
              "raiFilters": [
                {"filterType":"HATE_SPEECH","confidenceLevel":"MEDIUM_AND_ABOVE"},
                {"filterType":"HARASSMENT","confidenceLevel":"MEDIUM_AND_ABOVE"},
                {"filterType":"SEXUALLY_EXPLICIT","confidenceLevel":"MEDIUM_AND_ABOVE"},
                {"filterType":"DANGEROUS","confidenceLevel":"MEDIUM_AND_ABOVE"}
              ]
            },
            "piAndJailbreakFilterSettings": {
              "filterEnforcement":"ENABLED",
              "confidenceLevel":"HIGH"
            }
          },
          "integratedServices": ["AI_PLATFORM"],
          "aiPlatformFloorSetting": {
            "inspectAndBlock": true,
            "enableCloudLogging": true
          },
          "enableFloorSettingEnforcement": true
        }' \
        "https://modelarmor.googleapis.com/v1/projects/${var.project_id}/locations/global/floorSetting" \
      || (echo "Failed to update Model Armor floor settings" && exit 1)
      echo "Model Armor floor settings updated."
    EOT
  }

  depends_on = [
    time_sleep.api_propagation,
    google_project_iam_member.aiplatform_modelarmor,
  ]
}

# ── Cloud Run frontend ─────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "frontend" {
  project             = var.project_id
  name                = "voting-agent-frontend"
  location            = var.region
  deletion_protection = false

  template {
    service_account = google_service_account.cloud_run.email
    timeout         = "3600s" # SSE streams can stay open for the full agent response

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = local.image_url

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.region
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "MODEL_ARMOR_TEMPLATE"
        value = local.model_armor_template_name
      }
      env {
        name  = "MODEL_ARMOR_LOCATION"
        value = var.agent_region
      }

      # Only set AGENT_RESOURCE_NAME when we have one — omitting it keeps local-dev mode active
      dynamic "env" {
        for_each = local.effective_agent_name != "" ? [local.effective_agent_name] : []
        content {
          name  = "AGENT_RESOURCE_NAME"
          value = env.value
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [
    null_resource.build_image,
    null_resource.model_armor_template,
    null_resource.model_armor_floor_settings,
    google_project_iam_member.cloud_run_aiplatform,
    google_project_iam_member.cloud_run_modelarmor,
  ]
}

# ── App Hub — registers the agent and frontend for Application Topology ────────
# Enables the Cloud Monitoring Topology view and apptopology.viewer access.
# Idempotent: gcloud exits 0 if the resource already exists.

resource "null_resource" "apphub_workload" {
  triggers = {
    agent_resource = local.effective_agent_name
    application    = "my-app"
  }

  provisioner "local-exec" {
    command = <<-EOT
      gcloud apphub applications workloads describe voting-agent \
        --project=${var.project_id} --location=${var.region} --application=my-app \
        --format=none 2>/dev/null \
      || gcloud apphub applications workloads create voting-agent \
           --project=${var.project_id} \
           --location=${var.region} \
           --application=my-app \
           --discovered-workload=projects/${var.project_id}/locations/${var.region}/discoveredWorkloads/apphub-00000000-0000-0000-4620-3236a5438609 \
           --display-name="Voting Agent (Agent Engine)"
    EOT
  }

  depends_on = [time_sleep.api_propagation]
}

resource "null_resource" "apphub_service" {
  triggers = {
    service     = "voting-agent-frontend"
    application = "my-app"
  }

  provisioner "local-exec" {
    command = <<-EOT
      gcloud apphub applications services describe voting-agent-frontend \
        --project=${var.project_id} --location=${var.region} --application=my-app \
        --format=none 2>/dev/null \
      || gcloud apphub applications services create voting-agent-frontend \
           --project=${var.project_id} \
           --location=${var.region} \
           --application=my-app \
           --discovered-service=projects/${var.project_id}/locations/${var.region}/discoveredServices/apphub-00000000-0000-0000-34e3-e69c07b91bc3 \
           --display-name="Voting Agent Frontend (Cloud Run)"
    EOT
  }

  depends_on = [
    google_cloud_run_v2_service.frontend,
  ]
}

# ── Online monitor — continuous evaluation of live production traffic ──────────

resource "null_resource" "online_monitor" {
  triggers = {
    agent_resource = local.effective_agent_name
    metrics        = "safety_v1,final_response_quality_v1"
    sampling_pct   = "50"
  }

  provisioner "local-exec" {
    command = <<-EOT
      python3 ${path.module}/../tests/eval/setup_monitor.py
    EOT
  }

  depends_on = [
    null_resource.model_armor_floor_settings,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = google_cloud_run_v2_service.frontend.project
  location = google_cloud_run_v2_service.frontend.location
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
