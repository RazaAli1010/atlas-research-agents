"""Atlas evaluation harness (F8).

Runs the agent against a fixed benchmark topic set and grades each run
(structure, citation, coverage, groundedness) to report task success rate,
trajectory stats, cost, and latency. Importable as ``evals.*`` from the backend
root (where pytest and ``uv run`` execute).
"""
