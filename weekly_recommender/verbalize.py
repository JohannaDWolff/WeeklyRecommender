"""Tiny templating system: ASP rules (as in domain.py) -> semi-English text.

Idea
----
1. Parse each rule into literals (atom / comparison / aggregate), keeping the
   classical negation (-a) and default negation (not a) flags.
2. Infer a *type* for every variable (day, goal, activity, ...) from the
   sort-guard atoms (daynumber(D), goal(G), ...) and from the slots of the
   atoms it occurs in.
3. Drop the pure sort guards (they only matter for grounding, not meaning).
4. Render every literal through a per-predicate template, then assemble the
   sentence according to the rule kind:
       knowledge   -> "If <body>, then <head>."
       default     -> "By default, <head>, provided that <body>."
       constraint  -> "It is impossible that <body>."

To support a new predicate, add ONE entry to TEMPLATES (or ZERO for
zero-arity atoms). Unknown predicates fall back to a readable generic form.
"""
import re

from domain import DAY_NAMES

# ---------------------------------------------------------------- vocabulary
# Sort-guard predicates: they give a variable its type and are then hidden.
GUARDS = {
    "daynumber": "day",
    "energylevel": "energy",
    "weather": "weather",
    "goal": "goal",
    "activity": "activity",
}
NOUN = {"day": "day", "energy": "energy level", "weather": "weather",
        "goal": "goal", "activity": "activity", "bool": "value"}
PLURAL = {"day": "days", "energy": "energy levels", "weather": "weather values",
          "goal": "goals", "activity": "activities", "bool": "values"}

# pred -> slot types, positive template, negative (-pred) template
TEMPLATES = {
    "dailyenergylevel": dict(
        slots=["day", "energy"],
        pos="the energy level on {0} is {1}",
        neg="the energy level on {0} is not {1}"),
    "dailyweather": dict(
        slots=["day", "weather"],
        pos="the weather on {0} is {1}",
        neg="the weather on {0} is not {1}"),
    "dailyfriendavailable": dict(
        slots=["day", "bool"],
        pos="friend availability on {0} is {1}",
        neg="friend availability on {0} is not {1}",
        variants={
            (1, "true"): ("a friend is available on {0}",
                          "no friend is available on {0}"),
            (1, "false"): ("no friend is available on {0}",
                           "a friend is available on {0}"),
        }),
    "dailygoal": dict(
        slots=["day", "goal"],
        pos="the goal on {0} is {1}",
        neg="the goal on {0} is not {1}"),
    "dailyaction": dict(
        slots=["day", "activity"],
        pos="the activity on {0} is {1}",
        neg="the activity on {0} is not {1}"),
    "achieves": dict(
        slots=["goal", "activity"],
        pos="{1} achieves {0}",
        neg="{1} does not achieve {0}"),
    "achieved": dict(
        slots=["day", "goal"],
        pos="{1} is achieved on {0}",
        neg="{1} is not achieved on {0}"),
    "socialactivity": dict(slots=["activity"], pos="{0} is a social activity",
                           neg="{0} is not a social activity"),
    "exerciseactivity": dict(slots=["activity"], pos="{0} is an exercise activity",
                             neg="{0} is not an exercise activity"),
    "restingactivity": dict(slots=["activity"], pos="{0} is a resting activity",
                            neg="{0} is not a resting activity"),
    "creativeactivity": dict(slots=["activity"], pos="{0} is a creative activity",
                             neg="{0} is not a creative activity"),
    "choreactivity": dict(slots=["activity"], pos="{0} is a chore",
                          neg="{0} is not a chore"),
}

# zero-arity atoms (reified quotas etc.): pred -> (positive, negative)
ZERO = {
    "chorequota_met": ("the chore quota is met", "the chore quota is not met"),
    "socialquota_met": ("the social quota is met", "the social quota is not met"),
}

CMP_WORDS = {"!=": "differs from", "=": "is the same as", "<": "is before",
             ">": "is after", "<=": "is not after", ">=": "is not before"}
AGG_WORDS = {">=": "at least {n}", "<=": "at most {n}", "=": "exactly {n}",
             ">": "more than {n}", "<": "fewer than {n}", "!=": "anything but {n}"}

# ------------------------------------------------------------------- parsing
VAR = re.compile(r"^[A-Z]\w*$")
ARITH = re.compile(r"^([A-Z]\w*)\s*([+-])\s*(\d+)$")
LIT = re.compile(r"^(not\s+)?(-)?([a-z_]\w*)(?:\((.*)\))?$")
CMP = re.compile(r"^(.+?)\s*(!=|<=|>=|=|<|>)\s*(.+)$")
AGG_BRACE = re.compile(r"^\{\s*(.+?)\s*:\s*(.+?)\s*\}\s*(!=|<=|>=|=|<|>)\s*(\d+)$")
AGG_COUNT = re.compile(r"^(\d+)\s*(!=|<=|>=|=|<|>)\s*#count\s*\{\s*(.+?)\s*:\s*(.+?)\s*\}$")


def split_top(s, sep=","):
    """Split on `sep` outside of (...) and {...}."""
    out, depth, cur = [], 0, []
    for ch in s:
        if ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        out.append(tail)
    return out


def parse_literal(text):
    text = text.strip()
    m = AGG_BRACE.match(text)
    if m:
        elem = parse_literal(m.group(1))
        cond = [parse_literal(c) for c in split_top(m.group(2))]
        counted = next((c["args"][0] for c in cond
                        if c["kind"] == "atom" and c["pred"] in GUARDS), "X")
        cond = [c for c in cond if not is_guard(c)]
        return dict(kind="agg", var=counted, conds=[elem] + cond,
                    op=m.group(3), n=m.group(4), naf=False)
    m = AGG_COUNT.match(text)
    if m:
        return dict(kind="agg", var=m.group(3),
                    conds=[parse_literal(c) for c in split_top(m.group(4))],
                    op=m.group(2), n=m.group(1), naf=False)
    m = LIT.match(text)
    if m:
        args = split_top(m.group(4)) if m.group(4) else []
        return dict(kind="atom", naf=bool(m.group(1)), neg=bool(m.group(2)),
                    pred=m.group(3), args=args)
    m = CMP.match(text)
    if m:
        return dict(kind="cmp", a=m.group(1), op=m.group(2), b=m.group(3), naf=False)
    raise ValueError(f"cannot parse literal: {text!r}")


def is_guard(l):
    return (l["kind"] == "atom" and l["pred"] in GUARDS
            and len(l["args"]) == 1 and bool(VAR.match(l["args"][0])))


# -------------------------------------------------------------- type inference
def infer_types(lits):
    vt = {}

    def atoms(ls):
        for l in ls:
            if l["kind"] == "agg":
                yield from atoms(l["conds"])
            elif l["kind"] == "atom":
                yield l

    for a in atoms(lits):                       # pass 1: guards
        if is_guard(a):
            vt[a["args"][0]] = GUARDS[a["pred"]]
    for a in atoms(lits):                       # pass 2: argument slots
        spec = TEMPLATES.get(a["pred"])
        if not spec:
            continue
        for arg, typ in zip(a["args"], spec["slots"]):
            m = ARITH.match(arg)
            name = m.group(1) if m else arg
            if VAR.match(name):
                vt.setdefault(name, typ)
    for l in lits:                              # pass 3: comparisons (propagate)
        if l["kind"] == "cmp":
            for x, y in ((l["a"], l["b"]), (l["b"], l["a"])):
                if VAR.match(x) and x not in vt and y in vt:
                    vt[x] = vt[y]
    return vt


# ----------------------------------------------------------------- rendering
def render_term(t, typ, vt):
    m = ARITH.match(t)
    if m:
        return f"the day {'after' if m.group(2) == '+' else 'before'} day {m.group(1)}" \
            if int(m.group(3)) == 1 else f"{m.group(1)}{m.group(2)}{m.group(3)}"
    if VAR.match(t):
        return f"{NOUN.get(vt.get(t, typ), 'value')} {t}"
    if typ == "day" and t.isdigit():
        return DAY_NAMES.get(int(t), f"day {t}").capitalize()
    return t


def render_atom(l, vt):
    pred, args = l["pred"], l["args"]
    if not args:
        pos, neg = ZERO.get(pred, (pred.replace("_", " "),
                                   "not " + pred.replace("_", " ")))
        return neg if l["neg"] else pos
    spec = TEMPLATES.get(pred)
    if spec is None:
        text = f"{pred} holds for " + ", ".join(render_term(a, None, vt) for a in args)
        return text.replace("holds for", "does not hold for") if l["neg"] else text
    pos, neg = spec["pos"], spec["neg"]
    for (i, val), (p, n) in spec.get("variants", {}).items():
        if len(args) > i and args[i] == val:
            pos, neg = p, n
    terms = [render_term(a, t, vt) for a, t in zip(args, spec["slots"])]
    return (neg if l["neg"] else pos).format(*terms)


def and_join(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def render_literal(l, vt):
    if l["kind"] == "atom":
        return render_atom(l, vt)
    if l["kind"] == "cmp":
        ta = vt.get(l["a"]) or vt.get(l["b"])
        tb = vt.get(l["b"]) or vt.get(l["a"])
        return (f"{render_term(l['a'], ta, vt)} {CMP_WORDS[l['op']]} "
                f"{render_term(l['b'], tb, vt)}")
    if l["kind"] == "agg":
        typ = vt.get(l["var"], "value")
        conds = [render_literal(c, vt) for c in l["conds"]]
        return (f"there are {AGG_WORDS[l['op']].format(n=l['n'])} {PLURAL[typ]} "
                f"{l['var']} such that {and_join(conds)}")
    raise ValueError(l)


def cap(s):
    return s[0].upper() + s[1:]


# --------------------------------------------------------------------- API
def verbalize_rule(head, body="", kind=None):
    hl = parse_literal(head) if head.strip() else None
    bl = [parse_literal(x) for x in split_top(body)] if body.strip() else []
    vt = infer_types(([hl] if hl else []) + bl)
    shown = [l for l in bl if not is_guard(l)]
    conds = [render_literal(l, vt) if not l["naf"]
             else f"it cannot be shown that {render_literal(l, vt)}" for l in shown]
    if kind is None:
        kind = "constraint" if hl is None else \
            "default" if any(l["naf"] for l in bl) else "knowledge"
    if hl is None:
        return cap(f"it is impossible that {and_join(conds)}.")
    h = render_literal(hl, vt)
    if kind == "default":
        return cap(f"by default, {h}" + (f", provided that {and_join(conds)}." if conds else "."))
    return cap(f"if {and_join(conds)}, then {h}.") if conds else cap(f"{h}.")


def verbalize_fact(fact):
    return verbalize_rule(fact)


def verbalize_preferences(prefs):
    return [f"{i}. {verbalize_preference(p)}" for i, p in enumerate(prefs, 1)]


# ------------------------------------------------- safe helpers for the GUI
# These never raise: anything the parser can't handle (e.g. an unusual rule
# typed on the "General correction" screen) is shown as-is instead.
_PARSE_ERRORS = (ValueError, KeyError, IndexError)


def describe_atom(atom):
    """A single ground atom (str or clingo.Symbol) as an English clause,
    without a trailing period, e.g. "the goal on Tuesday is exercising"."""
    text = str(atom)
    try:
        return render_literal(parse_literal(text), {})
    except _PARSE_ERRORS:
        return text


def verbalize_atom(atom):
    """Like `describe_atom`, but capitalised - for standalone labels."""
    return cap(describe_atom(atom))


def describe_rule(rule):
    """`verbalize_rule` for a (head, body) pair, falling back to the raw
    formula if it can't be parsed."""
    head, body = rule
    try:
        return verbalize_rule(head, body)
    except _PARSE_ERRORS:
        return f"{body} implies {head}" if head.strip() else f"{body} is not allowed"


def verbalize_preference(atom):
    return f"Prefer that {describe_atom(atom)}."


if __name__ == "__main__":
    import domain as d

    def section(title, rules, kind=None):
        print(f"\n== {title} ==")
        for head, body in rules:
            print("-", verbalize_rule(head, body, kind))

    print("== Default facts ==")
    for f in d.DEFAULT_CONTEXT_FACTS + d.DEFAULT_GOAL_FACTS + d.DEFAULT_ACTION_FACTS:
        print("-", verbalize_fact(f))
    section("Context knowledge", d.CONTEXT_KNOWLEDGE)
    section("Goal knowledge", d.GOAL_KNOWLEDGE)
    section("Action knowledge", d.ACTION_KNOWLEDGE)
    section("Context defaults", d.CONTEXT_DEFAULTS, "default")
    section("Goal defaults", d.GOAL_DEFAULTS, "default")
    section("Action defaults / constraints", d.ACTION_DEFAULTS)
    for title, prefs in (("Context preferences", d.CONTEXT_PREFERENCES),
                         ("Goal preferences", d.GOAL_PREFERENCES),
                         ("Action preferences", d.ACTION_PREFERENCES)):
        print(f"\n== {title} (highest first) ==")
        print("\n".join(verbalize_preferences(prefs)))
