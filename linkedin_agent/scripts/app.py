"""
LinkedIn Growth Agent — Interfaccia web (Streamlit)
Avvio: streamlit run linkedin_agent/scripts/app.py
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

st.set_page_config(page_title="LinkedIn Growth Agent", page_icon="💼", layout="wide")

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .block-container { padding-top: 1.5rem; }
  h1 { color: #0077B5; }
  .card {
    background: #fff;
    border-radius: 10px;
    padding: 18px 22px;
    margin-bottom: 14px;
    border-left: 4px solid #0077B5;
    box-shadow: 0 1px 6px rgba(0,0,0,0.07);
  }
  .card-yellow { border-left-color: #f5a623; }
  .card-green  { border-left-color: #27ae60; }
  .card-purple { border-left-color: #8e44ad; }
  .pill {
    display: inline-block;
    background: #e8f4fd;
    color: #0077B5;
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 0.75em;
    font-weight: 600;
    margin-right: 4px;
  }
  .why-box {
    background: #f0f7ff;
    border-radius: 8px;
    padding: 10px 14px;
    margin-top: 10px;
    font-size: 0.88em;
    color: #333;
    border-left: 3px solid #0077B5;
  }
  .score-bar { height: 6px; border-radius: 3px; background: #e0e0e0; margin: 4px 0 10px; }
  .score-fill { height: 6px; border-radius: 3px; background: #0077B5; }
  .rec-card {
    background: #fff8f0;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 10px;
    border-left: 3px solid #f5a623;
  }
  .gap-card {
    background: #fff0f0;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 10px;
    border-left: 3px solid #e74c3c;
  }
  .win-card {
    background: #f0fff4;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 10px;
    border-left: 3px solid #27ae60;
  }
</style>
""", unsafe_allow_html=True)

# ── Imports (after path setup) ────────────────────────────────────────────────
from linkedin_agent.automation.browser import BrowserSession
from linkedin_agent.automation.browser_reader import BrowserLinkedInReader
from linkedin_agent.automation.comment_publisher import CommentPublisher
from linkedin_agent.automation.post_publisher import PostPublisher
from linkedin_agent.automation.reaction_publisher import ReactionPublisher
from linkedin_agent.config.settings import load_settings
from linkedin_agent.core.provider_factory import create_llm_provider
from linkedin_agent.modules.context_collector import ContextCollector
from linkedin_agent.modules.content_generator import ContentGenerator
from linkedin_agent.modules.dashboard_state import load_dashboard_state
from linkedin_agent.modules.engagement import EngagementModule
from linkedin_agent.modules.knowledge_store import SectorKnowledgeStore
from linkedin_agent.modules.network import NetworkModule
from linkedin_agent.modules.scheduler import DailyScheduler
from linkedin_agent.modules.strategy_advisor import StrategyAdvisor
from linkedin_agent.modules.tracker import ActivityTracker, PostDraft, PostGenerationResult

# ── Settings ──────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _load():
    try:
        return load_settings(), None
    except Exception as e:
        return None, str(e)

settings, err = _load()
OBSERVABILITY_ONLY_UI = os.environ.get("STREAMLIT_OBSERVABILITY_ONLY", "1").lower() in {"1", "true", "yes"}


def _make_runtime_components():
    db_path = settings.data_dir / "activity_log.db"
    tracker = ActivityTracker(db_path)
    tracker.init_db()
    knowledge_store = SectorKnowledgeStore(db_path)
    knowledge_store.init_db()
    llm = create_llm_provider(settings)
    return tracker, knowledge_store, llm


def _clear_post_state() -> None:
    st.session_state.current_post_result = None
    st.session_state.post_generation_status = "idle"
    st.session_state.current_post_text = ""
    st.session_state.approved_post = None
    st.session_state.post_skipped = False

# ── Session state ─────────────────────────────────────────────────────────────
for k, v in {
    "phase": "home", "plan": None, "dry_run": False,
    "approved_post": None, "post_skipped": False,
    "approved_comments": [], "approved_reactions": [], "approved_connections": [],
    "exec_log": [],
    "linkedin_status": "unknown",
    "linkedin_status_detail": "",
    "post_source_id": "",
    "current_snapshot": None,
    "current_post_result": None,
    "post_generation_status": "idle",
    "current_post_text": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


def _normalize_hashtags_from_text(text: str) -> tuple[str, list[str]]:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    hashtag_lines = [line for line in lines if line.strip().startswith("#")]
    hashtags: list[str] = []
    for line in hashtag_lines:
        hashtags.extend(token for token in line.split() if token.startswith("#"))
    body_lines = [line for line in lines if line not in hashtag_lines]
    body = "\n".join(body_lines).strip()
    deduped: list[str] = []
    seen: set[str] = set()
    for tag in hashtags:
        normalized = tag if tag.startswith("#") else f"#{tag}"
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(normalized)
    return body, deduped


def _render_observability_piano() -> None:
    db_path = settings.data_dir / "activity_log.db"
    if not db_path.exists():
        st.info("Nessun dato disponibile ancora. Esegui i workflow n8n `deep_bootstrap`, `daily_refresh` e `generate_daily_brief` per popolare la dashboard.")
        return

    tracker = ActivityTracker(db_path)
    tracker.init_db()
    state = load_dashboard_state(db_path)
    latest_context = state["latest_context"]
    latest_delta = state["latest_delta"]
    latest_brief = state["latest_brief"]
    latest_post_run = state["latest_post_generation_run"]
    pending = state["pending"]
    approved = state["approved"]

    st.info(
        "Questa UI e' in modalita osservabilita: legge lo stato persistito dai job knowledge-first "
        "e serve solo per review/approval. I job principali vengono orchestrati da n8n."
    )
    st.caption("Workflow attesi: `deep_bootstrap`, `daily_refresh`, `generate_daily_brief`.")

    if latest_context:
        summary = latest_context["summary"]
        counts = summary.get("counts", {})
        st.markdown("### 🧭 Contesto usato oggi")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Profilo reale", "si" if summary.get("profile_snapshot") else "no")
        c2.metric("Tuoi post letti", counts.get("own_posts", 0))
        c3.metric("Post settore letti", counts.get("niche_posts", 0))
        c4.metric("Profili settore letti", counts.get("niche_profiles", 0))
        status_color = "green" if latest_context["status"] == "sufficient" else "orange"
        st.markdown(
            f"<div class='why-box'><b>Stato contesto:</b> <span style='color:{status_color}'>{latest_context['status']}</span><br>"
            f"Snapshot creato alle {latest_context['created_at']}</div>",
            unsafe_allow_html=True,
        )
        if latest_context.get("notes"):
            with st.expander("Dettagli contesto raccolto", expanded=False):
                for note in latest_context["notes"]:
                    st.write(f"- {note}")
        st.divider()

    st.markdown("### 🧠 Base conoscenza")
    overview = state["knowledge_overview"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Post memoria", overview.get("sector_posts", 0))
    k2.metric("Profili memoria", overview.get("sector_profiles", 0))
    k3.metric("Segnali", overview.get("sector_signals", 0))
    k4.metric("Pattern", overview.get("market_patterns", 0))
    if latest_delta:
        delta_payload = latest_delta["delta"]
        st.markdown("### 📈 Delta giornaliero")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Nuovi post", delta_payload.get("new_posts", 0))
        d2.metric("Nuovi profili", delta_payload.get("new_profiles", 0))
        d3.metric("Nuovi segnali", delta_payload.get("signals_emerged", 0))
        d4.metric("Commenti candidati", delta_payload.get("comment_candidates", 0))
        if delta_payload.get("notes") or delta_payload.get("skipped_posts") or delta_payload.get("skipped_profiles"):
            with st.expander("Dettagli delta e scarti", expanded=False):
                for note in delta_payload.get("notes", []):
                    st.write(f"- {note}")
                if delta_payload.get("skipped_posts"):
                    st.write("Post esclusi nella fase finale:")
                    for item in delta_payload["skipped_posts"][:8]:
                        st.write(f"- {item}")
                if delta_payload.get("skipped_profiles"):
                    st.write("Profili esclusi nella fase finale:")
                    for item in delta_payload["skipped_profiles"][:8]:
                        st.write(f"- {item}")
        st.divider()

    st.markdown("### 🧾 Content brief del giorno")
    if not latest_brief:
        st.warning("Nessun content brief persistito ancora. Esegui il workflow `generate_daily_brief`.")
    else:
        brief = latest_brief["brief"]
        st.markdown(
            f"<div class='card'><b>Angolo:</b> {brief['angle_label']}<br>"
            f"<b>Pattern:</b> {brief['selected_pattern']}<br>"
            f"<b>Target:</b> {brief['target_reader']}<br>"
            f"<b>CTA:</b> {brief['recommended_cta']}</div>",
            unsafe_allow_html=True,
        )
        for point in brief.get("supporting_points", []):
            st.write(f"- {point}")
        if brief.get("context_sources"):
            with st.expander("Fonti del brief", expanded=False):
                for item in brief["context_sources"]:
                    st.write(f"- {item}")

    st.divider()
    st.markdown("### 📝 Varianti post in review")
    if not pending["posts"]:
        st.info("Nessuna variante post pending. Esegui `generate_post_variants` sul brief persistito.")
    else:
        for post in pending["posts"][:6]:
            with st.expander(f"Bozza #{post.id} · {post.pillar or 'variante'}", expanded=False):
                initial_text = post.content + (f"\n\n{' '.join(post.hashtags)}" if post.hashtags else "")
                edited = st.text_area(
                    "Bozza modificabile",
                    value=initial_text,
                    height=220,
                    key=f"review_post_{post.id}",
                )
                st.markdown(f"<div class='why-box'><b>Rationale:</b> {post.rationale or 'n/d'}</div>", unsafe_allow_html=True)
                if post.context_sources:
                    st.caption("Fonti usate")
                    for item in post.context_sources:
                        st.write(f"- {item}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Approva variante", key=f"approve_post_{post.id}", use_container_width=True):
                        body, hashtags = _normalize_hashtags_from_text(edited)
                        tracker.update_post_content(post.id, body or post.content, hashtags or post.hashtags)
                        tracker.update_post_status(post.id, "approved")
                        st.rerun()
                with c2:
                    if st.button("⏭️ Scarta variante", key=f"reject_post_{post.id}", use_container_width=True):
                        tracker.update_post_status(post.id, "rejected")
                        st.rerun()

    st.markdown("### 💬 Commenti candidati")
    if pending["comments"]:
        for item in pending["comments"][:6]:
            with st.expander(f"{item.post_author} · score {int(item.relevance_score * 100)}%", expanded=False):
                st.write(item.post_text_snippet)
                st.write(item.comment_text)
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Approva commento", key=f"approve_comment_{item.id}", use_container_width=True):
                        tracker.update_comment_status(item.id, "approved")
                        st.rerun()
                with c2:
                    if st.button("⏭️ Scarta commento", key=f"reject_comment_{item.id}", use_container_width=True):
                        tracker.update_comment_status(item.id, "rejected")
                        st.rerun()
    else:
        st.info("Nessun commento candidato persistito. Se il daily refresh non ha trovato candidati, guarda gli scarti nel delta giornaliero.")

    st.markdown("### 👍 Reazioni candidate")
    if pending["reactions"]:
        for item in pending["reactions"][:6]:
            with st.expander(f"{item.post_author} · {item.reaction_type}", expanded=False):
                st.write(item.post_text_snippet)
                st.write(item.motivation or "Reazione selezionata dal ranking.")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Approva reazione", key=f"approve_reaction_{item.id}", use_container_width=True):
                        tracker.update_reaction_status(item.id, "approved")
                        st.rerun()
                with c2:
                    if st.button("⏭️ Scarta reazione", key=f"reject_reaction_{item.id}", use_container_width=True):
                        tracker.update_reaction_status(item.id, "rejected")
                        st.rerun()
    else:
        st.info("Nessuna reazione candidata persistita.")

    st.markdown("### 🤝 Connessioni candidate")
    if pending["connections"]:
        for item in pending["connections"][:6]:
            with st.expander(f"{item.full_name} · score {int(item.relevance_score * 100)}%", expanded=False):
                st.write(item.headline)
                if item.profile_url:
                    st.markdown(f"[Apri profilo]({item.profile_url})")
                st.write(item.motivation or "Connessione selezionata dal ranking.")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Approva connessione", key=f"approve_connection_{item.id}", use_container_width=True):
                        tracker.update_connection_status(item.id, "approved")
                        st.rerun()
                with c2:
                    if st.button("⏭️ Scarta connessione", key=f"reject_connection_{item.id}", use_container_width=True):
                        tracker.update_connection_status(item.id, "rejected")
                        st.rerun()
    else:
        st.info("Nessuna connessione candidata persistita.")

    st.divider()
    st.markdown("### ✅ Stato review")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Post approvati", len(approved["posts"]))
    a2.metric("Commenti approvati", len(approved["comments"]))
    a3.metric("Reazioni approvate", len(approved["reactions"]))
    a4.metric("Connessioni approvate", len(approved["connections"]))
    if latest_post_run:
        with st.expander("Ultimo tentativo generazione post", expanded=False):
            st.write(f"Stato: {latest_post_run['status']}")
            st.write(f"Modello: {latest_post_run['model']}")
            if latest_post_run["error_message"]:
                st.write(f"Errore: {latest_post_run['error_message']}")
            for item in latest_post_run.get("validation_errors", []):
                st.write(f"- {item}")

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_user = st.columns([3, 1])
with col_title:
    st.title("💼 LinkedIn Growth Agent")
    if settings:
        st.caption(f"Gestione account: **{settings.linkedin_email}** · Niche: fondi europei & PNRR")
        if settings.llm_provider:
            model_name = settings.anthropic_model if settings.llm_provider == "claude" else settings.gemini_model
            provider_label = settings.llm_provider.capitalize()
            if model_name:
                st.caption(f"Provider LLM: `{provider_label}` · Modello: `{model_name}`")
            else:
                st.caption(f"Provider LLM: `{provider_label}`")
with col_user:
    if settings:
        st.markdown(f"""
        <div style='text-align:right;padding-top:10px'>
          <span style='font-weight:700;color:#0077B5;font-size:1.1em'>{settings.user.name}</span><br>
          <span style='font-size:0.8em;color:#666'>{settings.user.headline}</span>
        </div>""", unsafe_allow_html=True)

if err:
    st.error(f"Errore configurazione: {err}")
    st.stop()

if st.session_state.linkedin_status == "connected":
    st.success(f"LinkedIn: {st.session_state.linkedin_status_detail}")
elif st.session_state.linkedin_status == "browser_only":
    st.info(f"LinkedIn: {st.session_state.linkedin_status_detail}")
elif st.session_state.linkedin_status == "failed":
    st.warning(f"LinkedIn: {st.session_state.linkedin_status_detail}")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_piano, tab_profilo, tab_stats = st.tabs(["📋 Piano Giornaliero", "🔍 Analisi Profilo", "📊 Statistiche"])

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — PIANO GIORNALIERO
# ════════════════════════════════════════════════════════════════════════════
with tab_piano:
    _render_observability_piano()


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — ANALISI PROFILO
# ════════════════════════════════════════════════════════════════════════════
with tab_profilo:
    st.markdown("### 🔍 Analisi del tuo posizionamento LinkedIn")
    if OBSERVABILITY_ONLY_UI:
        st.info(
            "In modalita osservabilita questa tab non lancia job nuovi. "
            "Usa i workflow orchestrati per aggiornare snapshot e base conoscenza, "
            "poi consulta qui le evidenze gia persistite nella dashboard."
        )
        st.caption("La prossima milestone puo spostare anche l'analisi profilo su job dedicati orchestrati.")
    else:
        st.caption("L'AI analizza il tuo profilo reale, i tuoi post recenti e un benchmark del settore per darti raccomandazioni concrete.")

    col_info, col_btn = st.columns([3, 1])
    with col_info:
        st.markdown(f"""
        <div class='card'>
          <b>{settings.user.name}</b> · {settings.user.headline}<br>
          <span class='pill'>fondi europei</span>
          <span class='pill'>PNRR</span>
          <span class='pill'>Horizon Europe</span>
          <span class='pill'>terzo settore</span>
        </div>
        """, unsafe_allow_html=True)
    with col_btn:
        run_analysis = st.button(
            "🔍 Analizza profilo",
            type="primary",
            use_container_width=True,
            disabled=OBSERVABILITY_ONLY_UI,
        )

    if run_analysis and not OBSERVABILITY_ONLY_UI:
        with st.spinner("L'LLM sta analizzando il tuo posizionamento..."):
            db_path = settings.data_dir / "activity_log.db"
            tracker = ActivityTracker(db_path)
            tracker.init_db()
            llm = create_llm_provider(settings)
            advisor = StrategyAdvisor(settings, llm, tracker)
            try:
                browser_ok, browser_detail = BrowserSession.probe_saved_session(settings)
                if not browser_ok:
                    st.error(f"LinkedIn non collegato: {browser_detail}")
                else:
                    collector = ContextCollector(settings, tracker, BrowserLinkedInReader(settings))
                    snapshot = collector.collect_daily_context()
                    analysis = advisor.analyze_profile_positioning(snapshot)
                    analysis["snapshot_summary"] = snapshot.to_dict()
            except Exception as e:
                st.error(llm.describe_error(e, llm.model_name))
            else:
                if browser_ok:
                    st.session_state["profile_analysis"] = analysis

    if "profile_analysis" in st.session_state:
        a = st.session_state["profile_analysis"]
        summary = a.get("snapshot_summary", {})

        # Score
        score = a.get("positioning_score", 0)
        bar_w = int(score * 10)
        st.markdown(f"""
        <div style='margin:20px 0 10px'>
          <span style='font-size:1.1em;font-weight:700'>Punteggio posizionamento: {score}/10</span>
          <div class='score-bar'><div class='score-fill' style='width:{bar_w}%'></div></div>
          <span style='font-size:0.88em;color:#555'>{a.get("score_rationale","")}</span>
        </div>
        """, unsafe_allow_html=True)
        if a.get("context_evidence"):
            with st.expander("Evidenze usate nell'analisi", expanded=False):
                for item in a.get("context_evidence", []):
                    st.write(f"- {item}")
        if summary:
            counts = summary.get("counts", {})
            st.caption(
                f"Snapshot usato: {summary.get('created_at', 'n/d')} · "
                f"stato {summary.get('status', 'n/d')} · "
                f"tuoi post {counts.get('own_posts', 0)} · "
                f"post settore {counts.get('niche_posts', 0)} · "
                f"profili settore {counts.get('niche_profiles', 0)}"
            )

        is_empty_analysis = not any([
            a.get("strengths"),
            a.get("gaps"),
            a.get("opportunities"),
            a.get("profile_recommendations"),
            a.get("content_recommendations"),
            a.get("quick_wins"),
        ])
        if is_empty_analysis:
            st.warning(
                "L'analisi e' stata eseguita ma il provider LLM non ha restituito raccomandazioni strutturate. "
                "Guarda lo snapshot e le evidenze usate qui sopra: il problema ora e' di output AI, "
                "non di assenza totale di contesto."
            )

        # 3 columns: strengths / gaps / opportunities
        col_s, col_g, col_o = st.columns(3)
        with col_s:
            st.markdown("#### ✅ Punti di forza")
            for s in a.get("strengths", []):
                st.markdown(f"<div class='win-card'>✔ {s}</div>", unsafe_allow_html=True)
        with col_g:
            st.markdown("#### ⚠️ Lacune")
            for g in a.get("gaps", []):
                st.markdown(f"<div class='gap-card'>✖ {g}</div>", unsafe_allow_html=True)
        with col_o:
            st.markdown("#### 🚀 Opportunità")
            for o in a.get("opportunities", []):
                st.markdown(f"<div class='rec-card'>→ {o}</div>", unsafe_allow_html=True)

        st.divider()

        # Profile recommendations
        pr = a.get("profile_recommendations", [])
        if pr:
            st.markdown("#### 🛠️ Raccomandazioni per il profilo LinkedIn")
            for rec in pr:
                st.markdown(f"""
                <div class='rec-card'>
                  <b>{rec.get("area","")}</b><br>
                  <span style='color:#888;font-size:0.88em'>Problema: {rec.get("issue","")}</span><br>
                  💡 {rec.get("suggestion","")}
                </div>
                """, unsafe_allow_html=True)

        # Content recommendations
        cr = a.get("content_recommendations", [])
        if cr:
            st.markdown("#### 📈 Raccomandazioni per la strategia di contenuto")
            for rec in sorted(cr, key=lambda x: x.get("priority", 99)):
                st.markdown(f"""
                <div class='rec-card'>
                  <span style='color:#f5a623;font-weight:700'>#{rec.get("priority","")}</span>
                  <b> {rec.get("action","")}</b><br>
                  <span style='font-size:0.88em;color:#555'>{rec.get("rationale","")}</span>
                </div>
                """, unsafe_allow_html=True)

        # Quick wins
        qw = a.get("quick_wins", [])
        if qw:
            st.markdown("#### ⚡ Quick wins — da fare oggi")
            for q in qw:
                st.markdown(f"<div class='win-card'>⚡ {q}</div>", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — STATISTICHE
# ════════════════════════════════════════════════════════════════════════════
with tab_stats:
    st.markdown("### 📊 Statistiche attività")

    db_path = settings.data_dir / "activity_log.db"
    if not db_path.exists():
        st.info("Nessuna attività registrata ancora. Esegui il setup DB prima.")
    else:
        tracker = ActivityTracker(db_path)
        tracker.init_db()
        knowledge_store = SectorKnowledgeStore(db_path)
        knowledge_store.init_db()
        report = tracker.export_progress_report()
        knowledge_overview = knowledge_store.get_overview()

        # KPI metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Post pubblicati", report["all_time"]["posts_published"], delta=f"{report['this_week']['posts']} questa settimana")
        c2.metric("Commenti postati", report["all_time"]["comments_posted"], delta=f"{report['today']['comments']} oggi")
        c3.metric("Reazioni fatte", report["all_time"]["reactions_done"], delta=f"{report['today']['reactions']} oggi")
        c4.metric("Connessioni inviate", report["all_time"]["connections_sent"], delta=f"{report['today']['connections']} oggi")

        st.caption(
            f"Profili esplorati: {report['all_time']['profiles_seen']} · "
            f"Tuoi post letti: {report['all_time']['recent_posts_seen']} · "
            f"Post settore letti: {report['all_time']['niche_posts_seen']} · "
            f"Snapshot contesto: {report['all_time']['context_runs']} · "
            f"Tentativi generazione post: {report['all_time']['post_generation_runs']}"
        )

        st.markdown(
            f"<div class='why-box'><b>Knowledge base:</b> post {knowledge_overview['sector_posts']} · "
            f"profili {knowledge_overview['sector_profiles']} · segnali {knowledge_overview['sector_signals']} · "
            f"pattern {knowledge_overview['market_patterns']} · brief {knowledge_overview['content_briefs']}</div>",
            unsafe_allow_html=True,
        )

        st.divider()

        # Limits status
        st.markdown("#### Limiti giornalieri / settimanali")
        lim = settings.activity.daily_limits
        rows = [
            ("Post questa settimana", report["this_week"]["posts"], lim.posts_per_week),
            ("Commenti oggi", report["today"]["comments"], lim.comments_per_day),
            ("Reazioni oggi", report["today"]["reactions"], lim.reactions_per_day),
            ("Connessioni oggi", report["today"]["connections"], lim.connection_requests_per_day),
        ]
        for label, used, limit in rows:
            pct = min(used / max(limit, 1), 1.0)
            color = "#e74c3c" if pct >= 0.9 else "#f5a623" if pct >= 0.6 else "#27ae60"
            st.markdown(f"""
            <div style='margin-bottom:10px'>
              <div style='display:flex;justify-content:space-between;font-size:0.88em;margin-bottom:3px'>
                <span>{label}</span><span style='color:{color}'>{used}/{limit}</span>
              </div>
              <div class='score-bar'><div class='score-fill' style='width:{pct*100:.0f}%;background:{color}'></div></div>
            </div>
            """, unsafe_allow_html=True)

        st.divider()

        st.markdown("#### Profili visitati di recente")
        recent_profiles = tracker.get_recent_seen_profiles(limit=15)
        if not recent_profiles:
            st.info("Nessun profilo visitato registrato ancora.")
        else:
            for profile in recent_profiles:
                score_pct = int((profile["relevance_score"] or 0.0) * 100)
                name = profile["full_name"] or profile["profile_urn"]
                headline = profile["headline"] or "Profilo senza headline rilevata"
                seen_at = profile["first_seen_at"] or "timestamp non disponibile"
                url = profile["profile_url"]
                if url:
                    st.markdown(
                        f"- [{name}]({url}) · {headline} · rilevanza {score_pct}% · visto {seen_at}"
                    )
                else:
                    st.markdown(
                        f"- {name} · {headline} · rilevanza {score_pct}% · visto {seen_at}"
                    )

        st.divider()

        st.markdown("#### Post tuoi letti di recente")
        own_posts = tracker.get_recent_seen_posts("recent_posts_seen", limit=10)
        if not own_posts:
            st.info("Nessun post recente del profilo registrato ancora.")
        else:
            for post in own_posts:
                label = post["author_name"] or "Tu"
                snippet = post["text_snippet"][:160]
                st.markdown(f"- {label}: {snippet}...")

        st.markdown("#### Post del settore analizzati")
        niche_posts = tracker.get_recent_seen_posts("niche_posts_seen", limit=10)
        if not niche_posts:
            st.info("Nessun post di settore registrato ancora.")
        else:
            for post in niche_posts:
                query = f" · query {post['source_query']}" if post["source_query"] else ""
                st.markdown(
                    f"- {post['author_name']}: {post['text_snippet'][:150]}... "
                    f"(reazioni {post['reaction_count']}, commenti {post['comment_count']}{query})"
                )

        st.divider()

        st.markdown("#### Ultimo snapshot di contesto")
        latest_context = tracker.get_latest_context_run()
        if not latest_context:
            st.info("Nessun context snapshot registrato ancora.")
        else:
            summary = latest_context["summary"]
            counts = summary.get("counts", {})
            st.markdown(
                f"- Creato: {latest_context['created_at']}\n"
                f"- Stato: {latest_context['status']}\n"
                f"- Tuoi post: {counts.get('own_posts', 0)}\n"
                f"- Post settore: {counts.get('niche_posts', 0)}\n"
                f"- Profili settore: {counts.get('niche_profiles', 0)}"
            )
            if latest_context.get("notes"):
                with st.expander("Note snapshot", expanded=False):
                    for note in latest_context["notes"]:
                        st.write(f"- {note}")

        st.divider()

        st.markdown("#### Ultimo aggiornamento knowledge-first")
        latest_knowledge = knowledge_store.get_latest_knowledge_run()
        latest_delta = knowledge_store.get_latest_delta()
        latest_brief = knowledge_store.get_latest_brief()
        if not latest_knowledge:
            st.info("Nessun knowledge run registrato ancora.")
        else:
            st.markdown(
                f"- Run: {latest_knowledge['run_kind']}\n"
                f"- Creato: {latest_knowledge['created_at']}\n"
                f"- Stato: {latest_knowledge['status']}\n"
                f"- Scope: {latest_knowledge['market_scope']}"
            )
            if latest_knowledge["summary"]:
                with st.expander("Summary knowledge run", expanded=False):
                    for key, value in latest_knowledge["summary"].items():
                        st.write(f"- {key}: {value}")
        if latest_delta:
            st.markdown(
                f"- Ultimo delta: {latest_delta['created_at']} · snapshot {latest_delta['snapshot_id'] or 'n/d'}"
            )
        if latest_brief:
            st.markdown(
                f"- Ultimo brief: {latest_brief['created_at']} · angolo {latest_brief['angle_label']}"
            )

        st.divider()

        st.markdown("#### Ultima generazione post")
        latest_post_run = tracker.get_latest_post_generation_run()
        if not latest_post_run:
            st.info("Nessun tentativo di generazione post registrato ancora.")
        else:
            st.markdown(
                f"- Creato: {latest_post_run['created_at']}\n"
                f"- Stato: {latest_post_run['status']}\n"
                f"- Modello: {latest_post_run['model']}\n"
                f"- Snapshot ID: {latest_post_run['snapshot_id'] or 'n/d'}"
            )
            if latest_post_run["error_message"] or latest_post_run["validation_errors"] or latest_post_run["raw_excerpt"]:
                with st.expander("Dettagli ultima generazione", expanded=False):
                    if latest_post_run["error_message"]:
                        st.write(f"Errore: {latest_post_run['error_message']}")
                    for item in latest_post_run["validation_errors"]:
                        st.write(f"- {item}")
                    if latest_post_run["raw_excerpt"]:
                        st.caption(f"Estratto tecnico: {latest_post_run['raw_excerpt']}")
