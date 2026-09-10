"""Tkinter front-end for the weekly recommender.

State (facts, rules, last solve results) lives in a RecommenderEngine
instance owned by this App - no module-level globals. Widget placement goes
through RowLayout so rows are always allocated dynamically: no two widgets
can ever be handed the same fixed row number and end up overlapping.
"""
from __future__ import annotations

from tkinter import N, S, E, W, StringVar, Tk
from tkinter import ttk
from typing import Callable

import domain
from engine import (
    ConflictOption,
    Explanation,
    Inconsistent,
    ProposedFact,
    Recommendation,
    RecommenderEngine,
    RemovableFact,
    RemovableRule,
)


class RowLayout:
    """Places widgets in a frame's grid, one row at a time, tracking the
    next free row itself so callers never juggle row numbers by hand."""

    def __init__(self, frame: ttk.Frame) -> None:
        self.frame = frame
        self.row = 0

    def label(self, text: str, wraplength: int = 460) -> ttk.Label:
        widget = ttk.Label(self.frame, text=text, wraplength=wraplength, justify="left")
        widget.grid(column=1, row=self.row, sticky=(W, E))
        self.row += 1
        return widget

    def button(self, text: str, command: Callable[[], None] | None = None) -> ttk.Button:
        widget = ttk.Button(self.frame, text=text, command=command)
        widget.grid(column=1, row=self.row, sticky=W)
        self.row += 1
        return widget

    def button_pair(
        self, left: tuple[str, Callable[[], None] | None], right: tuple[str, Callable[[], None] | None]
    ) -> tuple[ttk.Button, ttk.Button]:
        """Two buttons side by side on the same row."""
        left_widget = ttk.Button(self.frame, text=left[0], command=left[1])
        left_widget.grid(column=1, row=self.row, sticky=W)
        right_widget = ttk.Button(self.frame, text=right[0], command=right[1])
        right_widget.grid(column=2, row=self.row, sticky=W)
        self.row += 1
        return left_widget, right_widget

    def label_var(self, textvariable: StringVar) -> ttk.Label:
        widget = ttk.Label(self.frame, textvariable=textvariable)
        widget.grid(column=1, row=self.row, sticky=(W, E))
        self.row += 1
        return widget

    def entry(self, textvariable: StringVar, width: int = 81) -> ttk.Entry:
        widget = ttk.Entry(self.frame, width=width, textvariable=textvariable)
        widget.grid(column=1, row=self.row, sticky=W)
        self.row += 1
        return widget


class App:
    def __init__(self) -> None:
        self.engine = RecommenderEngine()
        self.root = Tk()
        self.root.title("Weekly Recommendations")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.current_frame: ttk.Frame | None = None
        self.layout: RowLayout | None = None
        self._history: list[Callable[[], None]] = []
        self._current_render: Callable[[], None] | None = None
        self._show(lambda: self.show_recommendations(self.engine.recommend()))

    def run(self) -> None:
        self.root.mainloop()

    # -- Navigation -----------------------------------------------------
    #
    # Every screen transition goes through `_show`, which always builds a
    # fresh frame (via `_new_frame`), so a screen's widgets never linger
    # once you've moved past it. `_show` pushes the render function that
    # built the *previous* screen onto a history stack, and `_go_back`
    # re-runs it - "undo" without needing separate state to reverse.

    def _show(self, render: Callable[[], None]) -> None:
        if self._current_render is not None:
            self._history.append(self._current_render)
        self._current_render = render
        render()

    def _go_back(self) -> None:
        if not self._history:
            return
        render = self._history.pop()
        self._current_render = None  # don't re-push the screen we're leaving
        self._show(render)

    # -- Frame management --------------------------------------------------

    def _new_frame(self) -> RowLayout:
        if self.current_frame is not None:
            self.current_frame.destroy()
        frame = ttk.Frame(self.root, padding="20 20 20 90")
        frame.grid(column=0, row=0, sticky=(N, W, E, S))
        self.current_frame = frame
        self.layout = RowLayout(frame)
        if self._history:
            self.layout.button("← Back", command=self._go_back)
        return self.layout

    # -- Screen 1: the weekly recommendation --------------------------------

    def show_recommendations(self, recommendations: list[Recommendation]) -> None:
        layout = self._new_frame()
        layout.label("Recommendation for this week:")

        for rec in recommendations:
            layout.label(f"{rec.day.capitalize()}: {rec.action} for {rec.goal}")

        feedback = StringVar()

        def accept() -> None:
            accept_button.grid_forget()
            reject_button.grid_forget()
            feedback.set("Have a great week!")

        accept_button, reject_button = layout.button_pair(
            ("Accept", accept), ("Do Not Accept", lambda: self._show(self.show_rejection_picker))
        )
        layout.label_var(feedback)

    # -- Screen 2: pick which day's recommendation is wrong -----------------

    def show_rejection_picker(self) -> None:
        layout = self._new_frame()
        layout.label("Which recommendation do you disagree with?")

        for rec in self.engine.recommend():
            layout.button(
                f"{rec.day}: {rec.action} for {rec.goal}",
                command=lambda rec=rec: self._show(lambda: self.show_explanation(rec)),
            )

    # -- Screen 3: break a recommendation down into context/goal/action -----

    def show_explanation(self, recommendation: Recommendation) -> None:
        layout = self._new_frame()
        day_number = domain.DAY_NUMBERS[recommendation.day]

        layout.label("What exactly is the problem?")
        layout.label("relevant context:")

        for symbol in self.engine.relevant_context(day_number):
            layout.button(
                str(symbol),
                command=lambda symbol=symbol, day_number=day_number: self._show(
                    lambda: self.show_context_problem(symbol, day_number)
                ),
            )

        layout.label("Selected goal:")
        layout.button(
            recommendation.goal,
            command=lambda: self._show(
                lambda: self.show_goal_problem(recommendation.goal, day_number)
            ),
        )

        layout.label("Selected action:")
        layout.button(
            recommendation.action,
            command=lambda: self._show(
                lambda: self.show_action_problem(recommendation.action, day_number)
            ),
        )

    # -- "Why" drill-down for context/goal/action facts ----------------------

    def show_context_problem(self, symbol, day_number: int) -> None:
        layout = self._new_frame()
        day_name = domain.DAY_NAMES[day_number].capitalize()
        layout.label(f"You disagree with the identified context: {symbol} on {day_name}")

        fact = str(symbol)
        matching_fact = next((f for f in self.engine.context_facts if f == fact), None)
        if matching_fact is not None:
            self._offer_fact_removal(layout, "context", matching_fact)
        else:
            layout.label("This is a direct result of the knowledge base.")

    def show_goal_problem(self, goal: str, day_number: int) -> None:
        layout = self._new_frame()
        day_name = domain.DAY_NAMES[day_number].capitalize()
        layout.label(f"You disagree with the selected goal: {goal} on {day_name}")

        fact = f"dailygoal({day_number},{goal})"
        if fact in self.engine.goal_facts:
            self._offer_fact_removal(layout, "goal", fact)
            return

        explanation = self.engine.explain_goal(day_number, goal)
        if explanation is None:
            layout.label("not part of the knowledge base")
            return

        layout.label("This is a direct result of the knowledge base:")
        self._show_rule_explanation(layout, explanation)

    def show_action_problem(self, action: str, day_number: int) -> None:
        layout = self._new_frame()
        day_name = domain.DAY_NAMES[day_number].capitalize()
        layout.label(f"You disagree with the selected action: {action} on {day_name}")

        fact = f"dailyaction({day_number},{action})"
        matching_fact = next((f for f in self.engine.action_facts if f == fact), None)
        if matching_fact is not None:
            self._offer_fact_removal(layout, "action", matching_fact)
        else:
            layout.label("This is a direct result of the knowledge base.")

    def _show_rule_explanation(self, layout: RowLayout, explanation: Explanation) -> None:
        head, body = explanation.rule
        layout.label(f"{explanation.fact} comes from the following rule:")
        layout.button(
            f"{body} implies {head}",
            command=lambda: self.remove_rule(explanation.rule),
        )

        layout.label("and the following prerequisites:")
        for prerequisite in explanation.prerequisites:
            layout.button(
                str(prerequisite),
                command=lambda prerequisite=prerequisite: self._show(
                    lambda: self.show_prerequisite_problem(prerequisite)
                ),
            )

    def show_prerequisite_problem(self, symbol) -> None:
        layout = self._new_frame()
        layout.label(f"You disagree with the prerequisite: {symbol}")

        fact = str(symbol)
        for category in ("context", "goal", "action"):
            facts = getattr(self.engine, f"{category}_facts")
            if fact in facts:
                self._offer_fact_removal(layout, category, fact)
                return
        layout.label("This is a direct result of the knowledge base.")

    def _offer_fact_removal(self, layout: RowLayout, category: str, fact: str) -> None:
        layout.label("This information was entered as a fact. Would you like to remove it?")
        layout.button_pair(
            ("Yes", lambda: self.remove_fact(category, fact)),
            ("No", self._go_back),
        )

    # -- Actions that mutate the engine and re-solve -------------------------

    def remove_rule(self, rule) -> None:
        self.engine.remove_rule(rule)
        self._show(self.show_updated_recommendation)

    def remove_fact(self, category: str, fact: str) -> None:
        self.engine.remove_fact(category, fact)
        self._show(lambda: self.show_add_replacement_fact(category))

    def show_add_replacement_fact(self, category: str) -> None:
        layout = self._new_frame()
        layout.label("Would you like to add a different fact instead?")

        new_fact = StringVar()
        layout.entry(new_fact)
        layout.button("Enter", command=lambda: self.add_fact(category, new_fact.get()))
        layout.button("Skip", command=lambda: self._show(self.show_updated_recommendation))

    def add_fact(self, category: str, fact: str) -> None:
        try:
            self.engine.add_fact(category, fact)
        except Inconsistent as error:
            if error.report is not None:
                # Capture into a local: `error` is cleared once this except
                # block exits, but the lambda may run later (e.g. via Back).
                report = error.report
                self._show(lambda: self.show_conflict_report(report))
            else:
                self.layout.label(str(error))
            return
        self._show(self.show_updated_recommendation)

    def show_conflict_report(self, report) -> None:
        """Render a ConflictReport: the explanation text, then one button
        per resolution option - removing an existing fact or rule, or
        abandoning the fact that was just proposed. Removing a fact/rule
        then retries adding the proposed fact (see `resolve_conflict`),
        since clearing the obstacle is the whole point of that button."""
        layout = self._new_frame()
        layout.label(report.message)
        layout.label("Click one to remove it and resolve the conflict:")
        proposed = next(o for o in report.options if isinstance(o, ProposedFact))
        for option in report.options:
            layout.button(
                self._conflict_option_label(option),
                command=lambda option=option: self.resolve_conflict(option, proposed),
            )

    @staticmethod
    def _conflict_option_label(option: ConflictOption) -> str:
        if isinstance(option, ProposedFact):
            return f"Don't add: {option.fact}"
        if isinstance(option, RemovableFact):
            return f"Remove fact: {option.fact}"
        if isinstance(option, RemovableRule):
            head, body = option.rule
            return f"Remove rule: {head} :- {body}"
        raise TypeError(f"unknown conflict option: {option!r}")

    def resolve_conflict(self, option: ConflictOption, proposed: ProposedFact) -> None:
        if isinstance(option, ProposedFact):
            # The user chose not to add it after all - nothing to remove.
            self._show(self.show_updated_recommendation)
            return

        if isinstance(option, RemovableFact):
            self.engine.remove_fact(option.category, option.fact)
        elif isinstance(option, RemovableRule):
            self.engine.remove_rule(option.rule)
        else:
            raise TypeError(f"unknown conflict option: {option!r}")

        # Removing the obstacle is the whole point of these buttons - retry
        # the addition rather than silently dropping it. If a different
        # conflict remains (e.g. more than one culprit existed), show that
        # new report instead of pretending it's resolved.
        try:
            self.engine.add_fact(proposed.category, proposed.fact)
        except Inconsistent as error:
            if error.report is not None:
                # Capture into a local: `error` is cleared once this except
                # block exits, but the lambda may run later (e.g. via Back).
                report = error.report
                self._show(lambda: self.show_conflict_report(report))
            else:
                self.layout.label(str(error))
            return
        self._show(self.show_updated_recommendation)

    def show_updated_recommendation(self) -> None:
        try:
            recommendations = self.engine.recommend()
        except Inconsistent as error:
            layout = self._new_frame()
            layout.label(str(error))
            return
        self.show_recommendations(recommendations)


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
