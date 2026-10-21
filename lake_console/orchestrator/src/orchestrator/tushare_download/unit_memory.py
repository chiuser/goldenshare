"""Incremental current-unit object accounting, not an operating-system RSS limit."""

from __future__ import annotations

import sys
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal

from .download_errors import capacity_error


@dataclass(slots=True)
class _Node:
    value: object
    size: int
    references: int
    children: tuple[int, ...]


class UnitMemory:
    def __init__(self, config):
        self.limit = config.unit_memory_limit_bytes
        self.reserve_bytes = config.working_reserve_bytes
        self._nodes: dict[int, _Node] = {}
        self._roots: dict[object, int] = {}
        self._estimates: dict[object, int] = {}
        self._size = 0

    @property
    def used_bytes(self):
        return (
            self._size
            + sys.getsizeof(self._nodes)
            + sys.getsizeof(self._roots)
            + sys.getsizeof(self._estimates)
            + sum(self._estimates.values())
            + self.reserve_bytes
        )

    def _check(self, *, estimated=False):
        if self.used_bytes > self.limit:
            raise capacity_error(estimated=estimated)

    def reserve(self, label, size: int):
        if type(size) is not int or size < 0:
            raise ValueError("nonnegative allocation estimate required")
        self._estimates[label] = size
        self._check(estimated=True)

    def unreserve(self, label):
        self._estimates.pop(label, None)

    @staticmethod
    def _children(value):
        if type(value) is dict:
            return tuple(x for pair in value.items() for x in pair)
        if type(value) in (list, tuple):
            return value
        if type(value) is memoryview:
            return (value.obj,)
        if is_dataclass(value) and not isinstance(value, type):
            return tuple(getattr(value, f.name) for f in fields(value))
        if value is None or type(value) in (
            str,
            bytes,
            bytearray,
            bool,
            int,
            float,
            Decimal,
        ):
            return ()
        # Finite IntEnums are integer values with no owned execution state.
        if isinstance(value, int):
            return ()
        raise TypeError("unsupported unit memory object")

    def _add(self, value, *, shallow=False):
        root = id(value)
        pending = [(value, shallow)]
        current = children_values = None
        try:
            while pending:
                current, shallow = pending.pop()
                key = id(current)
                if key in self._nodes:
                    self._nodes[key].references += 1
                    continue
                children_values = () if shallow else self._children(current)
                children = tuple(id(child) for child in children_values)
                size = sys.getsizeof(current)
                node = _Node(current, size, 1, children)
                self._nodes[key] = node
                self._size += (
                    size
                    + sys.getsizeof(node)
                    + sys.getsizeof(children)
                    + sys.getsizeof(key)
                )
                pending.extend((child, False) for child in children_values)
            return root
        finally:
            pending.clear()
            value = current = children_values = node = None

    def _drop(self, key):
        pending = [key]
        node = None
        try:
            while pending:
                key = pending.pop()
                node = self._nodes[key]
                node.references -= 1
                if node.references:
                    continue
                del self._nodes[key]
                self._size -= (
                    node.size
                    + sys.getsizeof(node)
                    + sys.getsizeof(node.children)
                    + sys.getsizeof(key)
                )
                pending.extend(node.children)
        finally:
            pending.clear()
            node = None

    def attach(self, label, value, *, shallow=False):
        self.release(label)
        self._roots[label] = self._add(value, shallow=shallow)
        self._estimates.pop(label, None)
        self._check()
        return value

    def refresh_shallow(self, label, value):
        key = self._roots.get(label)
        if key is None or self._nodes[key].value is not value:
            return self.attach(label, value, shallow=True)
        node = self._nodes[key]
        size = sys.getsizeof(value)
        self._size += size - node.size
        node.size = size
        self._check()
        return value

    def release(self, label):
        key = self._roots.pop(label, None)
        if key is not None:
            self._drop(key)
        self._estimates.pop(label, None)

    def clear(self):
        self._roots.clear()
        self._nodes.clear()
        self._estimates.clear()
        self._size = 0
