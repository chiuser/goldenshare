"""Technical indicator contracts. D1 does not expose a placeholder calculator.

The executable calculate entry point and built-in factories arrive with D3.
Importing this package performs no source access or connection creation.
"""

from .contracts import CalculationInstance, CalculationRequest, CalculationResult

__all__ = ["CalculationInstance", "CalculationRequest", "CalculationResult"]
