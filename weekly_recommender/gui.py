"""Tkinter front-end for the weekly recommender.

State (facts, rules, last solve results) lives in a RecommenderEngine
instance owned by this App - no module-level globals. Widget placement goes
through RowLayout so rows are always allocated dynamically: no two widgets
can ever be handed the same fixed row number and end up overlapping.

Visual language: a small ttk.Style palette (COLORS below) plus a handful of
named styles configured once in `_configure_style`. `clam` is used as the
base theme rather than the platform default because it's the only built-in
ttk theme that actually honors custom button backgrounds/foregrounds on
every platform - macOS's native "aqua" theme silently ignores them.
"""
from __future__ import annotations

from tkinter import N, S, E, W, StringVar, Tk
from tkinter import ttk
from typing import Callable

import domain
from engine import (
    ConflictOption,
    EngineState,
    Explanation,
    FACT_VALUE_OPTIONS,
    Inconsistent,
    PreferenceExplanation,
    ProposedFact,
    Recommendation,
    RecommenderEngine,
    RemovableFact,
    RemovableRule,
    replacement_fact,
)

def _format_context_fact(symbol) -> str:
    """Render a context symbol (e.g. `dailyweather(1,good)`) as the
    human-readable "label: value" shown in the GUI, e.g. "weather: good" -
    falls back to the raw predicate name if it's not a known context
    factor."""
    label = domain.CONTEXT_FACTOR_LABELS.get(symbol.name, symbol.name)
    return f"{label}: {symbol.arguments[1]}"


COLORS = {
    "background": "#f5f6fa",
    "surface": "#ffffff",
    "text": "#1f2430",
    "muted": "#6b7280",
    "border": "#dde1ea",
    "accent": "#2f6fed",
    "accent_active": "#1f4fcc",
    "success": "#1f9d55",
    "success_active": "#167a42",
    "danger": "#d9455f",
    "danger_active": "#b7334a",
}

FONT_FAMILY = "Helvetica"


def _configure_style(root: Tk) -> None:
    root.configure(background=COLORS["background"])

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("TFrame", background=COLORS["background"])
    style.configure(
        "TLabel",
        background=COLORS["background"],
        foreground=COLORS["text"],
        font=(FONT_FAMILY, 11),
    )
    style.configure(
        "Heading.TLabel",
        font=(FONT_FAMILY, 16, "bold"),
        foreground=COLORS["text"],
    )
    style.configure(
        "Section.TLabel",
        font=(FONT_FAMILY, 11, "bold"),
        foreground=COLORS["muted"],
    )
    style.configure(
        "Muted.TLabel",
        font=(FONT_FAMILY, 10),
        foreground=COLORS["muted"],
    )
    style.configure(
        "Warning.TLabel",
        font=(FONT_FAMILY, 11, "bold"),
        foreground=COLORS["danger"],
    )
    style.configure(
        "Day.TLabel",
        font=(FONT_FAMILY, 11, "bold"),
        foreground=COLORS["text"],
    )
    style.configure(
        "Success.TLabel",
        font=(FONT_FAMILY, 12, "bold"),
        foreground=COLORS["success"],
    )

    style.configure("TSeparator", background=COLORS["border"])

    style.configure(
        "TButton",
        font=(FONT_FAMILY, 11),
        padding=(10, 6),
        background=COLORS["surface"],
        foreground=COLORS["text"],
        borderwidth=1,
        relief="solid",
    )
    style.map(
        "TButton",
        background=[("active", COLORS["border"])],
    )

    style.configure(
        "Accent.TButton",
        font=(FONT_FAMILY, 11, "bold"),
        foreground="white",
        background=COLORS["accent"],
        borderwidth=0,
    )
    style.map("Accent.TButton", background=[("active", COLORS["accent_active"])])

    style.configure(
        "Success.TButton",
        font=(FONT_FAMILY, 11, "bold"),
        foreground="white",
        background=COLORS["success"],
        borderwidth=0,
    )
    style.map("Success.TButton", background=[("active", COLORS["success_active"])])

    style.configure(
        "Danger.TButton",
        font=(FONT_FAMILY, 11, "bold"),
        foreground="white",
        background=COLORS["danger"],
        borderwidth=0,
    )
    style.map("Danger.TButton", background=[("active", COLORS["danger_active"])])

    style.configure(
        "Back.TButton",
        font=(FONT_FAMILY, 10),
        foreground=COLORS["muted"],
        background=COLORS["background"],
        padding=(4, 2),
        borderwidth=0,
    )
    style.map("Back.TButton", foreground=[("active", COLORS["text"])])

    style.configure(
        "TEntry",
        padding=(6, 4),
        fieldbackground=COLORS["surface"],
    )

    style.configure(
        "TCombobox",
        padding=(6, 4),
        fieldbackground=COLORS["surface"],
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", COLORS["surface"])],
        foreground=[("readonly", COLORS["text"])],
    )


class RowLayout:
    """Places widgets in a frame's grid, one row at a time, tracking the
    next free row itself so callers never juggle row numbers by hand."""

    def __init__(self, frame: ttk.Frame) -> None:
        self.frame = frame
        self.row = 0

    def heading(self, text: str) -> ttk.Label:
        widget = self.label(text, style="Heading.TLabel", pady=(0, 10))
        self.separator()
        return widget

    def section(self, text: str) -> ttk.Label:
        return self.label(text, style="Section.TLabel", pady=(10, 2))

    def muted(self, text: str) -> ttk.Label:
        return self.label(text, style="Muted.TLabel")

    def warning(self, text: str) -> ttk.Label:
        return self.label(text, style="Warning.TLabel", pady=(0, 6))

    def separator(self) -> ttk.Separator:
        widget = ttk.Separator(self.frame, orient="horizontal")
        widget.grid(column=1, row=self.row, columnspan=2, sticky=(W, E), pady=(0, 10))
        self.row += 1
        return widget

    def label(
        self,
        text: str,
        wraplength: int = 460,
        style: str = "TLabel",
        pady: tuple[int, int] = (0, 4),
    ) -> ttk.Label:
        widget = ttk.Label(self.frame, text=text, wraplength=wraplength, justify="left", style=style)
        widget.grid(column=1, row=self.row, sticky=(W, E), pady=pady)
        self.row += 1
        return widget

    def day_row(self, day_text: str, rest_text: str) -> ttk.Frame:
        """A recommendation line with the day name in bold and the rest in
        the regular body style, side by side."""
        row_frame = ttk.Frame(self.frame)
        row_frame.grid(column=1, row=self.row, sticky=(W, E), pady=(0, 4))
        ttk.Label(row_frame, text=day_text, style="Day.TLabel").pack(side="left")
        ttk.Label(row_frame, text=f" {rest_text}", style="TLabel").pack(side="left")
        self.row += 1
        return row_frame

    def button(
        self, text: str, command: Callable[[], None] | None = None, style: str = "TButton"
    ) -> ttk.Button:
        widget = ttk.Button(self.frame, text=text, command=command, style=style)
        widget.grid(column=1, row=self.row, sticky=W, pady=(0, 4))
        self.row += 1
        return widget

    def button_pair(
        self,
        left: tuple[str, Callable[[], None] | None],
        right: tuple[str, Callable[[], None] | None],
        left_style: str = "TButton",
        right_style: str = "TButton",
        fill: bool = False,
    ) -> tuple[ttk.Button, ttk.Button]:
        """Two buttons side by side on the same row. With `fill`, the right
        button is pinned to column 2's right edge instead of left-aligned
        right after column 1 - used to line the pair up with a `fill`
        entry above it, whose columnspan=2 sets column 2's width to
        whatever's needed to reach the entry's right edge."""
        if fill:
            self.frame.columnconfigure(2, weight=1)
        left_widget = ttk.Button(self.frame, text=left[0], command=left[1], style=left_style)
        left_widget.grid(column=1, row=self.row, sticky=W, pady=(0, 4))
        right_widget = ttk.Button(self.frame, text=right[0], command=right[1], style=right_style)
        right_widget.grid(column=2, row=self.row, sticky=(E if fill else W), pady=(0, 4))
        self.row += 1
        return left_widget, right_widget

    def label_var(self, textvariable: StringVar, style: str = "Success.TLabel") -> ttk.Label:
        widget = ttk.Label(self.frame, textvariable=textvariable, style=style)
        widget.grid(column=1, row=self.row, sticky=(W, E), pady=(6, 0))
        self.row += 1
        return widget

    def entry(self, textvariable: StringVar, width: int = 81, fill: bool = False) -> ttk.Entry:
        widget = ttk.Entry(self.frame, width=width, textvariable=textvariable)
        if fill:
            widget.grid(column=1, row=self.row, columnspan=2, sticky=(W, E), pady=(0, 4))
        else:
            widget.grid(column=1, row=self.row, sticky=W, pady=(0, 4))
        self.row += 1
        return widget

    def combobox(
        self, textvariable: StringVar, values: list[str], width: int = 81, fill: bool = False
    ) -> ttk.Combobox:
        widget = ttk.Combobox(
            self.frame, width=width, textvariable=textvariable, values=values, state="readonly"
        )
        if fill:
            widget.grid(column=1, row=self.row, columnspan=2, sticky=(W, E), pady=(0, 4))
        else:
            widget.grid(column=1, row=self.row, sticky=W, pady=(0, 4))
        self.row += 1
        return widget


class App:
    def __init__(self) -> None:
        self.engine = RecommenderEngine()
        self.root = Tk()
        self.root.title("Weekly Recommendations")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.root.minsize(560, 420)
        _configure_style(self.root)

        self.current_frame: ttk.Frame | None = None
        self.layout: RowLayout | None = None
        self._history: list[tuple[Callable[[], None], EngineState]] = []
        self._current_render: Callable[[], None] | None = None
        self._current_snapshot: EngineState | None = None
        self._show(lambda: self.show_recommendations(self.engine.recommend()))

    def run(self) -> None:
        self.root.mainloop()

    # -- Navigation -----------------------------------------------------
    #
    # Every screen transition goes through `_show`, which always builds a
    # fresh frame (via `_new_frame`), so a screen's widgets never linger
    # once you've moved past it. `_show` pushes the render function that
    # built the *previous* screen, together with the engine state as it was
    # when that screen was shown, onto a history stack. `_go_back` restores
    # that engine state before re-running the render - so any fact/rule
    # mutations made while on the screen being left (e.g. removing a fact,
    # then backing out of the follow-up screen) are undone, not just the
    # navigation itself.

    def _show(self, render: Callable[[], None]) -> None:
        if self._current_render is not None:
            self._history.append((self._current_render, self._current_snapshot))
        self._current_snapshot = self.engine.snapshot()
        self._current_render = render
        render()

    def _go_back(self) -> None:
        if not self._history:
            return
        render, snapshot = self._history.pop()
        self.engine.restore(snapshot)
        self._current_render = render
        self._current_snapshot = snapshot
        render()

    # -- Frame management --------------------------------------------------

    def _new_frame(self) -> RowLayout:
        if self.current_frame is not None:
            self.current_frame.destroy()
        frame = ttk.Frame(self.root, padding="24 20 24 24")
        frame.grid(column=0, row=0, sticky=(N, W, E, S))
        self.current_frame = frame
        self.layout = RowLayout(frame)
        if self._history:
            self.layout.button("← Back", command=self._go_back, style="Back.TButton")
        return self.layout

    # -- Screen 1: the weekly recommendation --------------------------------

    def show_recommendations(self, recommendations: list[Recommendation]) -> None:
        layout = self._new_frame()
        layout.heading("Recommendation for this week")

        for rec in recommendations:
            layout.day_row(f"{rec.day.capitalize()}:", f"{rec.action} for {rec.goal}")

        feedback = StringVar()

        def accept() -> None:
            accept_button.grid_forget()
            reject_button.grid_forget()
            feedback.set("Have a great week!")

        accept_button, reject_button = layout.button_pair(
            ("Accept", accept),
            ("Do Not Accept", lambda: self._show(self.show_rejection_picker)),
            left_style="Success.TButton",
        )
        layout.label_var(feedback)

    # -- Screen 2: pick which day's recommendation is wrong -----------------

    def show_rejection_picker(self) -> None:
        layout = self._new_frame()
        layout.heading("Which recommendation do you disagree with?")

        for rec in self.engine.recommend():
            layout.button(
                f"{rec.day}: {rec.action} for {rec.goal}",
                command=lambda rec=rec: self._show(lambda: self.show_explanation(rec)),
            )

    # -- Screen 3: break a recommendation down into context/goal/action -----

    def show_explanation(self, recommendation: Recommendation) -> None:
        layout = self._new_frame()
        day_number = domain.DAY_NUMBERS[recommendation.day]

        layout.heading("What exactly is the problem?")
        layout.section("Relevant context")

        for symbol in self.engine.relevant_context(day_number):
            layout.button(
                _format_context_fact(symbol),
                command=lambda symbol=symbol, day_number=day_number: self._show(
                    lambda: self.show_context_problem(symbol, day_number)
                ),
            )

        layout.section("Selected goal")
        layout.button(
            recommendation.goal,
            command=lambda: self._show(
                lambda: self.show_goal_problem(recommendation.goal, day_number)
            ),
        )

        layout.section("Selected action")
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
        layout.heading(
            f"You disagree with the identified context: {_format_context_fact(symbol)} "
            f"on {day_name}"
        )

        fact = str(symbol)
        matching_fact = next((f for f in self.engine.context_facts if f == fact), None)
        if matching_fact is not None:
            self._offer_fact_removal(layout, "context", matching_fact)
        else:
            self._offer_new_fact(layout, "context", fact)

    def show_goal_problem(self, goal: str, day_number: int) -> None:
        layout = self._new_frame()
        day_name = domain.DAY_NAMES[day_number].capitalize()
        layout.heading(f"You disagree with the selected goal: {goal} on {day_name}")

        fact = f"dailygoal({day_number},{goal})"
        if fact in self.engine.goal_facts:
            self._offer_fact_removal(layout, "goal", fact)
            return

        explanation = self.engine.explain_goal(day_number, goal)
        if explanation is None:
            self._offer_new_fact(layout, "goal", fact)
            return

        layout.muted("This is a direct result of the knowledge base:")
        layout.muted("Click on one of the options to remove it from the knowledge base.")
        self._show_rule_explanation(layout, explanation)

    def show_action_problem(self, action: str, day_number: int) -> None:
        layout = self._new_frame()
        day_name = domain.DAY_NAMES[day_number].capitalize()
        layout.heading(f"You disagree with the selected action: {action} on {day_name}")

        fact = f"dailyaction({day_number},{action})"
        matching_fact = next((f for f in self.engine.action_facts if f == fact), None)
        if matching_fact is not None:
            self._offer_fact_removal(layout, "action", matching_fact)
        else:
            self._offer_new_fact(layout, "action", fact)

    def _show_rule_explanation(self, layout: RowLayout, explanation: Explanation) -> None:
        head, body = explanation.rule
        layout.section(f"{explanation.fact} comes from the following rule")
        layout.button(
            f"{body} implies {head}",
            command=lambda: self.remove_rule(explanation.rule),
            style="Danger.TButton",
        )
        legend = self.engine.describe_rule_variables(explanation.rule, explanation.fact)
        if legend:
            layout.muted(legend)

        layout.section("and the following prerequisites")
        for prerequisite in explanation.prerequisites:
            layout.button(
                str(prerequisite),
                command=lambda prerequisite=prerequisite: self._show(
                    lambda: self.show_prerequisite_problem(prerequisite)
                ),
            )

    def show_prerequisite_problem(self, symbol) -> None:
        layout = self._new_frame()
        layout.heading(f"You disagree with the prerequisite: {symbol}")

        fact = str(symbol)
        for category in ("context", "goal", "action"):
            facts = getattr(self.engine, f"{category}_facts")
            if fact in facts:
                self._offer_fact_removal(layout, category, fact)
                return
        if symbol.name == "dailyaction":
            self._offer_new_fact(layout, "action", fact)
        else:
            layout.muted("This is a direct result of the knowledge base.")

    def _offer_new_fact(self, layout: RowLayout, category: str, old_fact: str) -> None:
        """This wasn't entered as a fact and isn't a direct consequence of a
        hard rule either - it was filled in by a default rule, so there's
        nothing to remove. Offer to add a fact instead, the same way
        `show_add_replacement_fact` does after a removal. The user only
        needs to type the new value, not the whole fact - `replacement_fact`
        rebuilds it around `old_fact`'s predicate and day."""
        layout.label("This value was filled in by default and can be changed.")
        layout.muted(f"Currently: {old_fact}")
        layout.muted("What would you prefer instead?")
        new_value = StringVar()
        predicate = old_fact.split("(")[0]
        layout.combobox(new_value, FACT_VALUE_OPTIONS[predicate], fill=True)
        layout.button(
            "Enter",
            command=lambda: self.propose_replacement(
                category, replacement_fact(old_fact, new_value.get())
            ),
            style="Accent.TButton",
        )

    def _offer_fact_removal(self, layout: RowLayout, category: str, fact: str) -> None:
        layout.label("This information was entered as a fact. Would you like to remove it?")
        layout.button_pair(
            ("Yes", lambda: self.remove_fact(category, fact)),
            ("No", self._go_back),
            left_style="Success.TButton",
        )

    # -- Actions that mutate the engine and re-solve -------------------------

    def remove_rule(self, rule) -> None:
        self.engine.remove_rule(rule)
        self._show(self.show_updated_recommendation)

    def remove_fact(self, category: str, fact: str) -> None:
        self.engine.remove_fact(category, fact)
        self._show(lambda: self.show_add_replacement_fact(category, fact))

    def show_add_replacement_fact(self, category: str, old_fact: str) -> None:
        layout = self._new_frame()
        layout.heading("Would you like to add a different fact instead?")
        layout.muted(f"Replacing: {old_fact}")

        new_value = StringVar()
        predicate = old_fact.split("(")[0]
        layout.combobox(new_value, FACT_VALUE_OPTIONS[predicate], fill=True)
        layout.button_pair(
            ("Enter", lambda: self.add_fact(category, replacement_fact(old_fact, new_value.get()))),
            ("Skip", lambda: self._show(self.show_updated_recommendation)),
            left_style="Accent.TButton",
            fill=True,
        )

    def propose_replacement(self, category: str, fact: str) -> None:
        """Entry point for replacing a default-filled value (`_offer_new_fact`).
        If `fact` is already achievable at this stage, explain why it wasn't
        chosen instead of adding it outright - see `show_preference_explanation`."""
        explanation = self.engine.explain_preference(category, fact)
        if explanation is not None:
            self._show(lambda: self.show_preference_explanation(explanation))
            return
        self.add_fact(category, fact)

    def show_preference_explanation(self, explanation: PreferenceExplanation) -> None:
        layout = self._new_frame()
        layout.heading(f"{explanation.fact} is possible, but wasn't chosen")
        if explanation.tie:
            layout.label(
                "Nothing currently prefers one over the other - the current "
                "pick was chosen arbitrarily."
            )
        else:
            layout.label(
                f"The current pick matches the preference "
                f"`{explanation.current_preference}`, which outranks "
                + (
                    f"`{explanation.desired_preference}`."
                    if explanation.desired_preference
                    else "this value, which currently matches no preference at all."
                )
            )
        layout.button(
            "Prefer this instead",
            command=lambda: self.prefer_and_update(explanation.category, explanation.fact),
            style="Accent.TButton",
        )
        layout.button(
            "Leave preferences unchanged, add it to the knowledge base instead",
            command=lambda: self.add_fact(explanation.category, explanation.fact),
        )
        layout.button("Back", command=self._go_back)

    def prefer_and_update(self, category: str, fact: str) -> None:
        self.engine.prefer(category, fact)
        self._show(self.show_updated_recommendation)

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
        self._show_conflict_message(layout, report.message)
        layout.label("")
        layout.muted("Click one to remove it and resolve the conflict:")
        proposed = next(o for o in report.options if isinstance(o, ProposedFact))
        for option in report.options:
            layout.button(
                self._conflict_option_label(option),
                command=lambda option=option: self.resolve_conflict(option, proposed),
                style=self._conflict_option_style(option),
            )

    @staticmethod
    def _show_conflict_message(layout: RowLayout, message: str) -> None:
        """Render a `ConflictReport.message`, one line at a time, so a
        `describe_rule_variables` legend line (indented 8 spaces - see
        `ConflictReport`) can be shown smaller and in the muted grey used
        elsewhere, instead of blending into the surrounding explanation."""
        for line in message.split("\n"):
            if line.startswith("        "):
                layout.muted(line.strip())
            else:
                layout.label(line, pady=(0, 2))

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

    @staticmethod
    def _conflict_option_style(option: ConflictOption) -> str:
        return "TButton" if isinstance(option, ProposedFact) else "Danger.TButton"

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
            layout.warning(str(error))
            return
        self.show_recommendations(recommendations)


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
