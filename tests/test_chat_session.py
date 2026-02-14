"""Tests for ChatSession and SessionManager."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from codesage.chat.session import ChatSession, SessionManager
from codesage.models import LLMMessage


class TestChatSession:
    def test_create_session(self):
        session = ChatSession()
        assert session.id
        assert session.created_at
        assert session.messages == []

    def test_add_user_message(self):
        session = ChatSession()
        session.add_user_message("Hello")
        assert len(session.messages) == 1
        assert session.messages[0].role == "user"
        assert session.messages[0].content == "Hello"

    def test_add_assistant_message(self):
        session = ChatSession()
        session.add_assistant_message("Hi there")
        assert len(session.messages) == 1
        assert session.messages[0].role == "assistant"
        assert session.messages[0].content == "Hi there"

    def test_updates_timestamp(self):
        session = ChatSession()
        original = session.updated_at
        session.add_user_message("test")
        assert session.updated_at >= original

    def test_get_messages_for_llm_empty(self):
        session = ChatSession()
        msgs = session.get_messages_for_llm()
        assert msgs == []

    def test_get_messages_for_llm_basic(self):
        session = ChatSession()
        session.add_user_message("Hello")
        session.add_assistant_message("Hi")
        session.add_user_message("How are you?")

        msgs = session.get_messages_for_llm(max_tokens=10000)
        assert len(msgs) == 3
        assert msgs[0].role == "user"

    def test_get_messages_for_llm_sliding_window(self):
        session = ChatSession()
        # Add many messages to exceed a small token budget
        for i in range(20):
            session.add_user_message(f"Message {i} " + "word " * 50)
            session.add_assistant_message(f"Reply {i} " + "response " * 50)

        msgs = session.get_messages_for_llm(max_tokens=500)
        # Should have fewer messages than total
        assert len(msgs) < 40
        # Should include the most recent messages
        assert msgs[-1].role == "assistant"

    def test_summary(self):
        session = ChatSession()
        session.add_user_message("What does this function do?")
        session.add_assistant_message("It calculates...")

        summary = session.summary()
        assert summary["id"] == session.id
        assert summary["message_count"] == 2
        assert "What does this function do?" in summary["preview"]

    def test_to_dict_and_from_dict(self):
        session = ChatSession(attached_code="x = 1", attached_language="python")
        session.add_user_message("Hello")
        session.add_assistant_message("Hi")

        data = session.to_dict()
        restored = ChatSession.from_dict(data)

        assert restored.id == session.id
        assert restored.attached_code == "x = 1"
        assert restored.attached_language == "python"
        assert len(restored.messages) == 2
        assert restored.messages[0].content == "Hello"

    def test_attached_code(self):
        session = ChatSession(
            attached_code="def foo(): pass",
            attached_language="python",
            attached_filename="test.py",
        )
        assert session.attached_code == "def foo(): pass"
        assert session.summary()["has_code"] is True


class TestSessionManager:
    def test_create_session(self):
        manager = SessionManager()
        session = manager.create_session()
        assert session.id
        assert manager.get_session(session.id) is session

    def test_create_session_with_code(self):
        manager = SessionManager()
        session = manager.create_session(
            code="x = 1",
            language="python",
            filename="test.py",
        )
        assert session.attached_code == "x = 1"

    def test_get_nonexistent(self):
        manager = SessionManager()
        assert manager.get_session("nonexistent") is None

    def test_list_sessions(self):
        manager = SessionManager()
        s1 = manager.create_session()
        s2 = manager.create_session()

        listing = manager.list_sessions()
        assert len(listing) == 2
        ids = {s["id"] for s in listing}
        assert s1.id in ids
        assert s2.id in ids

    def test_delete_session(self):
        manager = SessionManager()
        session = manager.create_session()
        sid = session.id

        assert manager.delete_session(sid) is True
        assert manager.get_session(sid) is None
        assert manager.delete_session(sid) is False  # already deleted

    def test_clear_session(self):
        manager = SessionManager()
        session = manager.create_session()
        session.add_user_message("hello")
        session.add_assistant_message("hi")

        assert len(session.messages) == 2
        assert manager.clear_session(session.id) is True
        assert len(session.messages) == 0

    def test_clear_nonexistent(self):
        manager = SessionManager()
        assert manager.clear_session("nope") is False

    def test_save_and_load(self, tmp_path: Path):
        manager = SessionManager(sessions_dir=tmp_path)
        session = manager.create_session(code="hello")
        session.add_user_message("test message")
        manager.save_session(session.id)

        # Verify file was created
        session_file = tmp_path / f"{session.id}.json"
        assert session_file.exists()

        # Load into new manager
        manager2 = SessionManager(sessions_dir=tmp_path)
        manager2.load_sessions()

        loaded = manager2.get_session(session.id)
        assert loaded is not None
        assert loaded.attached_code == "hello"
        assert len(loaded.messages) == 1
        assert loaded.messages[0].content == "test message"

    def test_delete_removes_file(self, tmp_path: Path):
        manager = SessionManager(sessions_dir=tmp_path)
        session = manager.create_session()
        manager.save_session(session.id)

        session_file = tmp_path / f"{session.id}.json"
        assert session_file.exists()

        manager.delete_session(session.id)
        assert not session_file.exists()

    def test_load_corrupted_file(self, tmp_path: Path):
        # Write a corrupted JSON file
        (tmp_path / "bad.json").write_text("not valid json{{{")

        manager = SessionManager(sessions_dir=tmp_path)
        manager.load_sessions()  # Should not crash
        assert len(manager.list_sessions()) == 0
