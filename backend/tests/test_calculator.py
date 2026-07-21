"""Calculator computes arithmetic and rejects unsafe input without executing it."""

import pytest

from app.tools.calculator import calculator


def _calc(expr: str) -> str:
    return calculator.invoke({"expression": expr})


def test_basic_arithmetic() -> None:
    assert _calc("2 + 3 * 4") == "14"
    assert float(_calc("(100 / 13) * 1.2")) == pytest.approx((100 / 13) * 1.2)
    assert _calc("-5 + 2") == "-3"
    assert _calc("2 ** 8") == "256"
    # Whole-number results render without a trailing ".0".
    assert _calc("(100 / 12) * 1.2") == "10"


@pytest.mark.parametrize(
    "expr",
    [
        '__import__("os").system("echo hi")',
        "().__class__",
        "os.getcwd()",
        "abs(-1)",
        "2 ** 9999",  # exponent guard
        "'a' * 5",
        "x + 1",
    ],
)
def test_rejects_unsafe(expr: str) -> None:
    result = _calc(expr)
    assert result.startswith("Error:")
