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
