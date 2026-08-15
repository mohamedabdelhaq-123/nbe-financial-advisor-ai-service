"""Tests for the shared Jinja2 prompt-template environment factory (FR-004/006/007)."""

import jinja2
import pytest

from app.core.jinja import build_prompts_env


def _write(path, name, body):
    (path / name).write_text(body)


def test_missing_render_variable_raises_undefined_error(tmp_path):
    """FR-004 — a required variable omitted from .render() must raise, not render blank."""
    _write(tmp_path, "needs_var.jinja2", "hello {{ name }}")
    env = build_prompts_env(tmp_path)
    template = env.get_template("needs_var.jinja2")
    with pytest.raises(jinja2.UndefinedError):
        template.render()


def test_angle_brackets_rendered_unescaped(tmp_path):
    """FR-006 — autoescape is off; markup-like content passes through verbatim."""
    _write(tmp_path, "raw.jinja2", "content: {{ body }}")
    env = build_prompts_env(tmp_path)
    rendered = env.get_template("raw.jinja2").render(body="<b>Statement</b> total: $100")
    assert "<b>Statement</b>" in rendered
    assert "&lt;" not in rendered
    assert "&gt;" not in rendered


def test_nonexistent_directory_raises_at_build_time(tmp_path):
    """Constitution VII — a bad templates dir fails fast, no silent empty Environment."""
    missing = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        build_prompts_env(missing)


def test_environment_is_reusable_across_renders(tmp_path):
    """FR-007 — the returned Environment serves multiple template renders."""
    _write(tmp_path, "a.jinja2", "a={{ x }}")
    _write(tmp_path, "b.jinja2", "b={{ y }}")
    env = build_prompts_env(tmp_path)
    assert env.get_template("a.jinja2").render(x=1) == "a=1"
    assert env.get_template("b.jinja2").render(y=2) == "b=2"
