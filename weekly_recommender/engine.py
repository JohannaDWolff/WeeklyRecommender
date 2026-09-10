"""Stateful recommender engine: owns the mutable fact/rule base, runs the
multi-stage ASP solve, and answers "why" questions for the GUI.

This replaces the module-level globals and string-index parsing of the
original prototype with an explicit class and clingo's Symbol API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

import clingo

import domain
from solver import (
    AnswerSet,
    parse_preferences,
    preference_rank,
    rank_by_preference,
    render_rules,
    render_statements,
    solve,
)


class Recommendation(NamedTuple):
    day: str
    goal: str
    action: str


class Explanation(NamedTuple):
    fact: clingo.Symbol
    rule: tuple[str, str]  # (head, body) as written in domain.py
    prerequisites: list[clingo.Symbol]


class ProposedFact(NamedTuple):
    """The fact the user just tried to add. Offered as a resolution option
    meaning "don't add it" - it was never actually inserted into the fact
    base, so resolving via this option requires no removal at all."""

    category: str
    fact: str


class RemovableFact(NamedTuple):
    """An existing fact that, if removed, would resolve a conflict."""

    category: str
    fact: str


class RemovableRule(NamedTuple):
    """A hard-knowledge rule that, if removed, would resolve a conflict."""

    rule: tuple[str, str]


ConflictOption = ProposedFact | RemovableFact | RemovableRule


class PreferenceExplanation(NamedTuple):
    """Why `fact` - true in one of this stage's own answer sets - wasn't
    the one picked. `tie` means neither side actually won on preference:
    the current pick only came out first because of arbitrary solver
    ordering, not because it matched an earlier preference."""

    category: str
    fact: str
    current_preference: str | None  # preference the chosen answer set matched, if any
    desired_preference: str | None  # preference the best alternative matched, if any
    tie: bool


class EngineState(NamedTuple):
    """A snapshot of everything `RecommenderEngine` mutates, so the GUI's
    back button can restore it and undo whatever changes were made on the
    screen it's leaving."""

    context_facts: list[str]
    goal_facts: list[str]
    action_facts: list[str]
    hard_rules: list[tuple[str, str]]
    context_preferences: list[str]
    goal_preferences: list[str]
    action_preferences: list[str]
    knowledge_solution: AnswerSet | None
    context_solution: AnswerSet | None
    goal_solution: AnswerSet | None
    action_solution: AnswerSet | None
    context_answer_sets: list[AnswerSet]
    goal_answer_sets: list[AnswerSet]
    action_answer_sets: list[AnswerSet]


class ConflictReport(NamedTuple):
    """Why `add_fact` failed, and every fact/rule whose removal would
    resolve it (always including the proposed fact itself, as a "don't add
    it" option)."""

    message: str
    options: list[ConflictOption]


class Inconsistent(Exception):
    """Raised when a proposed fact would make the knowledge base
    unsatisfiable. `report` is set for conflicts raised by `add_fact` (see
    `ConflictReport`) and `None` for other, unrelated solve failures (e.g.
    `run_pipeline`)."""

    def __init__(self, message: str, report: ConflictReport | None = None) -> None:
        super().__init__(message)
        self.report = report


def _negate(fact: str) -> str:
    return fact[1:] if fact.startswith("-") else f"-{fact}"


def replacement_fact(old_fact: str, new_value: str) -> str:
    """Rebuild `old_fact` (e.g. `dailygoal(7,creativity)`) with its trailing
    argument swapped for `new_value` - every tracked fact is
    `predicate(day, value)`, so only the value ever needs to change."""
    symbol = clingo.parse_term(old_fact)
    return f"{symbol.name}({symbol.arguments[0]},{new_value.strip()})"


_NEG_PREFIX = "neg__"


def split_body(body: str) -> list[str]:
    """Split an ASP rule body into its top-level comma-separated literals,
    ignoring commas nested inside a literal's argument list."""
    terms = []
    depth = 0
    current = []
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            terms.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        terms.append("".join(current).strip())
    return terms


@dataclass
class RecommenderEngine:
    context_facts: list[str] = field(default_factory=lambda: list(domain.DEFAULT_CONTEXT_FACTS))
    goal_facts: list[str] = field(default_factory=lambda: list(domain.DEFAULT_GOAL_FACTS))
    action_facts: list[str] = field(default_factory=lambda: list(domain.DEFAULT_ACTION_FACTS))
    # All non-default ("hard") rules, mutable so any of them can be removed
    # as a conflict-resolution option - not just the goal ones, as before.
    hard_rules: list[tuple[str, str]] = field(
        default_factory=lambda: list(
            domain.CONTEXT_KNOWLEDGE + domain.GOAL_KNOWLEDGE + domain.ACTION_KNOWLEDGE
        )
    )
    context_preferences: list[str] = field(
        default_factory=lambda: list(domain.CONTEXT_PREFERENCES)
    )
    goal_preferences: list[str] = field(default_factory=lambda: list(domain.GOAL_PREFERENCES))
    action_preferences: list[str] = field(
        default_factory=lambda: list(domain.ACTION_PREFERENCES)
    )

    knowledge_solution: AnswerSet | None = field(default=None, init=False)
    context_solution: AnswerSet | None = field(default=None, init=False)
    goal_solution: AnswerSet | None = field(default=None, init=False)
    action_solution: AnswerSet | None = field(default=None, init=False)
    context_answer_sets: list[AnswerSet] = field(default_factory=list, init=False)
    goal_answer_sets: list[AnswerSet] = field(default_factory=list, init=False)
    action_answer_sets: list[AnswerSet] = field(default_factory=list, init=False)

    # -- Snapshot/restore, for the GUI's back button to undo mutations -----

    def snapshot(self) -> EngineState:
        return EngineState(
            context_facts=list(self.context_facts),
            goal_facts=list(self.goal_facts),
            action_facts=list(self.action_facts),
            hard_rules=list(self.hard_rules),
            context_preferences=list(self.context_preferences),
            goal_preferences=list(self.goal_preferences),
            action_preferences=list(self.action_preferences),
            knowledge_solution=self.knowledge_solution,
            context_solution=self.context_solution,
            goal_solution=self.goal_solution,
            action_solution=self.action_solution,
            context_answer_sets=list(self.context_answer_sets),
            goal_answer_sets=list(self.goal_answer_sets),
            action_answer_sets=list(self.action_answer_sets),
        )

    def restore(self, state: EngineState) -> None:
        self.context_facts = list(state.context_facts)
        self.goal_facts = list(state.goal_facts)
        self.action_facts = list(state.action_facts)
        self.hard_rules = list(state.hard_rules)
        self.context_preferences = list(state.context_preferences)
        self.goal_preferences = list(state.goal_preferences)
        self.action_preferences = list(state.action_preferences)
        self.knowledge_solution = state.knowledge_solution
        self.context_solution = state.context_solution
        self.goal_solution = state.goal_solution
        self.action_solution = state.action_solution
        self.context_answer_sets = list(state.context_answer_sets)
        self.goal_answer_sets = list(state.goal_answer_sets)
        self.action_answer_sets = list(state.action_answer_sets)

    # -- Stage 1: compile the static knowledge base (vocabulary + facts) ----

    def _knowledge_base_program(
        self,
        context_facts: list[str] | None = None,
        goal_facts: list[str] | None = None,
        action_facts: list[str] | None = None,
    ) -> str:
        return (
            render_statements(domain.CONTEXT_DEFINITIONS)
            + render_statements(context_facts if context_facts is not None else self.context_facts)
            + render_statements(domain.GOAL_DEFINITIONS)
            + render_statements(goal_facts if goal_facts is not None else self.goal_facts)
            + render_statements(domain.ACTION_DEFINITIONS)
            + render_statements(action_facts if action_facts is not None else self.action_facts)
            + "#defined dailyaction/2. #defined dailyfriendavailable/2. "
        )

    def _hard_rules_text(self) -> str:
        """The non-default rules, rendered as ASP text. These stay in scope
        for every solving stage, since later stages depend on predicates
        (like `achieves/2`) that only the hard rules define."""
        return render_rules(self.hard_rules)

    def _solve_knowledge_base(self) -> list[AnswerSet]:
        return solve(self._hard_rules_text(), self._knowledge_base_program())

    # -- Full pipeline: context defaults -> goal defaults -> action defaults

    def run_pipeline(self) -> list[AnswerSet]:
        """Solve context, then goals, then actions, feeding each stage's
        top-ranked answer set into the next. Returns the ranked action-stage
        answer sets (the first is the chosen recommendation)."""
        knowledge_sets = self._solve_knowledge_base()
        if not knowledge_sets:
            raise Inconsistent("The fact base is contradictory.")
        self.knowledge_solution = knowledge_sets[0]

        context_sets = solve(
            self._hard_rules_text() + self.knowledge_solution.as_program(),
            render_rules(domain.CONTEXT_DEFAULTS) + "#defined dailyaction/2. ",
        )
        if not context_sets:
            raise Inconsistent("No consistent context defaults.")
        self.context_answer_sets = context_sets
        self.context_solution = rank_by_preference(context_sets, self.context_preferences)[0]

        goal_sets = solve(
            self._hard_rules_text() + self.context_solution.as_program(),
            render_rules(domain.GOAL_DEFAULTS) + "#defined dailyaction/2. ",
        )
        if not goal_sets:
            raise Inconsistent("No consistent goal defaults.")
        self.goal_answer_sets = goal_sets
        self.goal_solution = rank_by_preference(goal_sets, self.goal_preferences)[0]

        action_sets = solve(
            self._hard_rules_text() + self.goal_solution.as_program(),
            render_rules(domain.ACTION_DEFAULTS) + render_rules(domain.OUTPUT_FORMATTING_RULES),
        )
        if not action_sets:
            raise Inconsistent("No consistent action defaults.")
        self.action_answer_sets = action_sets
        ranked_action_sets = rank_by_preference(action_sets, self.action_preferences)
        self.action_solution = ranked_action_sets[0]
        return ranked_action_sets

    def recommend(self) -> list[Recommendation]:
        """Run the pipeline and return the top-ranked week's recommendations."""
        return self.recommendations_from(self.run_pipeline()[0])

    @staticmethod
    def recommendations_from(answer_set: AnswerSet) -> list[Recommendation]:
        recommendations = [
            Recommendation(day=str(args[0]), goal=str(args[1]), action=str(args[2]))
            for symbol in answer_set.matching("recommendation", 3)
            for args in [symbol.arguments]
        ]
        recommendations.sort(key=lambda rec: domain.DAY_NUMBERS[rec.day])
        return recommendations

    def relevant_context(self, day_number: int) -> list[clingo.Symbol]:
        """The positive context facts recorded for `day_number` in the last
        context solve (e.g. `dailyenergylevel(2,high)`) - the classically
        negated ones the context defaults also derive (e.g.
        `-dailyenergylevel(2,low)`, `-dailyenergylevel(2,medium)`) are what
        that value *isn't*, not relevant context to show."""
        if self.context_solution is None:
            return []
        return [
            symbol
            for factor in domain.CONTEXT_FACTORS
            for symbol in self.context_solution.matching(factor, 2)
            if symbol.positive and symbol.arguments[0] == clingo.Number(day_number)
        ]

    # -- Explanation: trace a fact back to the hard-rule of shape ----------
    # -- `dailygoal(D,G) :- ...` that produced it, and its prerequisites in
    # -- the knowledge-base stage. ------------------------------------------

    def explain_goal(self, day_number: int, goal: str) -> Explanation | None:
        """Find the hard-knowledge rule of shape `dailygoal(D,G) :- ...`
        that derives `dailygoal(day_number, goal)`, using only an action
        already established *before* the goal-defaults stage (stage 3) ran
        - i.e. present in `context_solution`, which reflects stage 1 (the
        knowledge base: explicit facts + hard rules) and stage 2 (context
        defaults) only. The action-defaults stage (4) runs *after* goals
        are decided and typically picks an action *because of* the goal
        already set in stage 3 - explaining the goal via that action would
        be circular, so such actions (present only in `action_solution`,
        not yet in `context_solution`) don't count as an explanation here.
        (Weekend days can have two actions, one per goal, so matching on
        day alone isn't enough - it must also be one that achieves this
        specific goal.)"""
        fact = clingo.parse_term(f"dailygoal({day_number},{goal})")

        if self.context_solution is None:
            return None

        candidate_actions = {
            symbol.arguments[1]
            for symbol in self.context_solution.matching("dailyaction", 2)
            if symbol.positive and symbol.arguments[0] == clingo.Number(day_number)
        }
        actions_for_goal = {
            symbol.arguments[1]
            for symbol in self.context_solution.matching("achieves", 2)
            if symbol.positive and str(symbol.arguments[0]) == goal
        }
        action = next(iter(candidate_actions & actions_for_goal), None)
        if action is None:
            return None

        for rule in self.hard_rules:
            head, body = rule
            if head.replace(" ", "") != "dailygoal(D,G)":
                continue

            substituted_body = (
                body.replace("D", str(day_number)).replace("G", goal).replace("A", str(action))
            )
            prerequisite_terms = split_body(substituted_body)

            prerequisites = []
            for term in prerequisite_terms:
                try:
                    prerequisites.append(clingo.parse_term(term))
                except RuntimeError:
                    continue

            return Explanation(fact=fact, rule=rule, prerequisites=prerequisites)

        return None

    def remove_rule(self, rule: tuple[str, str]) -> None:
        self.hard_rules.remove(rule)

    # -- Explaining a default value that lost to preference ranking --------

    def explain_preference(self, category: str, fact: str) -> PreferenceExplanation | None:
        """If `fact` is already true in one of this stage's own answer sets,
        explain why it wasn't the one chosen. Returns None if `fact` isn't
        achievable at this stage at all (the caller should fall back to
        `add_fact`)."""
        symbol = clingo.parse_term(fact)
        stage_answer_sets = getattr(self, f"{category}_answer_sets")
        matching = [answer_set for answer_set in stage_answer_sets if symbol in answer_set]
        if not matching:
            return None

        preferences = getattr(self, f"{category}_preferences")
        parsed = parse_preferences(preferences)
        desired = rank_by_preference(matching, preferences)[0]
        desired_rank = preference_rank(desired, parsed)
        current_solution = getattr(self, f"{category}_solution")
        current_rank = preference_rank(current_solution, parsed)

        return PreferenceExplanation(
            category=category,
            fact=fact,
            current_preference=(
                preferences[current_rank] if current_rank < len(preferences) else None
            ),
            desired_preference=(
                preferences[desired_rank] if desired_rank < len(preferences) else None
            ),
            tie=(current_rank == desired_rank),
        )

    def prefer(self, category: str, fact: str) -> None:
        """Give `fact` top priority in this stage's preferences, so the next
        solve picks an answer set containing it (ties still resolved by
        solver order - see `PreferenceExplanation.tie`)."""
        getattr(self, f"{category}_preferences").insert(0, fact)

    # -- Editing the fact base -------------------------------------------

    def remove_fact(self, category: str, fact: str) -> None:
        getattr(self, f"{category}_facts").remove(fact)

    def add_fact(self, category: str, fact: str) -> None:
        """Add a fact, after checking it does not contradict the existing
        fact base. On failure, `Inconsistent.report` carries a
        `ConflictReport`: why it failed, and every fact/rule (including the
        proposed fact itself) whose removal would resolve it - see
        `_report_direct_conflict` and `_report_deep_conflict`."""
        negation = clingo.parse_term(_negate(fact))
        baseline = self._solve_knowledge_base()
        if baseline and negation in baseline[0]:
            report = self._report_direct_conflict(category, fact, negation)
            raise Inconsistent(report.message, report)

        trial_facts = {
            "context": list(self.context_facts),
            "goal": list(self.goal_facts),
            "action": list(self.action_facts),
        }
        trial_facts[category].append(fact)
        program = self._knowledge_base_program(**{
            f"{key}_facts": value for key, value in trial_facts.items()
        })
        if solve(self._hard_rules_text(), program):
            getattr(self, f"{category}_facts").append(fact)
            return

        report = self._report_deep_conflict(category, fact, trial_facts, program)
        raise Inconsistent(report.message, report)

    def _report_direct_conflict(
        self, category: str, fact: str, negation: clingo.Symbol
    ) -> ConflictReport:
        """`negation` is already true before `fact` is even added: point to
        the explicit fact or hard-knowledge rule responsible, offering it
        (and abandoning `fact`) as resolution options."""
        options: list[ConflictOption] = [ProposedFact(category, fact)]

        for existing_category in ("context", "goal", "action"):
            for existing in getattr(self, f"{existing_category}_facts"):
                if clingo.parse_term(existing) == negation:
                    options.append(RemovableFact(existing_category, existing))
                    return ConflictReport(
                        message=f"{fact} contradicts the existing fact {existing}.",
                        options=options,
                    )

        rule = self._find_rule_for(negation)
        if rule is not None:
            options.append(RemovableRule(rule))
            head, body = rule
            return ConflictReport(
                message=f"{fact} contradicts the rule `{head} :- {body}`, "
                f"which already derives {negation}.",
                options=options,
            )

        return ConflictReport(
            message=f"{fact} contradicts {negation}, which already holds in the knowledge base.",
            options=options,
        )

    def _report_deep_conflict(
        self, category: str, fact: str, trial_facts: dict[str, list[str]], program: str
    ) -> ConflictReport:
        """Explain a contradiction that only appears once `fact` combines
        with the rest of the knowledge base: which existing fact(s) are (at
        least partly) responsible (`_find_conflicting_facts`), and which
        ground atom ends up derived both true and classically false, along
        with the rule deriving each side (`_find_contradictions` /
        `_find_rule_for`) - all offered as resolution options, alongside
        abandoning `fact` itself."""
        lines = []
        options: list[ConflictOption] = [ProposedFact(category, fact)]

        culprits = self._find_conflicting_facts(category, fact, trial_facts)
        if culprits:
            lines.append(
                f"Adding {fact} conflicts with: {', '.join(f.fact for f in culprits)}."
            )
            options.extend(culprits)
        else:
            lines.append(
                f"Adding {fact} makes the knowledge base contradictory "
                "(the conflict only appears when several existing facts combine)."
            )

        for positive, negative in self._find_contradictions(program):
            lines.append(f"Both {positive} and {negative} end up derivable:")
            for target in (positive, negative):
                rule = self._find_rule_for(target, program)
                if rule is not None:
                    lines.append(f"  > {target} from `{rule[0].strip()} :- {rule[1]}`")
                    options.append(RemovableRule(rule))

        # De-duplicate while preserving order (the same rule can derive more
        # than one clashing pair).
        options = list(dict.fromkeys(options))
        return ConflictReport(message="\n".join(lines), options=options)

    # -- Diagnosing a contradiction: which ground atom clashes, and which --
    # -- rule derives each side of it. ---------------------------------------
    #
    # The hard-knowledge rules never reference a classically negated atom in
    # a *body* (only in a head), which is asserted in `_rewrite_diagnostic`
    # below. That means renaming every negated head (`-p(...)`) to a fresh,
    # unnegated predicate (`neg__p(...)`) turns them into a plain stratified
    # Datalog program - no classical negation left to clash - which always
    # has exactly one answer set, even over facts that are contradictory
    # under the real rules. This rewrite is only ever used to build a
    # disposable copy of the rules for one throwaway diagnostic solve; the
    # live rule set (`self.hard_rules`) is never touched.

    def _rewrite_diagnostic(self, rules: list[tuple[str, str]]) -> list[tuple[str, str]]:
        rewritten = []
        for head, body in rules:
            for term in split_body(body):
                assert not term.startswith("-"), (
                    "diagnostic rewrite assumes rule bodies never reference a "
                    f"classically negated atom, but {head!r} has {term!r} in its body"
                )
            stripped_head = head.strip()
            if stripped_head.startswith("-"):
                head = _NEG_PREFIX + stripped_head[1:]
            rewritten.append((head, body))
        return rewritten

    def _diagnostic_hard_rules(self) -> list[tuple[str, str]]:
        return self._rewrite_diagnostic(self.hard_rules)

    @staticmethod
    def _diagnostic_symbol(symbol: clingo.Symbol) -> clingo.Symbol:
        if symbol.positive:
            return symbol
        return clingo.Function(_NEG_PREFIX + symbol.name, symbol.arguments)

    def _find_rule_for(
        self, target: clingo.Symbol, program: str | None = None
    ) -> tuple[str, str] | None:
        """Find a hard-knowledge rule that derives `target` from `program`'s
        facts (defaults to the current knowledge base), by removing
        candidate rules from a negation-free diagnostic rewrite one at a
        time and checking whether the (rewritten) target disappears. Using
        the rewrite keeps this well-defined even when `program` is
        contradictory under the real rules - removing a rule from the
        actual rule set could leave it just as contradictory, which would
        make "target no longer derived" ambiguous with "still stuck"."""
        if program is None:
            program = self._knowledge_base_program()
        rules = self.hard_rules
        signature = ("-" if not target.positive else "") + target.name
        diagnostic_target = self._diagnostic_symbol(target)
        candidates = [
            rule for rule in rules if rule[0].replace(" ", "").split("(")[0] == signature
        ]
        for rule in candidates:
            reduced = [r for r in rules if r != rule]
            results = solve(render_rules(self._rewrite_diagnostic(reduced)), program)
            if not results or diagnostic_target not in results[0]:
                return rule
        return None

    def _find_contradictions(self, program: str) -> list[tuple[clingo.Symbol, clingo.Symbol]]:
        """Diagnose exactly which ground atoms are forced both true and
        classically false by the hard rules over `program`'s facts
        (`program` is assumed to be contradictory under the real rules).
        Returns (positive, negative) symbol pairs."""
        results = solve(render_rules(self._diagnostic_hard_rules()), program)
        if not results:
            return []
        model = results[0]
        pairs = []
        for symbol in model.symbols:
            if symbol.name.startswith(_NEG_PREFIX):
                positive = clingo.Function(symbol.name[len(_NEG_PREFIX):], symbol.arguments)
                if positive in model:
                    negative = clingo.Function(positive.name, positive.arguments, False)
                    pairs.append((positive, negative))
        return pairs

    def _find_conflicting_facts(
        self, category: str, fact: str, trial_facts: dict[str, list[str]]
    ) -> list[RemovableFact]:
        """Facts in `trial_facts` (which already includes `fact` under
        `category`) that, individually removed, would let `fact` be added
        without contradiction - i.e. each one is (at least partly)
        responsible for the conflict."""
        hard_rules = self._hard_rules_text()
        culprits = []
        for existing_category, facts in trial_facts.items():
            for existing in facts:
                if existing_category == category and existing == fact:
                    continue
                trial = {key: list(value) for key, value in trial_facts.items()}
                trial[existing_category].remove(existing)
                program = self._knowledge_base_program(**{
                    f"{key}_facts": value for key, value in trial.items()
                })
                if solve(hard_rules, program):
                    culprits.append(RemovableFact(existing_category, existing))
        return culprits
