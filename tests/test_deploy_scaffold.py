from pathlib import Path

import main


ROOT = Path(__file__).resolve().parents[1]
DEPLOYER = ROOT / "ops" / "systemd" / "openshare-autodeploy.sh"
DOCKERFILE = ROOT / "Dockerfile"


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
