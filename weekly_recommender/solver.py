"""Thin, typed wrapper around clingo: builds ASP program text and exposes
answer sets as structured `clingo.Symbol` objects instead of raw strings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import clingo


def render_statements(statements: Iterable[str]) -> str:
    """Join bare ASP statements (definitions or facts) into a program."""
    return "".join(f"{statement}. " for statement in statements)


def render_rules(rules: Iterable[tuple[str, str]]) -> str:
    """Render (head, body) pairs as ASP rules, including integrity
    constraints where head is the empty string."""
    return "".join(f"{head} :- {body}. " for head, body in rules)


@dataclass(frozen=True)
class AnswerSet:
    """A single ASP model as a sorted, de-duplicated list of symbols."""

    symbols: tuple[clingo.Symbol, ...]

    @classmethod
    def from_model(cls, model: clingo.Model) -> "AnswerSet":
        return cls(tuple(sorted(model.symbols(shown=True), key=str)))

    def __contains__(self, symbol: clingo.Symbol) -> bool:
        return symbol in self.symbols

    def matching(self, name: str, arity: int | None = None) -> list[clingo.Symbol]:
        """All symbols with the given predicate name (and, optionally, arity)."""
        return [
            symbol
            for symbol in self.symbols
            if symbol.name == name and (arity is None or len(symbol.arguments) == arity)
        ]

    def as_program(self) -> str:
        """Re-render this answer set as ASP facts, for feeding into the next
        solving stage."""
        return "".join(f"{symbol}. " for symbol in self.symbols)


def solve(background: str, program: str) -> list[AnswerSet]:
    """Ground and solve `background + program`, returning every answer set."""
    control = clingo.Control(["0"])
    control.add("base", [], background)
    control.add("base", [], program)
    control.ground([("base", [])])

    answer_sets = []
    with control.solve(yield_=True) as handle:
        for model in handle:
            answer_sets.append(AnswerSet.from_model(model))
    return answer_sets


def parse_preferences(preferences: Sequence[str]) -> list[clingo.Symbol]:
    return [clingo.parse_term(preference) for preference in preferences]


def rank_by_preference(
    answer_sets: list[AnswerSet], preferences: Sequence[str]
) -> list[AnswerSet]:
    """Sort answer sets so that the one matching the earliest preference
    (by list position) comes first. Answer sets matching no preference sort
    last, in their original relative order (stable sort)."""
    parsed = parse_preferences(preferences)

    def rank(answer_set: AnswerSet) -> int:
        for index, preference in enumerate(parsed):
            if preference in answer_set:
                return index
        return len(parsed)

    return sorted(answer_sets, key=rank)
