"""Role->model routing + usage tracking. Stubbed in F2, fully built in F9.

Every LLM call must go through this router; nodes never instantiate model clients
directly (SHARED CONTEXT §2.5).
"""
