# Optional: deploy the ADK agent to Vertex AI Agent Runtime via agents-cli.
#
# Set var.deploy_agent = true to include this in terraform apply.
# The deployment writes deployment_metadata.json in the project root, which
# subsequent terraform applies read to wire up AGENT_RESOURCE_NAME in Cloud Run.
#
# Note: agents-cli deploy can take 10+ minutes. Requires agents-cli to be
# installed (`uv tool install google-agents-cli`) and gcloud to be authenticated.

resource "null_resource" "agent_deploy" {
  count = var.deploy_agent ? 1 : 0

  triggers = {
    agent_hash = filemd5("${path.module}/../app/agent.py")
    pyproject  = filemd5("${path.module}/../pyproject.toml")
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    command     = "agents-cli deploy"
  }

  depends_on = [time_sleep.api_propagation]
}
