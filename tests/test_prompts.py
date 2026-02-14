"""Tests for prompt management."""

from pathlib import Path

import pytest

from codesage.llm.prompts import PromptManager
from codesage.models import CommandType, LLMRequest


@pytest.fixture
def prompt_manager() -> PromptManager:
    templates_dir = Path(__file__).parent.parent / "templates"
    return PromptManager(templates_dir)


class TestPromptManager:
    def test_render_explain(self, prompt_manager: PromptManager):
        request = LLMRequest(
            command=CommandType.explain,
            code="def hello(): return 'world'",
            language="python",
            filename="test.py",
        )
        messages = prompt_manager.render(request)
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert "def hello()" in messages[0].content
        assert "python" in messages[0].content
        assert "test.py" in messages[0].content
        assert "Summary" in messages[0].content

    def test_render_improve(self, prompt_manager: PromptManager):
        request = LLMRequest(
            command=CommandType.improve,
            code="x = 1\ny = 2",
            language="python",
        )
        messages = prompt_manager.render(request)
        assert len(messages) == 1
        assert "Quality Rating" in messages[0].content
        assert "x = 1" in messages[0].content

    def test_render_chat(self, prompt_manager: PromptManager):
        request = LLMRequest(
            command=CommandType.chat,
            code="class Foo: pass",
            language="python",
            context="What does this class do?",
        )
        messages = prompt_manager.render(request)
        assert len(messages) == 1
        assert "class Foo" in messages[0].content

    def test_render_with_context(self, prompt_manager: PromptManager):
        request = LLMRequest(
            command=CommandType.explain,
            code="x = 1",
            language="python",
            context="This is part of a larger module.",
        )
        messages = prompt_manager.render(request)
        assert "larger module" in messages[0].content

    def test_render_minimal(self, prompt_manager: PromptManager):
        request = LLMRequest(
            command=CommandType.explain,
            code="x = 1",
        )
        messages = prompt_manager.render(request)
        assert "x = 1" in messages[0].content
