"""Typed documents — the pipeline's interface. Models mirror the
sample outputs in web/pages/sample_outputs.py, which are the binding
output-format reference. Tier 01 documents for now; each tier adds its
own as it lands. Every document renders to the site's .doc HTML style
via to_html()."""
import html as _html
from typing import Literal

from pydantic import BaseModel, Field


class IdeaCandidate(BaseModel):
    ticker: str = Field(description="Exchange ticker, e.g. '6501.T'")
    name: str
    direction: str = Field(description="'long' or 'short'")
    one_liner: str = Field(description="The idea in one sentence")
    catalyst: str = Field(description="Dated or expected catalyst")
    edge_claim: str = Field(description="Why the market is wrong")
    evidence: list[str] = Field(description="2-4 evidence bullets, "
                                            "each citing its source")
    liquidity_note: str = Field(description="Rough tradability note")


class IdeaBook(BaseModel):
    """One desk's book — Macro, Thematic, or Catalyst."""
    desk: str
    lens: str = Field(description="The desk's angle on the mandate tip")
    candidates: list[IdeaCandidate]

    def to_html(self, title):
        parts = [f"<h3>{_e(title)}</h3>",
                 f"<p><em>{_e(self.lens)}</em></p>"]
        for c in self.candidates:
            parts.append(
                f"<h4>{_e(c.ticker)} · {_e(c.name)} — "
                f"{_e(c.direction.upper())}</h4>"
                f"<p>{_e(c.one_liner)}</p>"
                f"<p><strong>Catalyst:</strong> {_e(c.catalyst)}<br>"
                f"<strong>Edge:</strong> {_e(c.edge_claim)}<br>"
                f"<strong>Liquidity:</strong> {_e(c.liquidity_note)}</p>"
                "<ul>" + "".join(f"<li>{_e(e)}</li>" for e in c.evidence)
                + "</ul>")
        return _doc("".join(parts))


class RevisionNote(BaseModel):
    """Head of Idea Generation's feedback on one desk's book."""
    desk: str
    verdict: str = Field(description="One-line overall read")
    notes: list[str] = Field(description="Specific revision requests")


class CombinedIdeasBook(BaseModel):
    """The Head's compilation — revised books merged, deduplicated,
    coverage-noted. Unranked by design: ranking is the Selection
    Committee's job."""
    coverage_note: str = Field(description="What the scan covered and "
                                           "what it deliberately did not")
    overlap_note: str = Field(description="Duplicates/overlaps merged "
                                          "and how")
    candidates: list[IdeaCandidate]

    def to_html(self, title):
        parts = [f"<h3>{_e(title)}</h3>",
                 f"<p><strong>Coverage:</strong> "
                 f"{_e(self.coverage_note)}</p>",
                 f"<p><strong>Overlaps:</strong> "
                 f"{_e(self.overlap_note)}</p>"]
        for c in self.candidates:
            parts.append(
                f"<h4>{_e(c.ticker)} · {_e(c.name)} — "
                f"{_e(c.direction.upper())}</h4>"
                f"<p>{_e(c.one_liner)}</p>"
                f"<p><strong>Catalyst:</strong> {_e(c.catalyst)}<br>"
                f"<strong>Edge:</strong> {_e(c.edge_claim)}</p>")
        return _doc("".join(parts))


class LensScore(BaseModel):
    ticker: str
    score: int = Field(ge=1, le=5, description="1 (worst) to 5 (best) "
                                               "through this lens only")
    fatal: bool = Field(description="True kills the candidate outright "
                                    "regardless of other lenses")
    rationale: str = Field(description="Two sentences max, this lens "
                                       "only")


class Scorecard(BaseModel):
    """One scorer's read of every candidate through a single lens."""
    lens: str
    method_note: str = Field(description="How this lens judged, in one "
                                         "or two sentences")
    scores: list[LensScore]

    def to_html(self, title):
        rows = "".join(
            f"<tr><td>{_e(s.ticker)}</td><td>{s.score}/5</td>"
            f"<td>{'FATAL' if s.fatal else '—'}</td>"
            f"<td>{_e(s.rationale)}</td></tr>" for s in self.scores)
        note = ""
        if self.lens == "edge":
            note = ("<p><em>Triage signal only — edge scores expire "
                    "when the Analyst Reports land and may never be "
                    "cited downstream as evidence.</em></p>")
        return _doc(
            f"<h3>{_e(title)}</h3>"
            f"<p>{_e(self.method_note)}</p>{note}"
            "<table><thead><tr><th>Ticker</th><th>Score</th>"
            "<th>Fatal</th><th>Rationale</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>")


class RankedReject(BaseModel):
    ticker: str
    rank: int
    reason: str = Field(description="Why it lost — name the lens")


class IdeaBrief(BaseModel):
    """The Chair's handoff to the Analyst team. Aggregated by judgment,
    not by summing scores; a fatal in any lens eliminates."""
    viable: bool = Field(description="False if no candidate survived")
    ticker: str = Field(description="Selected ticker; '—' if not "
                                    "viable")
    name: str
    direction: str
    catalyst: str
    rationale: str = Field(description="Why this one won, across "
                                       "lenses, by judgment")
    coverage_notes: str = Field(description="What the analysts should "
                                            "verify first; known gaps")
    ranked_rejects: list[RankedReject]

    def to_html(self, title):
        head = (f"<h3>{_e(title)}</h3>"
                f"<h4>{_e(self.ticker)} · {_e(self.name)} — "
                f"{_e(self.direction.upper())}</h4>"
                if self.viable else
                f"<h3>{_e(title)}</h3><h4>No viable candidate — "
                f"run ends at Selection</h4>")
        rejects = "".join(
            f"<li><strong>{_e(r.ticker)}</strong> (#{r.rank}) — "
            f"{_e(r.reason)}</li>" for r in self.ranked_rejects)
        return _doc(
            head
            + f"<p><strong>Catalyst:</strong> {_e(self.catalyst)}</p>"
            + f"<p>{_e(self.rationale)}</p>"
            + f"<p><strong>Coverage notes:</strong> "
              f"{_e(self.coverage_notes)}</p>"
            + f"<h4>Ranked rejects</h4><ul>{rejects}</ul>")


class ReportSection(BaseModel):
    heading: str
    body: str = Field(description="Prose paragraphs; cite specific "
                                  "numbers, dates, sources")


class AnalystReport(BaseModel):
    """One specialist's report — long-form evidence, not bullet spam.
    The format the sample outputs bind: sections of sourced prose, a
    summary table, and honest coverage gaps."""
    report_type: str
    headline: str = Field(description="The one-line takeaway")
    sections: list[ReportSection]
    summary_table: list[list[str]] = Field(
        description="First row is the header row")
    coverage_gaps: list[str] = Field(
        description="What the data did not cover — stated, not hidden")

    def to_html(self, title):
        secs = "".join(f"<h4>{_e(s.heading)}</h4><p>{_e(s.body)}</p>"
                       for s in self.sections)
        table = ""
        if self.summary_table:
            head = "".join(f"<th>{_e(c)}</th>"
                           for c in self.summary_table[0])
            rows = "".join(
                "<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row)
                + "</tr>" for row in self.summary_table[1:])
            table = (f"<table><thead><tr>{head}</tr></thead>"
                     f"<tbody>{rows}</tbody></table>")
        gaps = ""
        if self.coverage_gaps:
            gaps = ("<h4>Coverage gaps</h4><ul>"
                    + "".join(f"<li>{_e(g)}</li>"
                              for g in self.coverage_gaps) + "</ul>")
        return _doc(f"<h3>{_e(title)}</h3>"
                    f"<p><strong>{_e(self.headline)}</strong></p>"
                    f"{secs}{table}{gaps}")


class ReportAudit(BaseModel):
    report_type: str
    score: int = Field(ge=1, le=10)
    verdict: str = Field(description="One line: does it answer the "
                                     "brief?")
    revisions: list[str] = Field(description="Actionable revision "
                                             "requests")


class AnalystRevisionNotes(BaseModel):
    """The Analyst Lead's audit of all four reports — one revision
    pass each, then the reports freeze."""
    audits: list[ReportAudit]

    def to_html(self, title):
        parts = [f"<h3>{_e(title)}</h3>"]
        for a in self.audits:
            revs = "".join(f"<li>{_e(r)}</li>" for r in a.revisions)
            parts.append(
                f"<h4>{_e(a.report_type.title())} Report — "
                f"{a.score}/10</h4><p>{_e(a.verdict)}</p>"
                f"<ul>{revs}</ul>")
        return _doc("".join(parts))


class KillCriterion(BaseModel):
    """Dated and decidable — the v4 kill-criteria discipline: when the
    date arrives, named data answers fired / not fired. Never vibes."""
    date: str = Field(description="YYYY-MM-DD or a named dated event")
    criterion: str = Field(description="The falsifiable statement")
    data_source: str = Field(description="What data decides it")


class Thesis(BaseModel):
    """The Research Manager's judgment of the debate — decisive, not a
    summary. The document the fund is named for."""
    ticker: str
    name: str
    direction: Literal["long", "short", "pass"] = Field(
        description="Exactly one of: 'long', 'short', 'pass'. Nuance "
                    "belongs in stance, never here.")
    stance: str = Field(description="One sentence of stance nuance — "
                                    "e.g. conditions for entry on a "
                                    "pass, conviction level on a "
                                    "position")
    verdict: str = Field(description="Which side won and why, one "
                                     "paragraph, citing the decisive "
                                     "evidence")
    thesis: str = Field(description="The core argument, in prose")
    path: str = Field(description="Expected path: target, timeframe, "
                                  "what has to happen")
    kill_criteria: list[KillCriterion]
    strategic_actions: list[str] = Field(
        description="Concrete next steps for Pre-Trade Structuring")
    key_risks: list[str]

    def to_html(self, title):
        kc = "".join(
            f"<tr><td>{_e(k.date)}</td><td>{_e(k.criterion)}</td>"
            f"<td>{_e(k.data_source)}</td></tr>"
            for k in self.kill_criteria)
        return _doc(
            f"<h3>{_e(title)}</h3>"
            f"<h4>{_e(self.ticker)} · {_e(self.name)} — "
            f"{_e(self.direction.upper())}</h4>"
            f"<p><em>{_e(self.stance)}</em></p>"
            f"<p><strong>Verdict.</strong> {_e(self.verdict)}</p>"
            f"<p>{_e(self.thesis)}</p>"
            f"<p><strong>Path.</strong> {_e(self.path)}</p>"
            "<h4>Kill criteria — dated, decidable</h4>"
            "<table><thead><tr><th>Date</th><th>Criterion</th>"
            "<th>Decided by</th></tr></thead>"
            f"<tbody>{kc}</tbody></table>"
            "<h4>Strategic actions</h4><ul>"
            + "".join(f"<li>{_e(a)}</li>"
                      for a in self.strategic_actions)
            + "</ul><h4>Key risks</h4><ul>"
            + "".join(f"<li>{_e(r)}</li>" for r in self.key_risks)
            + "</ul>")


class FailureMode(BaseModel):
    mode: str = Field(description="How the position failed, told as "
                                  "retrospective fact")
    early_signal: str = Field(description="What would have shown it "
                                          "first")
    likelihood_note: str


class PreMortemReview(BaseModel):
    """Prospective hindsight: it is twelve months later and the
    position failed — explain why. Speculative by design."""
    premise: str
    failure_modes: list[FailureMode]
    most_likely: str = Field(description="The single most probable "
                                         "failure path")
    monitoring_additions: list[str] = Field(
        description="What to watch that the thesis does not already "
                    "watch")

    def to_html(self, title):
        modes = "".join(
            f"<h4>{_e(m.mode)}</h4>"
            f"<p><strong>Early signal:</strong> {_e(m.early_signal)}"
            f"<br><strong>Likelihood:</strong> "
            f"{_e(m.likelihood_note)}</p>"
            for m in self.failure_modes)
        return _doc(
            f"<h3>{_e(title)}</h3><p><em>{_e(self.premise)}</em></p>"
            + modes
            + f"<p><strong>Most likely path:</strong> "
              f"{_e(self.most_likely)}</p>"
            + "<h4>Monitoring additions</h4><ul>"
            + "".join(f"<li>{_e(m)}</li>"
                      for m in self.monitoring_additions)
            + "</ul>")


class Tranche(BaseModel):
    portion: str = Field(description="Share of the position, e.g. "
                                     "'50% (2.0% NAV)'")
    trigger: str = Field(description="What initiates this tranche")
    limit: str = Field(description="Limit price / discipline")


class TransactionProposal(BaseModel):
    """Pre-Trade Structuring's handoff — forks to the Risk panel AND
    directly to the PM (who reads the original, not risk's
    paraphrase)."""
    ticker: str
    name: str
    direction: Literal["long", "short"]
    size_pct_nav: float = Field(description="Proposed total position, "
                                            "% of NAV")
    entry_plan: list[Tranche]
    participation_note: str = Field(
        description="Order size vs average daily value traded — cite "
                    "the verified ADV number")
    stop: str = Field(description="Hard stop level + its basis")
    standing_orders: list[str]
    short_borrow: str = Field(
        description="Borrow-realism check. For shorts: borrowable at "
                    "size per the Positioning report's data, borrow "
                    "cost charged against expected P&L. For longs: "
                    "'n/a — long' plus a one-line for-the-record note.")
    expected_costs: str = Field(description="Slippage / borrow / "
                                            "hedging cost estimate")
    timeline: str = Field(description="Execution window and pacing")
    open_questions_for_risk: list[str] = Field(
        description="What the Risk panel should stress first")

    def to_html(self, title):
        tranches = "".join(
            f"<tr><td>{_e(t.portion)}</td><td>{_e(t.trigger)}</td>"
            f"<td>{_e(t.limit)}</td></tr>" for t in self.entry_plan)
        return _doc(
            f"<h3>{_e(title)}</h3>"
            f"<h4>{_e(self.ticker)} · {_e(self.name)} — "
            f"{_e(self.direction.upper())} · "
            f"{self.size_pct_nav:g}% NAV</h4>"
            "<h4>Entry plan</h4>"
            "<table><thead><tr><th>Tranche</th><th>Trigger</th>"
            "<th>Limit</th></tr></thead>"
            f"<tbody>{tranches}</tbody></table>"
            f"<p><strong>Participation:</strong> "
            f"{_e(self.participation_note)}</p>"
            f"<p><strong>Stop:</strong> {_e(self.stop)}</p>"
            "<h4>Standing orders</h4><ul>"
            + "".join(f"<li>{_e(s)}</li>"
                      for s in self.standing_orders)
            + "</ul>"
            + f"<p><strong>Borrow check:</strong> "
              f"{_e(self.short_borrow)}</p>"
            + f"<p><strong>Expected costs:</strong> "
              f"{_e(self.expected_costs)}</p>"
            + f"<p><strong>Timeline:</strong> {_e(self.timeline)}</p>"
            + "<h4>Open questions for Risk</h4><ul>"
            + "".join(f"<li>{_e(q)}</li>"
                      for q in self.open_questions_for_risk)
            + "</ul>")


class RiskView(BaseModel):
    """One risk lens's read of the proposal against the book."""
    lens: str
    assessment: str = Field(description="The lens's read, in prose — "
                                        "respond to prior lenses where "
                                        "you disagree")
    stress: str = Field(description="This lens's stress scenario, "
                                    "quantified where the data allows")
    concerns: list[str]
    recommended_constraints: list[str] = Field(
        description="Concrete, typed constraints this lens would "
                    "impose")
    severity: int = Field(ge=1, le=5,
                          description="1 benign … 5 blocking")

    def to_html(self, title):
        return _doc(
            f"<h3>{_e(title)}</h3>"
            f"<p><strong>Severity {self.severity}/5.</strong> "
            f"{_e(self.assessment)}</p>"
            f"<p><strong>Stress:</strong> {_e(self.stress)}</p>"
            "<h4>Concerns</h4><ul>"
            + "".join(f"<li>{_e(c)}</li>" for c in self.concerns)
            + "</ul><h4>Recommended constraints</h4><ul>"
            + "".join(f"<li>{_e(c)}</li>"
                      for c in self.recommended_constraints)
            + "</ul>")


class RiskConstraints(BaseModel):
    """The Head of Risk's signed, typed constraints — binding on the
    PM. The PortfolioDecision must satisfy each or explicitly
    escalate."""
    ticker: str
    name: str
    veto: bool = Field(description="True blocks the trade outright")
    veto_reason: str = Field(description="Required when veto is true; "
                                         "'' otherwise")
    max_position_pct_nav: float = Field(
        description="Hard cap on the position, % of NAV")
    entry_conditions: list[str] = Field(
        description="Binding pacing/tranche conditions")
    mandatory_stops: list[str] = Field(
        description="Stops are mandatory, not advisory — level + basis")
    standing_orders: list[str]
    exposure_caps: list[str] = Field(
        description="Book-level caps this trade must respect, e.g. "
                    "country gross, sector stacking")
    event_budget_bp: float = Field(
        description="Loss budget through the named catalyst, basis "
                    "points of NAV; 0 if not applicable")
    monitoring: list[str] = Field(
        description="What the daily loop must watch for this position")
    rationale: str = Field(description="Why these numbers — grounded "
                                       "in the lens views and the book")

    def to_html(self, title):
        veto = (f"<p><strong>VETO.</strong> {_e(self.veto_reason)}</p>"
                if self.veto else "")
        def ul(items):
            return "<ul>" + "".join(f"<li>{_e(i)}</li>"
                                    for i in items) + "</ul>"
        return _doc(
            f"<h3>{_e(title)}</h3>"
            f"<h4>{_e(self.ticker)} · {_e(self.name)}</h4>" + veto
            + f"<p><strong>Max position:</strong> "
              f"{self.max_position_pct_nav:g}% NAV · "
              f"<strong>Event budget:</strong> "
              f"{self.event_budget_bp:g}bp</p>"
            + "<h4>Entry conditions</h4>" + ul(self.entry_conditions)
            + "<h4>Mandatory stops</h4>" + ul(self.mandatory_stops)
            + "<h4>Standing orders</h4>" + ul(self.standing_orders)
            + "<h4>Exposure caps</h4>" + ul(self.exposure_caps)
            + "<h4>Monitoring</h4>" + ul(self.monitoring)
            + f"<p><strong>Rationale.</strong> "
              f"{_e(self.rationale)}</p>")


class ComplianceItem(BaseModel):
    constraint: str = Field(description="The RiskConstraint addressed, "
                                        "quoted or tightly paraphrased")
    status: Literal["satisfied", "escalated"]
    note: str = Field(description="How it is satisfied, or why it is "
                                  "escalated to the Head of Risk")


class PortfolioDecision(BaseModel):
    """The PM's decision. Must address every RiskConstraint —
    satisfied or explicitly escalated (escalation triggers one PM ↔
    Head of Risk bounce-back round)."""
    ticker: str
    name: str
    action: Literal["buy", "sell", "decline"]
    size_pct_nav: float = Field(description="Decided size, % NAV — "
                                            "0 when declining")
    rationale: str = Field(description="The decision's reasoning "
                                       "against thesis, proposal, "
                                       "constraints, and the book")
    compliance: list[ComplianceItem] = Field(
        description="One item per RiskConstraint — none may be "
                    "silently ignored")
    conditions: list[str] = Field(
        description="Conditions the PM attaches beyond the constraints")

    def to_html(self, title):
        comp = "".join(
            f"<tr><td>{_e(c.constraint)}</td>"
            f"<td>{'✓' if c.status == 'satisfied' else 'ESCALATED'}"
            f"</td><td>{_e(c.note)}</td></tr>"
            for c in self.compliance)
        return _doc(
            f"<h3>{_e(title)}</h3>"
            f"<h4>{_e(self.ticker)} · {_e(self.name)} — "
            f"{_e(self.action.upper())}"
            + (f" · {self.size_pct_nav:g}% NAV"
               if self.action != "decline" else "") + "</h4>"
            f"<p>{_e(self.rationale)}</p>"
            "<h4>Compliance vs RiskConstraints</h4>"
            "<table><thead><tr><th>Constraint</th><th>Status</th>"
            "<th>Note</th></tr></thead>"
            f"<tbody>{comp}</tbody></table>"
            "<h4>PM conditions</h4><ul>"
            + "".join(f"<li>{_e(c)}</li>" for c in self.conditions)
            + "</ul>")


class FundingSource(BaseModel):
    source: Literal["cash", "trim"]
    ticker: str = Field(description="'' for cash")
    amount_pct_nav: float
    rationale: str = Field(description="For trims: why this holding — "
                                       "conviction rank, thesis state")


class FundingPlan(BaseModel):
    """PM duty: portfolio construction — make room. Cash first, then
    trim lowest-conviction holdings. Grounded in the real book."""
    target_pct_nav: float = Field(description="Room to make, % NAV")
    sources: list[FundingSource]
    resulting_cash_pct: float = Field(
        description="Cash after funding — must respect the 1% floor")
    notes: str

    def to_html(self, title):
        rows = "".join(
            f"<tr><td>{_e(s.source)}</td><td>{_e(s.ticker) or '—'}</td>"
            f"<td>{s.amount_pct_nav:g}%</td><td>{_e(s.rationale)}</td>"
            f"</tr>" for s in self.sources)
        return _doc(
            f"<h3>{_e(title)}</h3>"
            f"<p>Room required: <strong>{self.target_pct_nav:g}% "
            f"NAV</strong> · cash after funding: "
            f"<strong>{self.resulting_cash_pct:g}%</strong></p>"
            "<table><thead><tr><th>Source</th><th>Ticker</th>"
            "<th>% NAV</th><th>Rationale</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            f"<p>{_e(self.notes)}</p>")


class InstructionLeg(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    size_pct_nav: float
    purpose: Literal["entry", "funding_trim", "hedge"]
    pacing: str = Field(description="Limit/pacing discipline for the "
                                    "desk")


class DealingInstruction(BaseModel):
    """PM - Instruction: binds the decision + funding plan into the
    stage's handoff document. The Compliance gate checks THIS at order
    release."""
    legs: list[InstructionLeg]
    stops_to_place: list[str]
    standing_orders: list[str]
    validity: str = Field(description="Execution window")
    notes: str

    def to_html(self, title):
        rows = "".join(
            f"<tr><td>{_e(l.ticker)}</td><td>{_e(l.side.upper())}</td>"
            f"<td>{l.size_pct_nav:g}%</td><td>{_e(l.purpose)}</td>"
            f"<td>{_e(l.pacing)}</td></tr>" for l in self.legs)
        def ul(items):
            return "<ul>" + "".join(f"<li>{_e(i)}</li>"
                                    for i in items) + "</ul>"
        return _doc(
            f"<h3>{_e(title)}</h3>"
            "<table><thead><tr><th>Ticker</th><th>Side</th>"
            "<th>% NAV</th><th>Purpose</th><th>Pacing</th></tr>"
            f"</thead><tbody>{rows}</tbody></table>"
            "<h4>Stops to place</h4>" + ul(self.stops_to_place)
            + "<h4>Standing orders</h4>" + ul(self.standing_orders)
            + f"<p><strong>Validity:</strong> {_e(self.validity)} · "
              f"{_e(self.notes)}</p>")


class Fill(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    size_pct_nav: float
    purpose: Literal["entry", "funding_trim", "hedge"]
    fill_price: str = Field(description="Currency-formatted, from the "
                                        "verified snapshot")
    slippage_note: str


class ExecutionReport(BaseModel):
    """Trading Desk duty #2 — what was actually done. The fills are
    the only thing that ever writes to the PMS."""
    fills: list[Fill]
    unfilled: list[str] = Field(description="Legs resting/deferred and "
                                            "why")
    stops_placed: list[str]
    market_note: str

    def to_html(self, title):
        rows = "".join(
            f"<tr><td>{_e(f.ticker)}</td><td>{_e(f.side.upper())}</td>"
            f"<td>{f.size_pct_nav:g}%</td><td>{_e(f.purpose)}</td>"
            f"<td>{_e(f.fill_price)}</td><td>{_e(f.slippage_note)}</td>"
            f"</tr>" for f in self.fills)
        return _doc(
            f"<h3>{_e(title)}</h3>"
            "<table><thead><tr><th>Ticker</th><th>Side</th><th>% NAV"
            "</th><th>Purpose</th><th>Fill</th><th>Slippage</th></tr>"
            f"</thead><tbody>{rows}</tbody></table>"
            "<h4>Unfilled / resting</h4><ul>"
            + "".join(f"<li>{_e(u)}</li>" for u in self.unfilled)
            + "</ul><h4>Stops placed</h4><ul>"
            + "".join(f"<li>{_e(s)}</li>" for s in self.stops_placed)
            + f"</ul><p>{_e(self.market_note)}</p>")


def compliance_record_html(checks, passed):
    """The Compliance gate's record — deterministic, no LLM."""
    rows = "".join(
        f"<tr><td>{_e(c['rule'])}</td>"
        f"<td>{_e(c['observed'])}</td>"
        f"<td>{'PASS' if c['ok'] else ('N/E' if c['ok'] is None else 'FAIL')}</td></tr>"
        for c in checks)
    verdict = "RELEASED" if passed else "RETURNED TO PM - DECISION"
    return _doc(
        "<h3>Compliance Record</h3>"
        "<p><em>Deterministic rule check of the Dealing Instruction "
        "against the mandate's typed restrictions and the book at "
        "order release — no judgment, no waivers. N/E = not "
        "mechanically evaluable yet.</em></p>"
        "<table><thead><tr><th>Rule</th><th>Observed</th>"
        "<th>Result</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        f"<p><strong>Verdict: {verdict}</strong></p>")


def debate_doc_html(side, turns):
    """One debater's case — their turns in order."""
    labels = ["Opening", "Rebuttal", "Closing"]
    parts = []
    for i, t in enumerate(turns):
        label = labels[i] if i < len(labels) else f"Turn {i + 1}"
        parts.append(f"<h4>{label}</h4>"
                     + "".join(f"<p>{_e(p)}</p>"
                               for p in t.split("\n\n") if p.strip()))
    return _doc(f"<h3>{_e(side)} Case</h3>" + "".join(parts))


def transcript_html(title, interleaved):
    """Full debate transcript — (speaker, text) turns verbatim."""
    parts = [f"<h3>{_e(title)}</h3>"]
    for speaker, text in interleaved:
        parts.append(f"<h4>{_e(speaker)}</h4>"
                     + "".join(f"<p>{_e(p)}</p>"
                               for p in text.split("\n\n")
                               if p.strip()))
    return _doc("".join(parts))


def _e(s):
    return _html.escape(str(s))


def _doc(inner):
    return ('<div class="doc__brand"><span>Alliela Research</span>'
            '<span>Engine output · real run</span></div>' + inner)
