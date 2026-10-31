"""Independent literal rule cases from the current product LLD §14.

The input/expected event and state timelines below were transcribed from RC01–69,
not captured from either calculator.  Bookkeeping assertions independently apply
the documented extrema/identity formulas to those literal, expected segments.
These synthetic indicator values do not claim an EMA-consistent market replay.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib

import pytest

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


DATES = ("2023-01-03", "2023-01-04", "2023-01-05", "2023-01-06",
         "2023-01-09", "2023-01-10", "2023-01-11", "2023-01-12",
         "2023-01-13", "2023-01-16", "2023-01-17", "2023-01-18")
PERIODS = ("day", "m60", "m90", "m120")
# A activation; T/F structure by DIF/flip; R return; C/X cancel by DIF/flip.
EVENTS = {"A": ("DULL", "activation"), "T": ("STRUCTURE", "dif_turn"),
          "F": ("STRUCTURE", "color_flip"), "R": ("DULL", "dif_return"),
          "C": ("CANCEL", "dif_break"), "X": ("CANCEL", "dif_break_on_flip")}
STATES = {"N": "NONE", "D": "DULL", "S": "STRUCTURE"}


@dataclass(frozen=True)
class Trace:
    values: tuple
    states: str
    segments: tuple[int, ...]  # Signed, one-based starting row; 0 means no wave.
    counts: tuple[int, ...]
    refs: tuple[int, ...]  # One-based start of the manually selected old segment.
    events: str  # One literal token per row, '-' means no event.


def trace(values, states, segments, counts, refs=None, events=None):
    size = len(values)
    result = Trace(tuple(values), states, tuple(segments), tuple(counts),
                   tuple(refs or (0,) * size), events or "-" * size)
    assert all(len(part) == size for part in (
        result.states, result.segments, result.counts, result.refs, result.events))
    return result


def extend(base, values, states, segments, counts, refs=None, events=None):
    tail = trace(values, states, segments, counts, refs, events)
    return Trace(base.values + tail.values, base.states + tail.states,
                 base.segments + tail.segments, base.counts + tail.counts,
                 base.refs + tail.refs, base.events + tail.events)


T = trace([(100, 200, 2), (90, 0, -2), (101, 100, 2), (102, 100, 2)],
          "NNND", [1, -2, 3, 3], [1, 1, 1, 2], [0, 0, 0, 1], "---A")
B = trace([(100, -200, -2), (110, 0, 2), (99, -100, -2), (98, -100, -2)],
          "NNND", [-1, 2, -3, -3], [1, 1, 1, 2], [0, 0, 0, 1], "---A")
TS = extend(T, [(103, 99, 2)], "S", [3], [3], [1], "T")
BS = extend(B, [(97, -99, -2)], "S", [-3], [3], [1], "T")
ABT = trace([(100, 300, 2), (90, 0, -2), (120, 200, 2), (110, 0, -2)],
            "NNNN", [1, -2, 3, -4], [1, 1, 1, 1])
ABB = trace([(100, -300, -2), (110, 0, 2), (80, -200, -2), (90, 0, 2)],
            "NNNN", [-1, 2, -3, 4], [1, 1, 1, 1])
ABTD = extend(ABT, [(130, 100, 2), (131, 100, 2)], "ND", [5, 5], [1, 2], [0, 3], "-A")
ABBD = extend(ABB, [(70, -100, -2), (69, -100, -2)], "ND", [-5, -5], [1, 2], [0, 3], "-A")


CASES = []


def case(number, name, data):
    CASES.append(pytest.param(number, data, id=f"RC-{number:02d}-{name}"))
    return data


case(1, "leading-zero", trace([(100, 0, 0), (101, 1, 0), (102, 2, 2)], "NNN", [0, 0, 3], [0, 0, 1]))
case(2, "red-zero-red", trace([(100, 10, 2), (105, 11, 0), (104, 10, 2)], "NNN", [1, 1, 1], [1, 1, 2]))
case(3, "red-zero-green", extend(T, [(103, 100, 0), (90, 99, -2)], "DN", [3, -6], [2, 1], [1, 0], "-F"))
case(4, "green-zero-red", extend(B, [(97, -100, 0), (110, -99, 2)], "DN", [-3, 6], [2, 1], [1, 0], "-F"))
for number, name, values, states, segs, counts, refs, events in [
    (5, "top", [(100,200,2),(90,0,-2),(99,100,2),(99,100,2),(101,100,0)], "NNNND", [1,-2,3,3,3], [1,1,1,2,2], [0,0,0,0,1], "----A"),
    (5, "bottom", [(100,-200,-2),(110,0,2),(101,-100,-2),(101,-100,-2),(99,-100,0)], "NNNND", [-1,2,-3,-3,-3], [1,1,1,2,2], [0,0,0,0,1], "----A"),
    (6, "top", [(100,200,2),(90,0,-2),(101,100,2),(102,100,0),(103,100,0),(104,100,2)], "NNNNND", [1,-2,3,3,3,3], [1,1,1,1,1,2], [0,0,0,0,0,1], "-----A"),
    (6, "bottom", [(100,-200,-2),(110,0,2),(99,-100,-2),(98,-100,0),(97,-100,0),(96,-100,-2)], "NNNNND", [-1,2,-3,-3,-3,-3], [1,1,1,1,1,2], [0,0,0,0,0,1], "-----A"),
    (7, "split-top-extrema", [(100,200,2),(105,190,2),(104,210,2),(90,0,-2),(106,100,2),(107,101,2)], "NNNNND", [1,1,1,-4,5,5], [1,2,3,1,1,2], [0,0,0,0,0,1], "-----A"),
    (8, "split-bottom-extrema", [(100,-200,-2),(95,-190,-2),(96,-210,-2),(110,0,2),(94,-100,-2),(93,-101,-2)], "NNNNND", [-1,-1,-1,4,-5,-5], [1,2,3,1,1,2], [0,0,0,0,0,1], "-----A"),
    (9, "equal-top-extrema", [(100,200,2),(100,200,2),(90,0,-2)], "NNN", [1,1,-3], [1,2,1], None, None),
    (9, "equal-bottom-extrema", [(100,-200,-2),(100,-200,-2),(110,0,2)], "NNN", [-1,-1,3], [1,2,1], None, None),
    (10, "flip-excludes-huge-close", [(100,200,2),(500,500,-2)], "NN", [1,-2], [1,1], None, None),
    (10, "flip-excludes-deep-dif", [(100,-200,-2),(50,-500,2)], "NN", [-1,2], [1,1], None, None),
]:
    case(number, name, trace(values, states, segs, counts, refs, events))
case(11, "second-red", T)
case(12, "second-green", B)
case(13, "no-borrowed-high", trace([(100,200,2),(90,0,-2),(101,100,2),(99,100,2)], "NNNN", [1,-2,3,3], [1,1,1,2]))
case(14, "no-borrowed-low", trace([(100,-200,-2),(110,0,2),(99,-100,-2),(101,-100,-2)], "NNNN", [-1,2,-3,-3], [1,1,1,2]))

TOP_EQUAL_DIF = trace([(100,200,2),(90,0,-2),(101,200,2),(102,200,2)], "NNNN", [1,-2,3,3], [1,1,1,2])
BOTTOM_EQUAL_DIF = trace([(100,-200,-2),(110,0,2),(99,-200,-2),(98,-200,-2)], "NNNN", [-1,2,-3,-3], [1,1,1,2])
for name, rows, segs in [
    ("top", [(100,200,2),(90,0,-2),(101,100,2),(102,200,2)], [1,-2,3,3]),
    ("bottom", [(100,-200,-2),(110,0,2),(99,-100,-2),(98,-200,-2)], [-1,2,-3,-3]),
]:
    case(15, name, trace(rows, "NNNN", segs, [1,1,1,2]))
case(16, "broken-bottom-cannot-recover", trace([(100,-200,-2),(110,0,2),(99,-201,-2),(98,-100,-2),(97,-99,-2)], "NNNNN", [-1,2,-3,-3,-3], [1,1,1,2,3]))
case(17, "broken-top-cannot-recover", trace([(100,200,2),(90,0,-2),(101,201,2),(102,100,2),(103,99,2)], "NNNNN", [1,-2,3,3,3], [1,1,1,2,3]))
case(18, "top-price-equal-then-strict", trace([(100,200,2),(90,0,-2),(100,100,2),(100,100,2),(100.01,100,2)], "NNNND", [1,-2,3,3,3], [1,1,1,2,3], [0,0,0,0,1], "----A"))
case(18, "bottom-price-equal-then-strict", trace([(100,-200,-2),(110,0,2),(100,-100,-2),(100,-100,-2),(99.99,-100,-2)], "NNNND", [-1,2,-3,-3,-3], [1,1,1,2,3], [0,0,0,0,1], "----A"))
case(19, "top-equal-not-broken", TOP_EQUAL_DIF)
case(19, "bottom-equal-not-broken", BOTTOM_EQUAL_DIF)
case(20, "top-weak-by-001", extend(TOP_EQUAL_DIF, [(103,199.999,2)], "D", [3], [3], [1], "A"))
case(20, "bottom-weak-by-001", extend(BOTTOM_EQUAL_DIF, [(97,-199.999,-2)], "D", [-3], [3], [1], "A"))
case(21, "top-current-positive-only", trace([(100,200,2),(90,0,-2),(101,1,2),(102,0,2),(103,-1,2),(104,0.001,2)], "NNNNND", [1,-2,3,3,3,3], [1,1,1,2,3,4], [0,0,0,0,0,1], "-----A"))
case(22, "bottom-positive-dif-allowed", trace([(100,-200,-2),(110,0,2),(99,5,-2),(98,6,-2)], "NNND", [-1,2,-3,-3], [1,1,1,2], [0,0,0,1], "---A"))
case(23, "top-no-history", trace([(100,100,2),(101,101,2)], "NN", [1,1], [1,2]))
case(23, "bottom-no-history", trace([(100,-100,-2),(99,-101,-2)], "NN", [-1,-1], [1,2]))
TOP_EQUAL_SELECT_A = case(24, "top-one-bar-old-ref-equal-B", extend(ABT, [(131,200,2),(132,200,2)], "ND", [5,5], [1,2], [0,1], "-A"))
BOTTOM_EQUAL_SELECT_A = case(24, "bottom-one-bar-old-ref-equal-B", extend(ABB, [(69,-200,-2),(68,-200,-2)], "ND", [-5,-5], [1,2], [0,1], "-A"))
case(25, "top-first-no-turn", trace([(100,200,2),(90,0,-2),(101,100,2),(102,99,2)], "NNND", [1,-2,3,3], [1,1,1,2], [0,0,0,1], "---A"))
case(25, "bottom-first-no-turn", trace([(100,-200,-2),(110,0,2),(99,-100,-2),(98,-99,-2)], "NNND", [-1,2,-3,-3], [1,1,1,2], [0,0,0,1], "---A"))
case(26, "top-near-before-stronger-far", ABTD)
case(26, "bottom-near-before-stronger-far", ABBD)
case(26, "top-A-broken-B-usable", trace([(100,150,2),(90,0,-2),(120,200,2),(110,0,-2),(130,180,2),(131,180,2)], "NNNNND", [1,-2,3,-4,5,5], [1,1,1,1,1,2], [0,0,0,0,0,3], "-----A"))
case(26, "bottom-A-broken-B-usable", trace([(100,-150,-2),(110,0,2),(80,-200,-2),(90,0,2),(70,-180,-2),(69,-180,-2)], "NNNNND", [-1,2,-3,4,-5,-5], [1,1,1,1,1,2], [0,0,0,0,0,3], "-----A"))
TOP_FAR = case(27, "top-B-broken-A-valid", extend(ABT, [(131,250,2),(132,250,2)], "ND", [5,5], [1,2], [0,1], "-A"))
BOTTOM_FAR = case(27, "bottom-B-broken-A-valid", extend(ABB, [(69,-250,-2),(68,-250,-2)], "ND", [-5,-5], [1,2], [0,1], "-A"))
case(28, "top-near-price-gate", extend(ABT, [(119,100,2),(119,100,2)], "NN", [5,5], [1,2]))
case(28, "bottom-near-price-gate", extend(ABB, [(81,-100,-2),(81,-100,-2)], "NN", [-5,-5], [1,2]))
TOP_FAR_PRICE = trace([(130,300,2),(90,0,-2),(120,200,2),(110,0,-2)], "NNNN", [1,-2,3,-4], [1,1,1,1])
BOTTOM_FAR_PRICE = trace([(70,-300,-2),(110,0,2),(80,-200,-2),(90,0,2)], "NNNN", [-1,2,-3,4], [1,1,1,1])
case(29, "top-A-own-price", extend(TOP_FAR_PRICE, [(125,250,2),(129,250,2)], "NN", [5,5], [1,2]))
case(29, "bottom-A-own-price", extend(BOTTOM_FAR_PRICE, [(75,-250,-2),(71,-250,-2)], "NN", [-5,-5], [1,2]))
case(30, "top-no-third-ref", trace([(90,400,2),(80,0,-2),(100,300,2),(90,0,-2),(120,200,2),(110,0,-2),(130,350,2),(131,350,2)], "NNNNNNNN", [1,-2,3,-4,5,-6,7,7], [1,1,1,1,1,1,1,2]))
case(30, "bottom-no-third-ref", trace([(110,-400,-2),(120,0,2),(100,-300,-2),(110,0,2),(80,-200,-2),(90,0,2),(70,-350,-2),(69,-350,-2)], "NNNNNNNN", [-1,2,-3,4,-5,6,-7,-7], [1,1,1,1,1,1,1,2]))
case(31, "top-switch-same-bar", extend(ABTD, [(132,201,2)], "D", [5], [3], [1]))
case(32, "bottom-switch-same-bar", extend(ABBD, [(68,-201,-2)], "D", [-5], [3], [1]))
case(33, "top-switch-no-borrowed-price", extend(ABTD, [(119,201,2)], "N", [5], [3], [0], "C"))
case(33, "bottom-switch-no-borrowed-price", extend(ABBD, [(81,-201,-2)], "N", [-5], [3], [0], "C"))
TOP_BOTH_BROKEN = case(34, "top-both-break", extend(ABTD, [(132,301,2)], "N", [5], [3], [0], "C"))
BOTTOM_BOTH_BROKEN = case(34, "bottom-both-break", extend(ABBD, [(68,-301,-2)], "N", [-5], [3], [0], "C"))
case(35, "top-far-valid-next-day", extend(TOP_FAR_PRICE, [(125,100,2),(126,100,2),(129,201,2),(131,201,2)], "NDND", [5,5,5,5], [1,2,3,4], [0,3,0,1], "-ACA"))
case(35, "bottom-far-valid-next-day", extend(BOTTOM_FAR_PRICE, [(75,-100,-2),(74,-100,-2),(71,-201,-2),(69,-201,-2)], "NDND", [-5,-5,-5,-5], [1,2,3,4], [0,3,0,1], "-ACA"))
case(36, "top-far-never-return-B", extend(TOP_FAR, [(133,190,2)], "S", [5], [3], [1], "T"))
case(36, "bottom-far-never-return-B", extend(BOTTOM_FAR, [(67,-190,-2)], "S", [-5], [3], [1], "T"))
case(36, "top-B-unbroken-still-fixed-A", extend(TOP_EQUAL_SELECT_A, [(133,199,2)], "D", [5], [3], [1]))
case(36, "bottom-B-unbroken-still-fixed-A", extend(BOTTOM_EQUAL_SELECT_A, [(67,-199,-2)], "D", [-5], [3], [1]))
case(37, "top-structure-no-rescue-next-bar-A", extend(ABTD, [(132,99,2),(133,201,2),(134,201,2)], "SND", [5,5,5], [3,4,5], [3,0,1], "TCA"))
case(37, "bottom-structure-no-rescue-next-bar-A", extend(ABBD, [(68,-99,-2),(67,-201,-2),(66,-201,-2)], "SND", [-5,-5,-5], [3,4,5], [3,0,1], "TCA"))
case(38, "top-retain-with-price-inside", extend(T, [(99,100,2)], "D", [3], [3], [1]))
case(38, "bottom-retain-with-price-inside", extend(B, [(101,-100,-2)], "D", [-3], [3], [1]))
case(39, "top-exact-one-percent", TS)
case(40, "bottom-exact-one-percent", BS)
case(41, "top-no-cumulative-turn", extend(T, [(103,99.5,2),(104,99.1,2)], "DD", [3,3], [3,4], [1,1]))
case(41, "bottom-no-cumulative-turn", extend(B, [(97,-99.5,-2),(96,-99.1,-2)], "DD", [-3,-3], [3,4], [1,1]))
case(42, "top-structure-price-not-rechecked", extend(T, [(99,99,2)], "S", [3], [3], [1], "T"))
case(42, "bottom-structure-price-not-rechecked", extend(B, [(101,-99,-2)], "S", [-3], [3], [1], "T"))
ZERO_BASIS_BOTTOM = trace([(100,-200,-2),(110,0,2),(99,-1,-2),(98,0,-2)], "NNND", [-1,2,-3,-3], [1,1,1,2], [0,0,0,1], "---A")
case(43, "zero-basis-no-structure", extend(ZERO_BASIS_BOTTOM, [(97,1,-2)], "D", [-3], [3], [1]))
case(43, "top-zero-basis-no-return", extend(T, [(103,0,2),(104,1,2)], "SS", [3,3], [3,4], [1,1], "T-"))
case(43, "bottom-zero-basis-no-return", extend(B, [(97,0,-2),(96,-1,-2)], "SS", [-3,-3], [3,4], [1,1], "T-"))
case(43, "zero-basis-does-not-block-flip", extend(ZERO_BASIS_BOTTOM, [(110,0,2)], "N", [5], [1], [0], "F"))
case(44, "actual-previous-zero-bar", extend(B, [(98,-100.5,0),(97,-99.4,-2)], "DS", [-3,-3], [2,3], [1,1], "-T"))
case(45, "top-equal-reference-then-break", extend(T, [(103,200,2),(104,200.01,2)], "DN", [3,3], [3,4], [1,0], "-C"))
case(45, "bottom-equal-reference-then-break", extend(B, [(97,-200,-2),(96,-200.01,-2)], "DN", [-3,-3], [3,4], [1,0], "-C"))
case(45, "top-equal-no-switch", extend(ABTD, [(132,200,2)], "D", [5], [3], [3]))
case(45, "bottom-equal-no-switch", extend(ABBD, [(68,-200,-2)], "D", [-5], [3], [3]))
case(46, "top-exact-return", trace([(100,200,2),(90,0,-2),(101,102,2),(102,102,2),(103,100,2),(99,101,2)], "NNNDSD", [1,-2,3,3,3,3], [1,1,1,2,3,4], [0,0,0,1,1,1], "---ATR"))
case(47, "bottom-return-no-price-wait", trace([(100,-200,-2),(110,0,2),(99,-102,-2),(98,-102,-2),(97,-100,-2),(101,-101,-2)], "NNNDSD", [-1,2,-3,-3,-3,-3], [1,1,1,2,3,4], [0,0,0,1,1,1], "---ATR"))
case(48, "top-insufficient-return", extend(TS, [(104,99.5,2)], "S", [3], [4], [1]))
case(48, "bottom-insufficient-return", extend(BS, [(96,-99.5,-2)], "S", [-3], [4], [1]))
case(48, "top-return-not-cumulative", extend(TS, [(104,99.6,2),(105,100.1,2)], "SS", [3,3], [4,5], [1,1]))
case(48, "bottom-return-not-cumulative", extend(BS, [(96,-99.6,-2),(95,-100.1,-2)], "SS", [-3,-3], [4,5], [1,1]))
case(49, "top-repeated-structure-return", extend(T, [(103,99,2),(99,100,2),(104,99,2),(98,100,2)], "SDSD", [3,3,3,3], [3,4,5,6], [1,1,1,1], "TRTR"))
case(49, "bottom-repeated-structure-return", extend(B, [(97,-99,-2),(101,-100,-2),(96,-99,-2),(102,-100,-2)], "SDSD", [-3,-3,-3,-3], [3,4,5,6], [1,1,1,1], "TRTR"))
case(50, "top-structure-direct-cancel", extend(TS, [(104,201,2)], "N", [3], [4], [0], "C"))
case(50, "bottom-structure-direct-cancel", extend(BS, [(96,-201,-2)], "N", [-3], [4], [0], "C"))
case(51, "top-both-broken-no-revival", extend(TOP_BOTH_BROKEN, [(133,100,2),(134,99,2)], "NN", [5,5], [4,5]))
case(51, "bottom-both-broken-no-revival", extend(BOTTOM_BOTH_BROKEN, [(67,-100,-2),(66,-99,-2)], "NN", [-5,-5], [4,5]))
case(52, "top-zero-turn-and-return", extend(T, [(103,99,0),(99,100,0)], "SD", [3,3], [2,2], [1,1], "TR"))
case(52, "bottom-zero-turn-and-return", extend(B, [(97,-99,0),(101,-100,0)], "SD", [-3,-3], [2,2], [1,1], "TR"))
case(53, "top-flip-create-following", extend(T, [(90,100,-2)], "N", [-5], [1], [0], "F"))
case(54, "bottom-flip-create-following", extend(B, [(110,-100,2)], "N", [5], [1], [0], "F"))
TOP_FOLLOWING = case(55, "top-existing-following", extend(TS, [(104,98,-2)], "N", [-6], [1]))
BOTTOM_FOLLOWING = case(56, "bottom-existing-following", extend(BS, [(96,-98,2)], "N", [6], [1]))
case(55, "top-flip-before-return", extend(TS, [(104,100,-2)], "N", [-6], [1]))
case(56, "bottom-flip-before-return", extend(BS, [(96,-100,2)], "N", [6], [1]))
case(57, "top-flip-break-no-lock", extend(TS, [(104,201,-2)], "N", [-6], [1], [0], "X"))
case(57, "bottom-flip-break-no-lock", extend(BS, [(96,-201,2)], "N", [6], [1], [0], "X"))
case(58, "top-zero-no-lock", extend(TS, [(104,99,0),(105,99,0)], "SS", [3,3], [3,3], [1,1]))
case(58, "bottom-zero-no-lock", extend(BS, [(96,-99,0),(95,-99,0)], "SS", [-3,-3], [3,3], [1,1]))
case(59, "top-price-alone-no-withdrawal", extend(TS, [(104,98.5,2)], "S", [3], [4], [1]))
case(60, "bottom-price-alone-no-withdrawal", extend(BS, [(96,-98.5,-2)], "S", [-3], [4], [1]))
case(61, "top-separator-price-break", extend(TOP_FOLLOWING, [(105,97,-2)], "N", [-6], [2]))
case(61, "bottom-separator-price-break", extend(BOTTOM_FOLLOWING, [(95,-97,2)], "N", [6], [2]))
case(62, "top-separator-reference-break", extend(TOP_FOLLOWING, [(150,201,-2)], "N", [-6], [2]))
case(62, "bottom-separator-reference-break", extend(BOTTOM_FOLLOWING, [(50,-201,2)], "N", [6], [2]))
case(63, "top-two-cycles", extend(TS, [(90,0,-2),(110,95,2),(111,96,2),(112,95,2),(100,94,-2)], "NNDSN", [-6,7,7,7,-10], [1,1,2,3,1], [0,0,3,3,0], "--AT-"))
case(63, "bottom-two-cycles", extend(BS, [(110,0,2),(90,-95,-2),(89,-96,-2),(88,-95,-2),(100,-94,2)], "NNDSN", [6,-7,-7,-7,10], [1,1,2,3,1], [0,0,3,3,0], "--AT-"))
case(64, "top-dead-never-revives-new-cycle", extend(TS, [(104,100,2),(105,201,2),(90,100,-2),(106,100,2),(107,99,2)], "DNNND", [3,3,-8,9,9], [4,5,1,1,2], [1,0,0,0,3], "RC--A"))
case(64, "bottom-dead-never-revives-new-cycle", extend(BS, [(96,-100,-2),(95,-201,-2),(110,-100,2),(94,-100,-2),(93,-99,-2)], "DNNND", [-3,-3,8,-9,-9], [4,5,1,1,2], [1,0,0,0,3], "RC--A"))
case(65, "top-dull-flip-break-first", extend(T, [(90,201,-2)], "N", [-5], [1], [0], "X"))
case(65, "bottom-dull-flip-break-first", extend(B, [(110,-201,2)], "N", [5], [1], [0], "X"))
case(66, "top-far-break-no-revival", extend(TOP_FAR, [(133,301,2),(134,190,2)], "NN", [5,5], [3,4], [0,0], "C-"))
case(66, "bottom-far-break-no-revival", extend(BOTTOM_FAR, [(67,-301,-2),(66,-190,-2)], "NN", [-5,-5], [3,4], [0,0], "C-"))
case(67, "top-zero-cancel", extend(T, [(103,201,0)], "N", [3], [2], [0], "C"))
case(67, "bottom-zero-cancel", extend(B, [(97,-201,0)], "N", [-3], [2], [0], "C"))
case(67, "top-zero-switch", extend(ABTD, [(132,201,0)], "D", [5], [2], [1]))
case(67, "bottom-zero-switch", extend(ABBD, [(68,-201,0)], "D", [-5], [2], [1]))
case(68, "top-zero-break-before-count-two", trace([(100,200,2),(90,0,-2),(101,100,2),(102,201,0),(103,100,2)], "NNNNN", [1,-2,3,3,3], [1,1,1,1,2]))
case(68, "bottom-zero-break-before-count-two", trace([(100,-200,-2),(110,0,2),(99,-100,-2),(98,-201,0),(97,-100,-2)], "NNNNN", [-1,2,-3,-3,-3], [1,1,1,1,2]))
case(69, "top-retained-price-equal", extend(T, [(100,100,2)], "D", [3], [3], [1]))
case(69, "bottom-retained-price-equal", extend(B, [(100,-100,-2)], "D", [-3], [3], [1]))


def _time(period, row):
    value = DATES[row - 1]
    return value if period == "day" else value + "T15:00:00+08:00"


def _identity(period, *parts):
    # Independent copy of the LLD identity formula, never calculator._id.
    value = [MAIN_SPEC.algorithm_version, MAIN_SPEC.spec_hash, "000001.SH", period, *parts]
    return hashlib.sha256("|".join(map(str, value)).encode()).hexdigest()[:24]


def _expected_wave(data, period, start, end, count):
    sign = 1 if data.segments[start - 1] > 0 else -1
    positions = range(start, end + 1)
    choose = max if sign == 1 else min
    price = choose(data.values[index - 1][0] for index in positions)
    dif = choose(data.values[index - 1][1] for index in positions)
    price_row = next(index for index in positions if data.values[index - 1][0] == price)
    dif_row = next(index for index in positions if data.values[index - 1][1] == dif)
    return {"sign": sign, "start": _time(period, start), "end": _time(period, end),
            "count": count, "price": price, "dif": dif,
            "price_at": _time(period, price_row), "dif_at": _time(period, dif_row)}


def _expected_reference(data, period, start, before_row):
    # Expected segment boundaries come only from the literal signed timeline.
    end = next(index for index in range(start, before_row)
               if index == before_row - 1 or abs(data.segments[index]) != start)
    wave = _expected_wave(data, period, start, end, 0)
    return {"startTime": wave["start"], "endTime": wave["end"],
            "price": wave["price"], "dif": wave["dif"],
            "priceAt": wave["price_at"], "difAt": wave["dif_at"]}


def _reference_for_row(data, period, row):
    start = data.refs[row - 1]
    return _expected_reference(data, period, start, row) if start else None


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("number,data", CASES)
def test_lld_rc_rule_sequence(period, number, data):
    calc = XxmCalculator(period=period, source_identity="literal-r4-rules")
    immutable_steps = []
    immutable_copies = []
    ledger = {}
    expected_active = None
    expected_ledger = {}
    for row, (close, dif, hist) in enumerate(data.values, 1):
        bar = XxmBar(_time(period, row), close, dif, dif - hist / 2, hist)
        before_state = STATES[data.states[row - 2]] if row > 1 else "NONE"
        before_segment = data.segments[row - 2] if row > 1 else 0
        current_segment = data.segments[row - 1]
        flipped = bool(before_segment and current_segment != before_segment)
        code = data.events[row - 1]
        expected_state = STATES[data.states[row - 1]]
        expected_sign = 1 if (before_segment if flipped else current_segment) > 0 else -1
        expected_direction = "TOP" if expected_sign == 1 else "BOTTOM"
        event_ref = (_reference_for_row(data, period, row - 1) if code in "RTXC" and row > 1
                     else _reference_for_row(data, period, row) if code == "A" else None)
        if code == "F":
            event_ref = _reference_for_row(data, period, row - 1)
        expected_updates = []
        expected_events = []
        for identity, previous_record in list(expected_ledger.items()):
            if previous_record['status'] != 'FOLLOWING':
                continue
            record = deepcopy(previous_record)
            original_sign = 1 if record['direction'] == 'TOP' else -1
            root_sign = (hist > 0) - (hist < 0)
            same = record['nextSameColorStart']
            if same is None and root_sign == original_sign:
                record['nextSameColorStart'] = bar.time
            elif same is not None and root_sign == -original_sign:
                record.update(status='FINISHED', trackingEndedAt=bar.time)
            if record['status']=='FOLLOWING' and record['nextSameColorStart'] is not None and original_sign*(close-record['originWave']['price'])>0:
                record.update(status='DISAPPEARED',trackingEndedAt=bar.time,disappearedAt=bar.time,disappearanceReason='structure_price_break')
                expected_events.append(dict(id=_identity(period,bar.time,'CANCEL','structure_price_break',identity),time=bar.time,
                    direction=record['direction'],type='CANCEL',route='structure_price_break',fromState='STRUCTURE',
                    eventReference=deepcopy(record['originalReference']),relatedStructureId=identity))
            if record!=previous_record:
                expected_updates.append(record)
        if code != "-":
            event_type, route = EVENTS[code]
            event_id = _identity(period, bar.time, event_type, expected_sign, event_ref["startTime"])
            related = None
            if code in "TF":
                assert expected_active is None
                related = _identity(period, "structure", event_id)
                origin_start = abs(before_segment if flipped else current_segment)
                extreme_end = row - 1 if flipped else row
                origin_wave = _expected_wave(data, period, origin_start, extreme_end, 0)
                record = {"id": related, "direction": expected_direction,
                          "structureEventId": event_id, "formedAt": bar.time,
                          "formationRoute": route, "originSegmentStart": _time(period, origin_start),
                          "originalReference": deepcopy(event_ref), "priceExtreme": origin_wave["price"],
                          "priceExtremeAt": origin_wave["price_at"],
                          "status": "FOLLOWING" if code == "F" else "ASSESSING",
                          "firstOppositeAt": bar.time if code == "F" else None,
                          "originWave": _expected_wave(data, period, origin_start, extreme_end, data.counts[extreme_end-1]) if code=='F' else None,
                          "nextSameColorStart": None, "trackingEndedAt": None,
                          "disappearedAt": None, "disappearanceReason": None}
                expected_updates.append(record)
                if code == "T":
                    expected_active = deepcopy(record)
            elif code == "R" or (code in "CX" and before_state == "STRUCTURE"):
                assert expected_active is not None
                related = expected_active["id"]
                final = dict(expected_active, status="DISAPPEARED", trackingEndedAt=bar.time, disappearedAt=bar.time,
                             disappearanceReason="dif_return" if code == "R" else "reference_dif_break")
                expected_updates.append(final)
                expected_active = None
            expected_events.append({"id": event_id, "time": bar.time, "direction": expected_direction,
                                    "type": event_type, "route": route, "fromState": before_state,
                                    "eventReference": event_ref, "relatedStructureId": related})
        elif flipped and before_state == "STRUCTURE":
            assert expected_active is not None
            expected_updates.append(dict(expected_active, status="FOLLOWING", firstOppositeAt=bar.time,
                originWave=_expected_wave(data,period,abs(before_segment),row-1,data.counts[row-2])))
            expected_active = None
        result = calc.step(bar)
        message = (f"RC-{number:02d} row={row} C/D/H={data.values[row-1]} "
                   f"expected={data.states[row-1]} ref={data.refs[row-1]}")
        assert result.events == tuple(expected_events), message
        assert result.structures == tuple(expected_updates), message
        assert result.decision is None, message
        assert calc.state == expected_state, message
        assert calc.processed == row and calc.previous == bar, message
        expected_ref = _reference_for_row(data, period, row)
        assert (calc.reference.reference() if calc.reference else None) == expected_ref, message
        assert calc.active_structure == expected_active, message
        if current_segment:
            start = abs(current_segment)
            expected_wave = _expected_wave(data, period, start, row, data.counts[row - 1])
            assert asdict(calc.wave) == expected_wave, message
        else:
            assert calc.wave is None and calc.history == {1: [], -1: []}, message
        expected_history = {1: [], -1: []}
        for ended_row in range(1, row):
            ended_segment = data.segments[ended_row - 1]
            if ended_segment and data.segments[ended_row] != ended_segment:
                old_wave = _expected_wave(data, period, abs(ended_segment), ended_row,
                                          data.counts[ended_row - 1])
                pool = expected_history[old_wave["sign"]]
                pool.append(old_wave)
                del pool[:-2]
        assert {sign: [asdict(wave) for wave in waves] for sign, waves in calc.history.items()} == expected_history, message
        point = result.point
        assert point == {"time": bar.time, "close": close, "dif": dif, "dea": dif-hist/2,
                         "hist": hist, "ordinaryState": expected_state,
                         "ordinaryDirection": ("TOP" if current_segment > 0 else "BOTTOM")
                         if expected_state != "NONE" else None,
                         "activeReference": expected_ref,
                         "activeStructureId": expected_active["id"] if expected_active else None}, message
        for item in expected_updates:
            expected_ledger[item["id"]] = deepcopy(item)
        for item in result.structures:
            previous = ledger.get(item["id"])
            assert previous is None or previous["status"] in ("ASSESSING", "FOLLOWING"), message
            ledger[item["id"]] = deepcopy(item)
        assert ledger == expected_ledger, message
        assert immutable_steps == immutable_copies, message
        immutable_steps.append(result)
        immutable_copies.append(deepcopy(result))
    assert {item.values[0] for item in CASES} == set(range(1, 70))


@pytest.mark.parametrize("period", PERIODS)
def test_rc_39_40_original_float_order_boundary(period):
    """LLD §3.12: -99→-98.01 is below the original float gate, not exact 1%."""
    # The dedicated cancellation/return boundary below uses a DULL basis -99.
    prefix = [(100,-200,-2),(110,0,2),(99,-99,-2),(98,-99,-2)]
    calc = XxmCalculator(period=period, source_identity="float-order")
    for row, (c,d,h) in enumerate(prefix, 1):
        calc.step(XxmBar(_time(period,row),c,d,d-h/2,h))
    below = calc.step(XxmBar(_time(period,5),97,-98.01,-97.01,-2))
    assert below.events == () and below.point["ordinaryState"] == "DULL"
    other = XxmCalculator(period=period, source_identity="float-order")
    for row, (c,d,h) in enumerate(prefix,1):
        other.step(XxmBar(_time(period,row),c,d,d-h/2,h))
    above = other.step(XxmBar(_time(period,5),97,-98.009,-97.009,-2))
    assert [(event["type"],event["route"]) for event in above.events] == [("STRUCTURE","dif_turn")]
