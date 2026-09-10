# Weekly Recommender

An Answer Set Programming (ASP) prototype, using [clingo](https://potassco.org/clingo/),
that recommends one activity per day of the week to satisfy a daily goal
(socialising, exercising, resting, creativity, chores), given context such as
energy level, weather and friend availability. A Tkinter GUI lets you accept
the recommendation, or reject it, drill into *why* a given day/goal/action was
chosen, and edit the underlying facts/rules to get a new recommendation.

- `StudyExample.py` — the original single-file prototype (kept for reference).
- `weekly_recommender/` — refactored version:
  - `domain.py` — the ASP vocabulary, facts, rules, defaults and preferences (pure data).
  - `solver.py` — thin clingo wrapper: builds ASP program text, exposes answer
    sets as structured `clingo.Symbol` data via `AnswerSet`.
  - `engine.py` — `RecommenderEngine`: owns the mutable fact/rule base, runs
    the context → goal → action multi-stage solve, and answers "why" questions.
  - `gui.py` — Tkinter front-end (`App`), driven by `RecommenderEngine`.
  - `main.py` — entry point.

## Run it

```
clingo_venv/bin/python weekly_recommender/main.py
```

## Design notes

The solver runs in three stages (context defaults → goal defaults → action
defaults) rather than one grounding, because the non-monotonic defaults
across stages would otherwise conflict combinatorially. Each stage's chosen
answer set (picked by `solver.rank_by_preference`) is fed as facts into the
next. The three *hard* rule sets (`CONTEXT_KNOWLEDGE`, `GOAL_KNOWLEDGE`,
`ACTION_KNOWLEDGE`) stay in scope for every stage, since later defaults
depend on predicates — like `achieves/2` — that only the hard rules define.
