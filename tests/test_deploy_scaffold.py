from pathlib import Path

import main


ROOT = Path(__file__).resolve().parents[1]
DEPLOYER = ROOT / "ops" / "systemd" / "openshare-autodeploy.sh"
DOCKERFILE = ROOT / "Dockerfile"
PUBLIC_COMPOSE = ROOT / "docker-compose.public.yml"
CONTAINER_WORKFLOW = ROOT / ".github" / "workflows" / "container-release.yml"
DOCKERHUB_OVERVIEW = ROOT / "docs" / "dockerhub" / "openshare.md"
VITE_CONFIG = ROOT / "web" / "vite.config.ts"
BASE_TEMPLATE = ROOT / "templates" / "base.html"


def test_deployer_gates_the_exact_main_sha_and_health_version():
    source = DEPLOYER.read_text(encoding="utf-8")

    assert "head_sha=${sha}&event=push" in source
    assert '.name == $workflow and .head_sha == $sha and .event == "push"' in source
    assert '.status == "ok" and .version == $version' in source
    assert 'DB_PATH and STORAGE_PATH must be absolute host paths' in source
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == main.APP_VERSION


def test_runtime_image_contains_every_local_application_module():
    source = DOCKERFILE.read_text(encoding="utf-8")

    for module in ("main.py", "auth.py", "db.py", "mirror.py", "thumbs.py"):
        assert module in source, f"Docker runtime image does not copy {module}"
    assert "FROM --platform=$BUILDPLATFORM node:22-alpine AS web-build" in source


def test_react_chunks_use_the_fastapi_static_mount():
    vite_config = VITE_CONFIG.read_text(encoding="utf-8")
    base_template = BASE_TEMPLATE.read_text(encoding="utf-8")

    assert "base: '/static/react/'" in vite_config
    assert 'src="/static/react/assets/openshare.js?v={{ app_version }}"' in base_template
    assert 'href="/static/react/assets/openshare.css?v={{ app_version }}"' in base_template
    assert 'href="/static/style.css?v={{ app_version }}"' in base_template


def test_public_container_release_is_ci_gated_and_multi_arch():
    workflow = CONTAINER_WORKFLOW.read_text(encoding="utf-8")
    compose = PUBLIC_COMPOSE.read_text(encoding="utf-8")

    assert "workflow_run:" in workflow
    assert "timeout-minutes: 20" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in workflow
    assert "platforms: linux/amd64,linux/arm64" in workflow
    assert "ghcr.io/minionenjoyer/openshare" in workflow
    assert "vars.DOCKERHUB_USERNAME" in workflow
    assert "vars.DOCKERHUB_NAMESPACE" in workflow
    assert "secrets.DOCKERHUB_TOKEN" in workflow
    assert "docker buildx imagetools create" in workflow
    assert "peter-evans/dockerhub-description@1b9a80c056b620d92cedb9d9b5a223409c68ddfa" in workflow
    assert "readme-filepath: docs/dockerhub/openshare.md" in workflow
    assert DOCKERHUB_OVERVIEW.read_text(encoding="utf-8").startswith("# OpenShare\n")
    assert "push-to-registry: true" in workflow
    assert "${OPENSHARE_IMAGE:-ghcr.io/minionenjoyer/openshare}:${OPENSHARE_VERSION:-latest}" in compose
