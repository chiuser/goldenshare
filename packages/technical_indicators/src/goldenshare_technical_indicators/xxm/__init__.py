"""Quantitative structure recognition using completed bars and their MACD values."""

from .calculator import XxmCalculator
from .spec import MAIN_SPEC, XxmSpec
from .types import XxmBar

__all__ = ["MAIN_SPEC", "XxmBar", "XxmCalculator", "XxmSpec"]
