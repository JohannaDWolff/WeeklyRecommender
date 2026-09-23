# TODO

## Weekend recommendation rows can pair a goal with the wrong action

`domain.py`'s `OUTPUT_FORMATTING_RULES` generates a `recommendation` for
every `dailygoal(D,G), dailyaction(D,A)` combination on a day - it doesn't
require `achieves(G,A)`. On weekdays that's harmless, since there's only
one `dailygoal`/`dailyaction` fact per day. But Saturday and Sunday can
carry two independent goal+action pairs at once (e.g. `resting` achieved
by `tv`, and separately `socialising` achieved by `karaoke`), and the
cross-join then also manufactures rows that were never actually paired -
e.g. `recommendation(saturday, resting, karaoke)`, even though karaoke
only achieves `socialising` that day, not `resting`.

The original prototype (`StudyExample.py`) required `achieves(G,A)` in its
weekend output-formatting rules; the refactor
(`weekly_recommender/domain.py`) dropped that condition when unifying the
weekday/weekend rules into one list comprehension.

Confirmed via:
```python
engine.action_solution.matching("dailygoal", 2)   # dailygoal(6,resting), dailygoal(6,socialising)
engine.action_solution.matching("dailyaction", 2) # dailyaction(6,karaoke), dailyaction(6,tv)
engine.action_solution.matching("achieves", 2)    # achieves(resting,tv), achieves(socialising,karaoke) - not the cross pairs
```

**Fix**: add `achieves(G,A)` back to the body of
`OUTPUT_FORMATTING_RULES` in `domain.py:146-149`, matching the original
prototype's weekend rules.

## Replacing a default action can make the goal-defaults stage unsatisfiable

The `chores` quota (`domain.py:123`: `{ dailygoal(D,chores) : daynumber(D) }
!= 2`) requires exactly 2 chores days. Under the default context/facts,
only Monday and Friday are chores-eligible (Wed/Thu/Sun are blocked by low
energy via `domain.py:83`; Tuesday is hard-pinned to `exercising` by
`DEFAULT_ACTION_FACTS`'s `dailyaction(2,swimming)`; Saturday is hard-pinned
to `resting` by `DEFAULT_GOAL_FACTS`) - so both must end up as `chores` for
the quota to be satisfiable at all.

Editing Friday's action to `swimming` (e.g. via the "problem screen":
remove `cleanbathroom` on Friday, replace with `swimming`) adds
`dailyaction(5,swimming)` as a fact. Since swimming is an
`exerciseactivity`, the hard rule `domain.py:86`
(`dailygoal(D,G) :- dailyaction(D,A), achieves(G,A)`) unconditionally
forces `dailygoal(5,exercising)`, knocking Friday out of the
chores-eligible pool. Only Monday is left, so no assignment can reach the
required count of 2 - the goal-defaults solve (`engine.py:294-299`)
returns zero answer sets, raising `Inconsistent("No consistent goal
defaults.")`.

This also isn't caught until the recommendation is recomputed:
`RecommenderEngine.add_fact` (`engine.py:518`) only checks the new fact
against the base knowledge base (stage 1), not the full defaults pipeline,
so the fact is added successfully and the failure only surfaces afterward
when `show_updated_recommendation` re-runs `run_pipeline()` - with no
`ConflictReport`, just a generic warning and no offered resolution
options.

**Fix**: needs design thought - e.g. relax the `!= 2` chores quota to a
range, or give the user a proper `ConflictReport`-style resolution (as
`add_fact`'s direct/deep conflict paths already do) instead of a bare
"No consistent goal defaults." warning with no way to fix it from the
GUI.
