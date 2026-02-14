"""Chat session and session manager."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import litellm

from codesage.models import LLMMessage

logger = logging.getLogger(__name__)

DEFAULT_SESSIONS_DIR = Path.home() / ".local" / "share" / "codesage" / "sessions"


@dataclass
class ChatSession:
    """A single chat conversation with history."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    messages: list[LLMMessage] = field(default_factory=list)
    attached_code: str = ""
    attached_language: str = ""
    attached_filename: str = ""

    def add_user_message(self, content: str) -> None:
        """Add a user message to the session."""
        self.messages.append(LLMMessage(role="user", content=content))
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message to the session."""
        self.messages.append(LLMMessage(role="assistant", content=content))
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def get_messages_for_llm(
        self,
        max_tokens: int = 8000,
        model: str = "gpt-4o-mini",
    ) -> list[LLMMessage]:
        """Get messages for the LLM with sliding window token management.

        Keeps the system message (if present) and as many recent messages
        as fit within the token budget.

        Args:
            max_tokens: Maximum tokens for conversation history.
            model: Model name for token counting.

        Returns:
            List of LLMMessages within the token budget.
        """
        if not self.messages:
            return []

        # Separate system messages from conversation
        system_msgs = [m for m in self.messages if m.role == "system"]
        conv_msgs = [m for m in self.messages if m.role != "system"]

        # Count system message tokens
        system_tokens = 0
        for msg in system_msgs:
            try:
                system_tokens += litellm.token_counter(model=model, text=msg.content or "")
            except Exception:
                system_tokens += len(msg.content or "") // 4

        available = max_tokens - system_tokens
        if available <= 0:
            return system_msgs

        # Sliding window: include messages from the end
        selected: list[LLMMessage] = []
        current_tokens = 0

        for msg in reversed(conv_msgs):
            try:
                msg_tokens = litellm.token_counter(model=model, text=msg.content or "")
            except Exception:
                msg_tokens = len(msg.content or "") // 4

            if current_tokens + msg_tokens > available:
                break
            selected.insert(0, msg)
            current_tokens += msg_tokens

        return system_msgs + selected

    def summary(self) -> dict:
        """Return a compact summary of the session."""
        first_user = ""
        for msg in self.messages:
            if msg.role == "user" and msg.content:
                first_user = msg.content[:100]
                break

        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
            "preview": first_user,
            "has_code": bool(self.attached_code),
        }

    def to_dict(self) -> dict:
        """Serialize session to dict for persistence."""
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.model_dump(exclude_none=True) for m in self.messages],
            "attached_code": self.attached_code,
            "attached_language": self.attached_language,
            "attached_filename": self.attached_filename,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChatSession:
        """Deserialize session from dict."""
        messages = [LLMMessage(**m) for m in data.get("messages", [])]
        return cls(
            id=data["id"],
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            messages=messages,
            attached_code=data.get("attached_code", ""),
            attached_language=data.get("attached_language", ""),
            attached_filename=data.get("attached_filename", ""),
        )


class SessionManager:
    """Manages chat sessions with optional file persistence."""

    def __init__(self, sessions_dir: Path | None = None) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR

    def create_session(
        self,
        code: str = "",
        language: str = "",
        filename: str = "",
    ) -> ChatSession:
        """Create a new chat session."""
        session = ChatSession(
            attached_code=code,
            attached_language=language,
            attached_filename=filename,
        )
        self._sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        """List all sessions as summaries."""
        return [s.summary() for s in self._sessions.values()]

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            # Remove persisted file
            path = self._sessions_dir / f"{session_id}.json"
            if path.exists():
                path.unlink()
            return True
        return False

    def clear_session(self, session_id: str) -> bool:
        """Clear a session's message history. Returns True if it existed."""
        session = self._sessions.get(session_id)
        if session:
            session.messages.clear()
            session.updated_at = datetime.now(timezone.utc).isoformat()
            self.save_session(session_id)
            return True
        return False

    def save_session(self, session_id: str) -> None:
        """Persist a session to disk."""
        session = self._sessions.get(session_id)
        if not session:
            return

        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self._sessions_dir / f"{session_id}.json"
        path.write_text(json.dumps(session.to_dict(), indent=2))

    def load_sessions(self) -> None:
        """Load all sessions from disk."""
        if not self._sessions_dir.exists():
            return

        for path in self._sessions_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                session = ChatSession.from_dict(data)
                self._sessions[session.id] = session
            except Exception as e:
                logger.warning("Failed to load session %s: %s", path.name, e)
