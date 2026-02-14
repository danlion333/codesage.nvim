"""Jinja2-based prompt management for CodeSage."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from codesage.models import CommandType, LLMMessage, LLMRequest


class PromptManager:
    """Manages Jinja2 prompt templates for LLM requests."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        if templates_dir is None:
            # Default: templates/ directory at project root
            templates_dir = Path(__file__).parent.parent.parent.parent / "templates"
        self._env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, request: LLMRequest) -> list[LLMMessage]:
        """Render a prompt template into LLM messages.

        Args:
            request: The LLM request containing command type and context.

        Returns:
            List of LLMMessage objects ready for the provider.

        Raises:
            TemplateNotFound: If the template for the command doesn't exist.
        """
        template_name = f"{request.command.value}.j2"
        template = self._env.get_template(template_name)

        rendered = template.render(
            code=request.code,
            language=request.language,
            filename=request.filename,
            context=request.context,
            query=request.context,  # For chat template
        )

        return [LLMMessage(role="user", content=rendered)]

    def render_with_system(
        self,
        request: LLMRequest,
        system_template: str,
        template_vars: dict | None = None,
    ) -> list[LLMMessage]:
        """Render a user prompt with a system message prepended.

        Args:
            request: The LLM request.
            system_template: Name of the system template file (e.g., "system_agentic.j2").
            template_vars: Extra variables for the system template.

        Returns:
            List of LLMMessages starting with the system message.
        """
        # Render user message
        user_messages = self.render(request)

        # Render system message
        sys_template = self._env.get_template(system_template)
        sys_vars = {
            "code": request.code,
            "language": request.language,
            "filename": request.filename,
            "context": request.context,
        }
        if template_vars:
            sys_vars.update(template_vars)

        system_content = sys_template.render(**sys_vars)

        return [LLMMessage(role="system", content=system_content)] + user_messages
