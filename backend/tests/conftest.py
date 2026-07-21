"""Pytest fixtures / bootstrap.

Set dummy values for the required env vars *before* any test imports
``app.config`` / ``app.main`` (which build the module-level Settings singleton at
import time). Only fills values that aren't already set, so a real local ``.env``
or CI job env still wins.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test-openai")
os.environ.setdefault("TAVILY_API_KEY", "tvly-test-tavily")
