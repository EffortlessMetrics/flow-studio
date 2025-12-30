"""
claude/ - Claude step engine implementation.

This subpackage implements the ClaudeStepEngine with lifecycle-aware execution.

Modules:
- engine.py: Main ClaudeStepEngine class with mode selection and lifecycle methods
- prompt_builder.py: Prompt construction with ContextPack support
- router.py: Microloop termination and routing session
- envelope.py: HandoffEnvelope creation and writing
"""

from .engine import ClaudeStepEngine

__all__ = ["ClaudeStepEngine"]
