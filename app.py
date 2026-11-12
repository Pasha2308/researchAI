"""Streamlit Web Dashboard for the Evidence-First Deep Research Engine.

Provides an interactive local dashboard bound to 127.0.0.1 for configuring,
launching, tracking, and auditing deep research runs with interactive evidence inspection.
"""

import os
import sys
from pathlib import Path
import streamlit as st

# Ensure project root is in python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings
from research_engine.database.connection import init_database
from research_engine.database.repository import ResearchRepository
from research_engine.providers.llm.groq_provider import GroqLLMProvider
from research_engine.research.orchestrator import ResearchOrchestrator

# Initialize database
init_database()
repo = ResearchRepository(settings.database_path)

st.set_page_config(
    page_title="Evidence-First Deep Research Engine",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown(
    """
    <style>
    .main-header { font-size: 2.2rem; font-weight: 700; color: #1E3A8A; margin-bottom: 0.2rem; }
    .sub-header { font-size: 1.05rem; color: #4B5563; margin-bottom: 1.5rem; }
    .metric-card { background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; }
    .badge-tier-a { background-color: #DCFCE7; color: #166534; padding: 3px 8px; border-radius: 4px; font-weight: 600; }
    .badge-tier-b { background-color: #E0F2FE; color: #075985; padding: 3px 8px; border-radius: 4px; font-weight: 600; }
    .badge-tier-c { background-color: #FEF3C7; color: #92400E; padding: 3px 8px; border-radius: 4px; font-weight: 600; }
    .badge-tier-d { background-color: #F1F5F9; color: #475569; padding: 3px 8px; border-radius: 4px; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown("<div class='main-header'>🔬 Evidence-First Deep Research Engine</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='sub-header'>Systematic autonomous research backed by traceable source quotations and fail-closed verification.</div>",
    unsafe_allow_html=True
)

# Sidebar: Run Selection & History
st.sidebar.title("Navigation & History")
all_runs = repo.list_all_runs()
run_options = {f"{r.id} - {r.question[:30]}...": r.id for r in all_runs}

selected_run_label = st.sidebar.selectbox(
    "Select Existing Run to Inspect",
    options=["-- Create New Research Run --"] + list(run_options.keys()),
    index=0
)

# Main Navigation Tabs
tab_new, tab_monitor, tab_evidence, tab_report = st.tabs([
    "🚀 New Research Run",
    "📊 Run Accounting & Metrics",
    "🔍 Evidence & Citation Inspector",
    "📄 Report Viewer"
])

# =============================================================================
# Tab 1: New Research Run
# =============================================================================
with tab_new:
    st.subheader("Launch an Evidence-First Deep Research Run")

    col_q1, col_q2 = st.columns([3, 1])
    with col_q1:
        question_input = st.text_area(
            "Research Question / Topic",
            placeholder="e.g. FastAPI vs Flask in high-throughput 2026 production: benchmarks, failure modes, and user consensus",
            height=100
        )
        scope_input = st.text_input(
            "Scope Boundaries / Constraints (Optional)",
            placeholder="e.g. Focus on Python 3.12+, exclude microcontrollers, require empirical benchmarks"
        )

    with col_q2:
        target_sources = st.number_input("Target Sources", min_value=10, max_value=300, value=settings.default_target_sources, step=10)
        max_rounds = st.slider("Max Iterative Rounds", min_value=1, max_value=5, value=settings.max_research_rounds)
        recency = st.selectbox("Search Recency", ["Anytime", "Past Year (y)", "Past Month (m)", "Past Week (w)"])
        recency_val = None
        if "Past Year" in recency:
            recency_val = "y"
        elif "Past Month" in recency:
            recency_val = "m"
        elif "Past Week" in recency:
            recency_val = "w"

    # API Key check
    api_key_configured = bool(settings.groq_api_key.strip())
    if not api_key_configured:
        st.warning("⚠️ `GROQ_API_KEY` is not detected in your `.env` file. You can enter it temporarily below:")
        temp_api_key = st.text_input("Temporary Groq API Key", type="password")
    else:
        temp_api_key = settings.groq_api_key

    start_button = st.button("🚀 Start Deep Research", type="primary", use_container_width=True)

    if start_button:
        active_key = temp_api_key.strip() or settings.groq_api_key.strip()
        if not active_key:
            st.error("Cannot launch: GROQ_API_KEY is required for live research.")
        elif not question_input.strip():
            st.error("Please enter a valid research question.")
        else:
            status_box = st.status("Initializing research pipeline...", expanded=True)

            try:
                llm = GroqLLMProvider(api_key=active_key, default_model=settings.groq_model)
                verifier_llm = GroqLLMProvider(api_key=active_key, default_model=settings.groq_verifier_model)
                orchestrator = ResearchOrchestrator(
                    llm_provider=llm,
                    verifier_llm_provider=verifier_llm,
                    repository=repo
                )

                progress_bar = st.progress(0.0)

                def st_progress(phase: str, data: dict):
                    msg = data.get("message") or f"Phase: {phase}"
                    if "current" in data and "total" in data:
                        status_box.update(label=f"[{phase.upper()}] {data['current']}/{data['total']}: {data.get('domain', '')}")
                    else:
                        status_box.update(label=f"[{phase.upper()}] {msg}")

                report_file = orchestrator.run_research(
                    question=question_input.strip(),
                    scope=scope_input.strip(),
                    target_sources=target_sources,
                    max_rounds=max_rounds,
                    progress_callback=st_progress
                )

                status_box.update(label="✅ Deep Research Run Completed Successfully!", state="complete")
                st.success(f"Report generated at: `{report_file}`")
                st.rerun()

            except Exception as e:
                status_box.update(label=f"❌ Run failed: {e}", state="error")
                st.error(f"Error details: {e}")

# =============================================================================
# Tab 2: Run Accounting & Metrics
# =============================================================================
active_run_id = None
if selected_run_label != "-- Create New Research Run --":
    active_run_id = run_options.get(selected_run_label)
elif all_runs:
    active_run_id = all_runs[0].id

with tab_monitor:
    if not active_run_id:
        st.info("No research runs available. Launch a new run above.")
    else:
        run = repo.get_run(active_run_id)
        stats = repo.get_run_accounting_stats(active_run_id)

        st.subheader(f"Run Accounting: `{active_run_id}`")
        st.caption(f"Question: **{run.question if run else ''}**")

        # Top metric cards
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Sources Queued", stats["total_sources_queued"])
        m2.metric("Pages Fetched", stats["fetched_sources"])
        m3.metric("Pages Extracted", stats["extracted_sources"])
        m4.metric("Candidate Evidence", stats["total_candidate_evidence"])
        m5.metric("Quote Validated", stats["quote_valid_evidence"])
        m6.metric("Verified Evidence", stats["verified_evidence"])

        st.divider()

        col_left, col_right = st.columns([1, 1])
        with col_left:
            st.markdown("#### Source Quality Tiers Breakdown")
            tiers = stats["tier_breakdown"]
            if tiers:
                for tier_name, count in sorted(tiers.items()):
                    badge_cls = f"badge-{tier_name.lower().replace(' ', '-')}"
                    st.markdown(f"<span class='{badge_cls}'>{tier_name}</span>: **{count} sources**", unsafe_allow_html=True)
            else:
                st.write("No tier distribution recorded.")

            st.markdown("#### Contradictions & Disagreements")
            contradictions = repo.get_contradictions_for_run(active_run_id)
            if contradictions:
                for c in contradictions:
                    st.warning(f"⚠️ **{c.topic_facet}**: {c.description}")
            else:
                st.info("No direct contradictions detected among verified sources.")

        with col_right:
            st.markdown("#### Search Queries Executed")
            queries = repo.get_search_queries(active_run_id)
            if queries:
                q_data = [{"Round": q["round_num"], "Category": q["category"], "Query": q["query"], "Results": q["results_count"]} for q in queries]
                st.dataframe(q_data, use_container_width=True, hide_index=True)
            else:
                st.write("No queries recorded.")

# =============================================================================
# Tab 3: Evidence & Citation Inspector
# =============================================================================
with tab_evidence:
    if not active_run_id:
        st.info("Select a research run to inspect evidence.")
    else:
        st.subheader("Interactive Citation & Evidence Inspector")
        st.caption("Inspect exact quotations, character offsets, surrounding context, and verification verdicts.")

        all_evidence = repo.get_all_evidence_for_run(active_run_id)
        sources_list = repo.get_sources_for_run(active_run_id)
        sources_map = {s.id: s for s in sources_list if s.id is not None}

        if not all_evidence:
            st.write("No evidence items found for this run.")
        else:
            filter_choice = st.radio(
                "Filter Evidence Status",
                ["All", "Verified Only", "Quote Valid Only", "Rejected / Unverified"],
                horizontal=True
            )

            filtered = []
            for e in all_evidence:
                if filter_choice == "Verified Only" and not e.is_verified:
                    continue
                if filter_choice == "Quote Valid Only" and not e.quote_valid:
                    continue
                if filter_choice == "Rejected / Unverified" and e.is_verified:
                    continue
                filtered.append(e)

            st.write(f"Showing **{len(filtered)}** evidence items:")

            for evid in filtered:
                src = sources_map.get(evid.source_id)
                domain = src.domain if src else "unknown"
                url = src.url if src else "#"
                tier = src.source_tier if src else "Tier D"

                status_icon = "✅" if evid.is_verified else ("⚠️" if evid.quote_valid else "❌")

                with st.expander(f"{status_icon} [{evid.id}] ({domain}) - {evid.candidate_claim[:80]}..."):
                    c1, c2 = st.columns([2, 1])
                    with c1:
                        st.markdown(f"**Candidate Claim:** {evid.candidate_claim}")
                        st.markdown(f"**Verbatim Quote:** *\"{evid.exact_quote}\"*")
                        st.markdown(f"**Surrounding Source Context:**\n> {evid.surrounding_context}")
                    with c2:
                        st.markdown(f"**Source:** [{domain}]({url}) ({tier})")
                        st.markdown(f"**Claim Type:** `{evid.claim_type}`")
                        st.markdown(f"**Evidence Type:** `{evid.evidence_type}`")
                        st.markdown(f"**Support Verdict:** `{evid.support_status}`")
                        st.markdown(f"**Quote Valid:** `{'Yes' if evid.quote_valid else 'No'}`")
                        st.markdown(f"**Reason:** {evid.verification_reason}")

# =============================================================================
# Tab 4: Report Viewer
# =============================================================================
with tab_report:
    if not active_run_id:
        st.info("Select a research run to view its report.")
    else:
        report_record = repo.get_report(active_run_id)
        if not report_record:
            st.write("No report has been generated for this run yet.")
        else:
            st.subheader(report_record.get("title", "Research Report"))
            r_col1, r_col2 = st.columns([4, 1])
            with r_col2:
                st.download_button(
                    label="📥 Download Report (.md)",
                    data=report_record["markdown_content"],
                    file_name=f"research_report_{active_run_id}.md",
                    mime="text/markdown",
                    use_container_width=True
                )

            st.divider()
            st.markdown(report_record["markdown_content"])

