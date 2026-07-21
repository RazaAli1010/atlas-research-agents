"""Calculator tool: safe arithmetic evaluation for pricing math (F3).

Implemented with ``ast`` parsing — **never** ``eval``/``exec`` — so hostile input
like ``__import__("os").system(...)`` or ``().__class__`` cannot execute. Only a
small allowlist of arithmetic node/operator types is accepted; anything else
returns a plain error string the model can read and recover from.
"""

import ast
import operator
from collections.abc import Callable

from langchain_core.tools import tool

# Allowed binary / unary operators → their Python implementation.
_BIN_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Guard against CPU/memory blowups from huge exponents (e.g. ``2 ** 9999999``).
_MAX_EXPONENT = 100


class _UnsafeExpression(ValueError):
    """Raised when the expression contains a disallowed node or operator."""


def _eval(node: ast.AST) -> float:
    """Recursively evaluate an allowlisted arithmetic AST node."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            # Reject strings, bytes, None, booleans — numbers only.
            raise _UnsafeExpression("only numeric constants are allowed")
        return float(node.value)

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        impl = _BIN_OPS.get(op_type)
        if impl is None:
            raise _UnsafeExpression(f"operator {op_type.__name__} is not allowed")
        left, right = _eval(node.left), _eval(node.right)
        if op_type is ast.Pow and abs(right) > _MAX_EXPONENT:
            raise _UnsafeExpression("exponent too large")
        return impl(left, right)

    if isinstance(node, ast.UnaryOp):
        impl_u = _UNARY_OPS.get(type(node.op))
        if impl_u is None:
            raise _UnsafeExpression(f"operator {type(node.op).__name__} is not allowed")
        return impl_u(_eval(node.operand))

    # Name, Call, Attribute, Subscript, comprehensions, str constants, etc.
    raise _UnsafeExpression(f"node {type(node).__name__} is not allowed")


@tool
def calculator(expression: str) -> str:
    """Evaluate a basic arithmetic expression and return the numeric result.

    Use this for pricing math: sums, differences, products, division,
    percentages, and powers — e.g. "(19.99 * 12) * 0.8" for an annual discounted
    price. Supported operators: + - * / // % ** and unary + / -. Parentheses are
    allowed. Only numbers and these operators are permitted; variables, function
    calls, and text are rejected.

    Args:
        expression: The arithmetic expression to evaluate, e.g. "100 / 12 * 1.2".

    Returns:
        The result as a string (e.g. "14"), or a message starting with "Error:"
        if the expression is invalid or unsupported.
    """
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval(tree.body)
    except _UnsafeExpression:
        return "Error: unsupported expression"
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError):
        return "Error: unsupported expression"

    # Render whole numbers without a trailing ".0" for readability.
    if result == int(result):
        return str(int(result))
    return str(result)
