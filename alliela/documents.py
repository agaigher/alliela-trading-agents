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


def _e(s):
    return _html.escape(str(s))


def _doc(inner):
    return ('<div class="doc__brand"><span>Alliela Research</span>'
            '<span>Engine output · real run</span></div>' + inner)
