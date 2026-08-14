"""Typed documents — the pipeline's interface. Models mirror the
sample outputs in web/pages/sample_outputs.py, which are the binding
output-format reference. Tier 01 documents for now; each tier adds its
own as it lands. Every document renders to the site's .doc HTML style
via to_html()."""
import html as _html

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


def _e(s):
    return _html.escape(str(s))


def _doc(inner):
    return ('<div class="doc__brand"><span>Alliela Research</span>'
            '<span>Engine output · real run</span></div>' + inner)
