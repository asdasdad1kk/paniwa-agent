"""Harness Studio: local context engineering for chat-based LLMs.

No AI provider, no network calls. The toolkit prepares high-signal prompts and
context bundles that a developer pastes into any chat assistant, then helps
review the answer and turn it into a verified patch.
"""

from __future__ import annotations

__version__ = "2.0.0"
APP_NAME = "Harness Studio"
APP_ID = "harness.studio.local"

__all__ = ["__version__", "APP_NAME", "APP_ID"]
