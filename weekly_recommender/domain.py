"""Domain knowledge: vocabulary, facts, rules, defaults and preferences.

This module only holds *data* (ASP source fragments as plain strings).
No solving or presentation logic lives here - see solver.py and engine.py.
"""

DAY_NAMES = {
    1: "monday",
    2: "tuesday",
    3: "wednesday",
    4: "thursday",
    5: "friday",
    6: "saturday",
    7: "sunday",
}
DAY_NUMBERS = {name: number for number, name in DAY_NAMES.items()}

# Context factors that are tracked per day but have no ASP sort of their own
# (used only to drive the GUI's explanation view).
CONTEXT_FACTORS = ["dailyenergylevel", "dailyweather", "dailyfriendavailable"]

# --- Vocabulary -------------------------------------------------------------

CONTEXT_DEFINITIONS = [
    "energylevel(low;medium;high)",
    "daynumber(1..7)",
    "weekend(6;7)",
    "weather(good;bad)",
]

GOAL_DEFINITIONS = ["goal(socialising;exercising;resting;creativity;chores)"]

ACTION_DEFINITIONS = [
    "activity(pubquiz;knittingclub;gamenight;karaoke;dinnerwithfriend;swimming;"
    "running;yoga;knittingalone;tv;reading;meditating;painting;journaling;laundry;"
    "cleankitchen;cleanbathroom;vacuum)",
    "socialactivity(pubquiz;knittingclub;gamenight;dinnerwithfriend;karaoke)",
    "exerciseactivity(swimming;running;yoga)",
    "restingactivity(knittingalone;yoga;tv;reading;meditating)",
    "creativeactivity(knittingclub;knittingalone;painting;journaling)",
    "choreactivity(laundry;cleankitchen;cleanbathroom;vacuum)",
]

# --- Explicit facts (mutable at runtime through RecommenderEngine) ---------

DEFAULT_CONTEXT_FACTS = [
    "dailyenergylevel(2,high)",
    "dailyenergylevel(3,low)",
    "dailyenergylevel(4,low)",
    "-dailyenergylevel(5,medium)",
    "dailyenergylevel(7,low)",
    "dailyenergylevel(1,medium)",
    "dailyweather(3,bad)",
    "dailyweather(4,bad)",
    "dailyweather(6,bad)",
    "dailyfriendavailable(3,true)",
    "dailyfriendavailable(5,true)",
    "dailyfriendavailable(6,true)",
]

DEFAULT_GOAL_FACTS = ["dailygoal(6,resting)"]

DEFAULT_ACTION_FACTS = ["dailyaction(2,swimming)"]

# --- Hard knowledge rules ("head", "body" pairs; not default rules) --------

CONTEXT_KNOWLEDGE = [
    ("-dailyenergylevel(D,E)", "daynumber(D), energylevel(E), dailyenergylevel(D,C), C != E"),
    ("-dailyweather(D,W)", "daynumber(D), weather(W), dailyweather(D,V), W != V"),
]

GOAL_KNOWLEDGE = [
    ("-dailygoal(D,G)", "daynumber(D), D <= 5, goal(G), dailygoal(D,F), G != F"),
    ("-dailygoal(D+1,G)", "dailygoal(D,G)"),
    ("-dailygoal(D-1,G)", "dailygoal(D,G)"),
    (
        "-dailygoal(D,G)",
        "daynumber(D), D > 5, goal(G), dailygoal(D,F), G != F, dailygoal(D,E), E != F, E != G",
    ),
    ("-dailygoal(D,chores)", "dailyenergylevel(D,low)"),
    ("-dailygoal(D,exercising)", "dailyenergylevel(D,low)"),
    ("-dailygoal(D,resting)", "dailyenergylevel(D,high)"),
    ("dailygoal(D,G)", "dailyaction(D,A), achieves(G,A)"),
    ("achieves(socialising,A)", "socialactivity(A)"),
    ("achieves(exercising,A)", "exerciseactivity(A)"),
    ("achieves(resting,A)", "restingactivity(A)"),
    ("achieves(creativity,A)", "creativeactivity(A)"),
    ("achieves(chores,A)", "choreactivity(A)"),
    ("achieved(D,G)", "dailygoal(D,G), dailyaction(D,A), achieves(G,A)"),
]

ACTION_KNOWLEDGE = [
    (
        "-dailyaction(D,A)",
        "daynumber(D), D > 5, activity(A), achieves(G,A), achieves(G,B), "
        "dailygoal(D,G), dailyaction(D,B), A != B",
    ),
    ("-dailyaction(D,A)", "daynumber(D), choreactivity(A), dailyaction(C,A), C != D"),
    ("-dailyaction(D,A)", "daynumber(D), D < 6, activity(A), dailyaction(D,B), A != B"),
    (
        "-dailyaction(D,G)",
        "daynumber(D), D > 5, activity(G), dailyaction(D,F), G != F, dailyaction(D,E), E != F, E != G",
    ),
    ("-dailyaction(D+1,A)", "dailyaction(D,A)"),
    ("-dailyaction(D-1,A)", "dailyaction(D,A)"),
    ("-dailyaction(D,pubquiz)", "dailyenergylevel(D,low)"),
    ("-dailyaction(D,karaoke)", "dailyenergylevel(D,low)"),
    ("-dailyaction(D,dinnerwithfriend)", "dailyfriendavailable(D,false), daynumber(D)"),
    ("-dailyaction(D,running)", "dailyweather(D,bad)"),
    ("-dailyaction(D,pubquiz)", "D != 1, daynumber(D)"),
    ("-dailyaction(D,knittingclub)", "D != 3, daynumber(D)"),
    ("-dailyaction(D,gamenight)", "D != 4, daynumber(D)"),
]

# --- Default rules (non-monotonic) and integrity constraints ---------------
# Integrity constraints use an empty head, written here as "" for clarity.

CONTEXT_DEFAULTS = [
    ("dailyenergylevel(D,medium)", "daynumber(D), not -dailyenergylevel(D,medium)"),
    ("dailyweather(D,good)", "daynumber(D), not -dailyweather(D,good)"),
    ("dailyfriendavailable(D,false)", "daynumber(D), not dailyfriendavailable(D,true)"),
]

GOAL_DEFAULTS = [
    (
        "dailygoal(D,G)",
        "daynumber(D), goal(G), not -dailygoal(D,G), achieves(G,A), not -dailyaction(D,A)",
    ),
    ("", "{ dailygoal(D,chores) : daynumber(D) } != 2"),
    ("", "{ dailygoal(D,socialising) : daynumber(D) } >= 3"),
]

ACTION_DEFAULTS = [
    (
        "dailyaction(D,A)",
        "daynumber(D), activity(A), dailygoal(D,G), achieves(G,A), "
        "not dailyaction(D,B), achieves(G,B), B != A, not -dailyaction(D,A)",
    ),
    ("", "-achieved(D,G), dailygoal(D,G)"),
    ("", "dailyaction(D,tv), dailyaction(C,tv), D != C"),
    ("-achieved(D,G)", "not achieved(D,G), daynumber(D), dailygoal(D,G)"),
]

# --- Output shaping ----------------------------------------------------------

OUTPUT_FORMATTING_RULES = [
    (
        f"recommendation({DAY_NAMES[day]},G,A)",
        f"dailygoal({day},G), dailyaction({day},A), achieves(G,A)",
    )
    for day in range(1, 8)
]

# --- Preferences used to rank among equally valid answer sets --------------

CONTEXT_PREFERENCES = ["dailyenergylevel(3,medium)", "dailyenergylevel(7,low)"]

GOAL_PREFERENCES = [
    "dailygoal(1,socialising)", "dailygoal(2,socialising)",
    "dailygoal(4,exercising)", "dailygoal(4,creativity)",
    "dailygoal(7,creativity)", "dailygoal(7,socialising)", "dailygoal(7,resting)", "dailygoal(7,exercising)", "dailygoal(7,chores)",
    "dailygoal(6,resting)",
]

ACTION_PREFERENCES = ["dailyaction(1,pubquiz)", "dailyaction(1,vacuum)", "dailyaction(1,laundry)", "dailyaction(3,dinnerwithfriend)", "dailyaction(2,swimming)", "dailyaction(4,painting)", "dailyaction(2,vacuum)", "-dailyaction(6,tv)", "dailyaction(7,painting)", "dailyaction(7,knittingalone)", "dailyaction(7,journaling)"]
