"""Conversational assistant over the existing analysis.

Layered so that no single component is trusted to behave:

``scope``   decides in Python whether a question may be answered at all.
``tools``   the only path to the complaint data, survey model and loan maths.
``model``   the seam a real LLM client drops into, plus deterministic stubs.
``guard``   checks the finished reply for ranking, verdicts and invented figures.

Importing the package registers the system-authored refusal strings with the
guard, so a refusal is not mistaken for a violation of its own rules.
"""

from app.chat import guard as _guard

_guard.register_system_texts({})
