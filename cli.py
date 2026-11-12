"""Command-Line Interface for the Evidence-First Deep Research Engine."""

import argparse
import json
import os
import sys

from config import settings
from research_engine.database.connection import init_database
from research_engine.database.repository import ResearchRepository
from research_engine.providers.llm.groq_provider import GroqLLMProvider
from research_engine.research.orchestrator import ResearchOrchestrator


def get_orchestrator(db_path: str = settings.database_path) -> ResearchOrchestrator:
    """Initialize repository and orchestrator with configured provider."""
    init_database(db_path)
    repo = ResearchRepository(db_path)

    api_key = settings.groq_api_key.strip()
    if not api_key:
        print("[!] Warning: GROQ_API_KEY is not set in environment or .env file.")
        print("    Live research with Groq will fail unless an API key is provided.")

    llm = GroqLLMProvider(
        api_key=api_key or "gsk_placeholder",
        default_model=settings.groq_model,
        max_retries=settings.groq_max_retries
    )
    verifier_llm = GroqLLMProvider(
        api_key=api_key or "gsk_placeholder",
        default_model=settings.groq_verifier_model,
        max_retries=settings.groq_max_retries
    )
    return ResearchOrchestrator(
        llm_provider=llm,
        verifier_llm_provider=verifier_llm,
        repository=repo,
        db_path=db_path
    )


def cmd_run(args: argparse.Namespace) -> None:
    """Execute a new research run."""
    question = args.question.strip()
    if not question:
        print("[!] Error: You must provide a research question or topic.")
        sys.exit(1)

    print(f"[*] Starting research run for: '{question}'")
    print(f"[*] Target sources: {args.limit} | Max rounds: {args.rounds}")

    orchestrator = get_orchestrator()

    def on_progress(phase: str, data: dict):
        msg = data.get("message") or f"Phase {phase}"
        if "current" in data and "total" in data:
            print(f"    [{data['current']}/{data['total']}] {msg} ({data.get('domain', '')})")
        else:
            print(f"--> [{phase.upper()}] {msg}")

    try:
        report_path = orchestrator.run_research(
            question=question,
            scope=args.scope,
            target_sources=args.limit,
            max_rounds=args.rounds,
            output_report_path=args.output,
            progress_callback=on_progress
        )
        print(f"\n[✓] Research complete! Report saved at:\n    {os.path.abspath(report_path)}")
    except KeyboardInterrupt:
        print("\n[!] Execution paused by user. Progress is preserved in database.")
    except Exception as e:
        print(f"\n[✗] Run failed: {e}")
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    """Display status and accounting metrics for a research run."""
    repo = ResearchRepository(settings.database_path)
    run = repo.get_run(args.run_id)
    if not run:
        print(f"[!] Error: Research run '{args.run_id}' not found.")
        sys.exit(1)

    stats = repo.get_run_accounting_stats(args.run_id)

    print("=" * 65)
    print(f" RESEARCH RUN STATUS: {run.id}")
    print("=" * 65)
    print(f" Question:           {run.question}")
    print(f" Status:             {run.status.upper()} (Phase: {run.phase})")
    print(f" Created:            {run.created_at}")
    print(f" Primary Model:      {run.model_id}")
    print(f" Verifier Model:     {run.verifier_model_id}")
    print(f" Report Path:        {run.report_path or 'Not generated yet'}")
    print("-" * 65)
    print(" ACCOUNTING COUNTERS:")
    print(f"  - Sources Queued:              {stats['total_sources_queued']}")
    print(f"  - Pages Successfully Fetched:  {stats['fetched_sources']}")
    print(f"  - Pages Failed / Blocked:      {stats['failed_sources']}")
    print(f"  - Pages Extracted:             {stats['extracted_sources']}")
    print(f"  - Total Candidate Evidence:    {stats['total_candidate_evidence']}")
    print(f"  - Exact Quote Validated:       {stats['quote_valid_evidence']}")
    print(f"  - Fully Verified Evidence:     {stats['verified_evidence']}")
    print(f"  - Evidence-Bearing Sources:    {stats['evidence_bearing_sources']}")
    print(f"  - Contradictions Detected:     {stats['contradictions_count']}")
    print(f"  - Synthesized Claims:          {stats['claims_count']}")
    print("=" * 65)


def cmd_list(args: argparse.Namespace) -> None:
    """List all research runs recorded in the database."""
    repo = ResearchRepository(settings.database_path)
    runs = repo.list_all_runs()
    if not runs:
        print("No research runs found in database.")
        return

    print("=" * 80)
    print(f"{'Run ID':<16} | {'Status':<11} | {'Sources':<8} | {'Question'}")
    print("-" * 80)
    for r in runs:
        q_snippet = (r.question[:40] + "...") if len(r.question) > 40 else r.question
        print(f"{r.id:<16} | {r.status:<11} | {r.target_sources:<8} | {q_snippet}")
    print("=" * 80)


def cmd_inspect(args: argparse.Namespace) -> None:
    """Inspect evidence details, quotation, and source context for a citation."""
    repo = ResearchRepository(settings.database_path)
    evid = repo.get_evidence_by_id(args.evidence_id, args.run_id)
    if not evid:
        print(f"[!] Evidence item '{args.evidence_id}' not found in run '{args.run_id}'.")
        sys.exit(1)

    src = repo.get_source_by_id(evid.source_id, args.run_id)

    print("=" * 70)
    print(f" EVIDENCE RECORD: [{evid.id}]")
    print("=" * 70)
    print(f" Run ID:             {evid.run_id}")
    print(f" Source ID:          {evid.source_id} ({src.domain if src else 'N/A'})")
    print(f" Source URL:         {src.url if src else 'N/A'}")
    print(f" Claim Type:         {evid.claim_type} (Evidence: {evid.evidence_type})")
    print(f" Verification:       {evid.support_status.upper()} (Verified: {evid.is_verified})")
    print(f" Reason:             {evid.verification_reason}")
    print("-" * 70)
    print(" CANDIDATE CLAIM:")
    print(f" \"{evid.candidate_claim}\"")
    print("-" * 70)
    print(" VERBATIM SUPPORTING QUOTATION:")
    print(f" \"{evid.exact_quote}\"")
    print("-" * 70)
    print(" SURROUNDING SOURCE CONTEXT:")
    print(f" {evid.surrounding_context}")
    print("=" * 70)


def cmd_export(args: argparse.Namespace) -> None:
    """Export the report markdown for an existing run."""
    repo = ResearchRepository(settings.database_path)
    report = repo.get_report(args.run_id)
    if not report:
        print(f"[!] No generated report found for run '{args.run_id}'.")
        sys.exit(1)

    out_file = args.output or f"report_{args.run_id}.md"
    with open(out_file, "w", encoding="utf-8") as fp:
        fp.write(report["markdown_content"])
    print(f"[✓] Report exported successfully to:\n    {os.path.abspath(out_file)}")


def main():
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Evidence-First Deep Research Engine CLI: Autonomous multi-source research with zero-hallucination verification."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Command: run
    p_run = subparsers.add_parser("run", help="Start a new deep research run.")
    p_run.add_argument("question", type=str, help="Research question or topic.")
    p_run.add_argument("-s", "--scope", type=str, default="", help="Scope boundaries or instructions.")
    p_run.add_argument("-n", "--limit", type=int, default=settings.default_target_sources, help="Target useful sources.")
    p_run.add_argument("-r", "--rounds", type=int, default=settings.max_research_rounds, help="Maximum search rounds.")
    p_run.add_argument("-o", "--output", type=str, default="", help="Custom output report path.")
    p_run.set_defaults(func=cmd_run)

    # Command: status
    p_status = subparsers.add_parser("status", help="View status and accounting stats of a run.")
    p_status.add_argument("run_id", type=str, help="Research run ID.")
    p_status.set_defaults(func=cmd_status)

    # Command: list
    p_list = subparsers.add_parser("list", help="List all previous research runs.")
    p_list.set_defaults(func=cmd_list)

    # Command: inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect supporting quote and context for an evidence citation.")
    p_inspect.add_argument("run_id", type=str, help="Research run ID.")
    p_inspect.add_argument("-e", "--evidence-id", required=True, type=str, help="Evidence ID (e.g. evid-xxxx).")
    p_inspect.set_defaults(func=cmd_inspect)

    # Command: export
    p_export = subparsers.add_parser("export", help="Export report markdown for a completed run.")
    p_export.add_argument("run_id", type=str, help="Research run ID.")
    p_export.add_argument("-o", "--output", type=str, default="", help="Destination markdown path.")
    p_export.set_defaults(func=cmd_export)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

