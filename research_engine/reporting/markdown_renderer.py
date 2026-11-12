"""Markdown Report Renderer.

Converts structured, verified report payloads into a comprehensive,
publication-grade Markdown report with inline clickable citations,
publication dates, and an exhaustive Sources & Evidence Directory.
"""

from datetime import datetime
from typing import Dict, List, Set
from research_engine.database.models import EvidenceRecord, ResearchPlan, SourceRecord
from research_engine.database.repository import ResearchRepository
from research_engine.reporting.validator import CitationValidationResult
from research_engine.synthesis.report_synthesizer import StructuredReportPayload, SynthesizedStatement


class MarkdownReportRenderer:
    """Renders structured reports into formatted Markdown documents."""

    def __init__(self, repository: ResearchRepository):
        self.repo = repository

    def render(
        self,
        run_id: str,
        payload: StructuredReportPayload,
        validation_result: CitationValidationResult,
        plan: ResearchPlan
    ) -> str:
        """Render complete markdown document with traceable citations."""
        sources = self.repo.get_sources_for_run(run_id)
        sources_map: Dict[int, SourceRecord] = {s.id: s for s in sources if s.id is not None}
        evidence_list = self.repo.get_all_evidence_for_run(run_id)
        evidence_map: Dict[str, EvidenceRecord] = {e.id: e for e in evidence_list}

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines: List[str] = []

        # 1. Header
        lines.append(f"# {payload.title}\n")
        lines.append(f"**Research Date:** {now_str} | **Run ID:** `{run_id}`")
        lines.append(f"**Research Scope:** {plan.scope or 'Comprehensive investigation'}\n")

        # 2. Executive Summary
        lines.append("## Executive Summary\n")
        if payload.executive_summary:
            for stmt in payload.executive_summary:
                cite_str = self._format_inline_citations(stmt.cited_evidence_ids, evidence_map, sources_map)
                lines.append(f"- {stmt.statement} {cite_str}".strip())
        else:
            lines.append("No executive summary generated.")
        lines.append("")

        # 3. Key Verified Findings
        lines.append("## Key Verified Findings\n")
        lines.append("> [!IMPORTANT]\n> Every finding below is substantiated by traceable source quotations verified in original webpage text.\n")
        if payload.key_findings:
            for stmt in payload.key_findings:
                cite_str = self._format_inline_citations(stmt.cited_evidence_ids, evidence_map, sources_map)
                lines.append(f"1. **{stmt.statement}** {cite_str}".strip())
        else:
            lines.append("No verified findings met the strict evidence threshold.")
        lines.append("")

        # 4. Detailed Research Findings
        if payload.detailed_sections:
            lines.append("## Detailed Research Findings\n")
            for section in payload.detailed_sections:
                lines.append(f"### {section.section_title}\n")
                for stmt in section.statements:
                    cite_str = self._format_inline_citations(stmt.cited_evidence_ids, evidence_map, sources_map)
                    lines.append(f"- {stmt.statement} {cite_str}".strip())
                lines.append("")

        # 5. Community & Self-Reported Experiences
        lines.append("## Community & Self-Reported Experiences\n")
        lines.append(
            "> [!NOTE]\n"
            "> The following observations reflect publicly posted, self-reported user experiences from forums and community threads. "
            "They illustrate real-world practitioner experiences, not universal statistical consensus.\n"
        )
        if payload.community_experiences:
            for stmt in payload.community_experiences:
                cite_str = self._format_inline_citations(stmt.cited_evidence_ids, evidence_map, sources_map)
                lines.append(f"- {stmt.statement} {cite_str}".strip())
        else:
            lines.append("No community user reviews met the verified evidence criteria.")
        lines.append("")

        # 6. Complaints, Known Risks & Failure Modes
        lines.append("## Complaints, Known Risks & Criticisms\n")
        if payload.complaints_and_risks:
            for stmt in payload.complaints_and_risks:
                cite_str = self._format_inline_citations(stmt.cited_evidence_ids, evidence_map, sources_map)
                lines.append(f"- {stmt.statement} {cite_str}".strip())
        else:
            lines.append("No specific failure modes or critical complaints were verified.")
        lines.append("")

        # 7. Contradictions & Disagreements
        lines.append("## Contradictions & Disagreements\n")
        contradictions = self.repo.get_contradictions_for_run(run_id)
        if contradictions:
            for c in contradictions:
                lines.append(f"- **{c.description}** (Topic: `{c.topic_facet}`)")
        elif payload.contradictions_disagreements:
            for stmt in payload.contradictions_disagreements:
                cite_str = self._format_inline_citations(stmt.cited_evidence_ids, evidence_map, sources_map)
                lines.append(f"- {stmt.statement} {cite_str}".strip())
        else:
            lines.append("No direct contradictions detected among the verified sources.")
        lines.append("")

        # 8. What Could Not Be Established (Research Gaps)
        lines.append("## What the Research Could Not Establish\n")
        if payload.what_could_not_be_established:
            for gap in payload.what_could_not_be_established:
                lines.append(f"- {gap}")
        else:
            lines.append("- Certain granular internal metrics and proprietary benchmarks remain unavailable in public sources.")
        lines.append("")

        # 9. Research Methodology & Limitations
        lines.append("## Research Methodology & Limitations\n")
        stats = self.repo.get_run_accounting_stats(run_id)
        lines.append(f"- **Sources Queued:** {stats['total_sources_queued']}")
        lines.append(f"- **Pages Successfully Fetched:** {stats['fetched_sources']}")
        lines.append(f"- **Pages Extracted:** {stats['extracted_sources']}")
        lines.append(f"- **Evidence Items Analyzed:** {stats['total_candidate_evidence']}")
        lines.append(f"- **Exact Quote Verified Items:** {stats['quote_valid_evidence']}")
        lines.append(f"- **Independently Verified Items:** {stats['verified_evidence']}")
        lines.append(f"- **Evidence-Bearing Unique Sources:** {stats['evidence_bearing_sources']}")
        lines.append("- **Verification Standard:** Fail-closed deterministic exact quote matching + second-pass claim support verification.")
        lines.append("")

        # 10. Conclusion
        lines.append("## Conclusion & Strategic Assessment\n")
        lines.append(payload.conclusion or "Research evaluation concluded based on verified evidence ledger.")
        lines.append("")

        # 11. Sources & Evidence Directory
        lines.append("---\n")
        lines.append("## Sources & Evidence Directory\n")
        lines.append("| Citation | Source Tier | Domain | Published | URL | Verbatim Supporting Quote |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

        # Display all cited evidence items
        for eid in sorted(validation_result.validated_evidence_ids):
            evid = evidence_map.get(eid)
            if not evid:
                continue
            src = sources_map.get(evid.source_id)
            if not src:
                continue

            clean_quote = " ".join(evid.exact_quote.split())
            if len(clean_quote) > 120:
                clean_quote = clean_quote[:117] + "..."

            # Escape pipes for markdown table
            safe_quote = clean_quote.replace("|", "\\|")
            pub_date = evid.published_date or src.published_date or "N/A"

            lines.append(
                f"| `[{eid}]` | `{src.source_tier}` | `{src.domain}` | {pub_date} | [{src.title[:35] or src.domain}]({src.url}) | \"{safe_quote}\" |"
            )

        return "\n".join(lines)

    def _format_inline_citations(
        self,
        evidence_ids: List[str],
        evidence_map: Dict[str, EvidenceRecord],
        sources_map: Dict[int, SourceRecord]
    ) -> str:
        """Format clickable markdown citations for a list of evidence IDs."""
        if not evidence_ids:
            return ""

        cite_tokens = []
        for eid in evidence_ids:
            evid = evidence_map.get(eid)
            if evid:
                src = sources_map.get(evid.source_id)
                if src:
                    cite_tokens.append(f"[[{eid}: {src.domain}]]({src.url})")
                else:
                    cite_tokens.append(f"`[{eid}]`")
            else:
                cite_tokens.append(f"`[{eid}]`")

        return " " + " ".join(cite_tokens)

