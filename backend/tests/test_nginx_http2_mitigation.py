from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/nginx_http2_mitigation.py"
spec = importlib.util.spec_from_file_location("nginx_http2_mitigation", SCRIPT)
assert spec is not None and spec.loader is not None
mitigation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mitigation)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "server {\n    listen 443 ssl http2;\n    server_name example.test;\n}\n",
            "server {\n    listen 443 ssl;\n    server_name example.test;\n}\n",
        ),
        (
            "server {\n    listen 443 ssl;\n    http2 on;\n    server_name example.test;\n}\n",
            "server {\n    listen 443 ssl;\n\n    server_name example.test;\n}\n",
        ),
    ],
)
def test_disable_http2_supports_old_and_current_nginx_syntax(source: str, expected: str) -> None:
    assert mitigation.disable_http2(source, name="portal") == expected


def test_disable_http2_rejects_unknown_or_ambiguous_listener_syntax() -> None:
    with pytest.raises(ValueError, match="exactly one recognized"):
        mitigation.disable_http2("server { listen 443 ssl; }", name="portal")
    with pytest.raises(ValueError, match="exactly one recognized"):
        mitigation.disable_http2(
            "server { listen 443 ssl http2; http2 on; }", name="portal"
        )


def test_prepare_overlay_preserves_allowlist_and_source_files(tmp_path: Path) -> None:
    sources = {
        "portal": ROOT / "nginx/nginx.prod.conf",
        "grafana": ROOT / "nginx/grafana.prod.conf.template",
        "support": ROOT / "nginx/support.prod.conf",
    }
    original = {key: path.read_bytes() for key, path in sources.items()}
    output = tmp_path / "http2-off"

    hashes = mitigation.prepare_overlay(sources, output)

    assert set(hashes) == {
        "portal.conf",
        "grafana.conf.template",
        "support.conf",
        "compose.no-http2.yml",
        "compose.patched-image.yml",
    }
    assert {key: path.read_bytes() for key, path in sources.items()} == original
    for filename in (
        "portal.conf",
        "grafana.conf.template",
        "support.conf",
    ):
        text = (output / filename).read_text()
        assert "listen 443 ssl http2;" not in text
        assert "http2 on;" not in text
    support = (output / "support.conf").read_text()
    assert "include /etc/nginx/ssl/support-allowlist.conf;" in support
    assert "    deny all;" in support

    override = yaml.safe_load((output / "compose.no-http2.yml").read_text())
    volumes = override["services"]["nginx"]["volumes"]
    assert {volume["target"] for volume in volumes} == {
        "/etc/nginx/conf.d/default.conf",
        "/etc/nginx/templates/grafana.conf.template",
        "/etc/nginx/conf.d/support.conf",
    }
    assert all(volume["read_only"] is True for volume in volumes)
    assert all(Path(volume["source"]).is_absolute() for volume in volumes)

    image_override = yaml.safe_load((output / "compose.patched-image.yml").read_text())
    assert image_override["services"]["nginx"]["image"] == mitigation.PATCHED_IMAGE
    assert image_override["services"]["nginx"]["pull_policy"] == "never"


def test_prepare_overlay_does_not_overwrite_existing_output(tmp_path: Path) -> None:
    sources = {
        "portal": ROOT / "nginx/nginx.prod.conf",
        "grafana": ROOT / "nginx/grafana.prod.conf.template",
        "support": ROOT / "nginx/support.prod.conf",
    }
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "operator-evidence"
    sentinel.write_text("keep")

    with pytest.raises(ValueError, match="must be new"):
        mitigation.prepare_overlay(sources, output)

    assert sentinel.read_text() == "keep"


def test_support_transform_refuses_to_remove_allowlist_or_deny_all() -> None:
    source = (ROOT / "nginx/support.prod.conf").read_text()
    with pytest.raises(ValueError, match="allowlist and deny-all"):
        mitigation.disable_http2(source.replace("    deny all;\n", ""), name="support")
