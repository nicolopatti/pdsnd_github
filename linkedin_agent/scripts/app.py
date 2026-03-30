"""
LinkedIn Growth Agent — Interfaccia grafica web (Streamlit)

Avvio:
    streamlit run linkedin_agent/scripts/app.py

Si apre automaticamente il browser su http://localhost:8501
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from linkedin_agent.automation.browser import BrowserSession
from linkedin_agent.automation.comment_publisher import CommentPublisher
from linkedin_agent.automation.post_publisher import PostPublisher
from linkedin_agent.automation.reaction_publisher import ReactionPublisher
from linkedin_agent.config.settings import load_settings
from linkedin_agent.core.ai_client import AIClient
from linkedin_agent.core.linkedin_client import LinkedInReader
from linkedin_agent.modules.content_generator import ContentGenerator
from linkedin_agent.modules.engagement import EngagementModule
from linkedin_agent.modules.network import NetworkModule
from linkedin_agent.modules.scheduler import DailyScheduler
from linkedin_agent.modules.strategy_advisor import StrategyAdvisor
from linkedin_agent.modules.tracker import ActivityTracker

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="LinkedIn Growth Agent",
    page_icon="🚀",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------
def _init_state():
    defaults = {
        "phase": "home",          # home | planning | reviewing | executing | done
        "plan": None,
        "approved_post": None,
        "post_skipped": False,
        "approved_comments": [],
        "approved_reactions": [],
        "approved_connections": [],
        "execution_log": [],
        "settings": None,
        "linkedin_ok": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# ---------------------------------------------------------------------------
# Load settings (cached)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_settings():
    try:
        return load_settings(), None
    except Exception as e:
        return None, str(e)

settings, settings_error = get_settings()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🚀 LinkedIn Growth Agent")
st.caption("Genera, rivedi e pubblica contenuti LinkedIn in modo semi-automatico.")

if settings_error:
    st.error(f"Errore configurazione: {settings_error}")
    st.info("Controlla che il file `.env` esista e contenga GEMINI_API_KEY, LINKEDIN_EMAIL, LINKEDIN_PASSWORD.")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar — status
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Stato")
    st.success("✅ Gemini API configurata")
    st.success(f"✅ Account: {settings.linkedin_email}")
    if settings.linkedin_li_at:
        st.success("✅ Cookie li_at presente")
    else:
        st.warning("⚠️ Cookie li_at non presente (possibile CHALLENGE)")

    st.divider()
    st.header("Limiti settimanali")
    st.write(f"Post/settimana: **{settings.activity.daily_limits.posts_per_week}**")
    st.write(f"Commenti/giorno: **{settings.activity.daily_limits.comments_per_day}**")
    st.write(f"Reazioni/giorno: **{settings.activity.daily_limits.reactions_per_day}**")
    st.write(f"Connessioni/giorno: **{settings.activity.daily_limits.connection_requests_per_day}**")

    st.divider()
    if st.button("🔄 Ricomincia da capo"):
        for k in ["phase", "plan", "approved_post", "post_skipped",
                  "approved_comments", "approved_reactions", "approved_connections", "execution_log"]:
            st.session_state[k] = None if k in ("plan", "approved_post") else ([] if k.startswith("approved") or k == "execution_log" else ("home" if k == "phase" else False))
        st.session_state["phase"] = "home"
        st.session_state["post_skipped"] = False
        st.rerun()

# ---------------------------------------------------------------------------
# FASE 1 — HOME
# ---------------------------------------------------------------------------
if st.session_state.phase == "home":
    st.subheader("Piano Giornaliero")
    st.write("Clicca il bottone per generare il piano di oggi: post, commenti, reazioni e connessioni.")

    col1, col2 = st.columns([1, 3])
    with col1:
        dry_run = st.checkbox("Modalità demo (dati finti)", value=False)
    with col2:
        st.caption("Usa la modalità demo per testare senza toccare LinkedIn.")

    if st.button("📋 Genera Piano Giornaliero", type="primary", use_container_width=True):
        st.session_state.phase = "planning"
        st.session_state["_dry_run"] = dry_run
        st.rerun()

# ---------------------------------------------------------------------------
# FASE 2 — PLANNING (spinner + build)
# ---------------------------------------------------------------------------
elif st.session_state.phase == "planning":
    dry_run = st.session_state.get("_dry_run", False)

    with st.spinner("Caricamento piano giornaliero... (può richiedere qualche secondo)"):
        db_path = settings.data_dir / "activity_log.db"
        tracker = ActivityTracker(db_path)
        tracker.init_db()

        ai = AIClient(api_key=settings.gemini_api_key)
        content_gen = ContentGenerator(settings, ai)
        advisor = StrategyAdvisor(settings, ai, tracker)

        linkedin_reader = None
        engagement = None
        network = None

        if not dry_run:
            try:
                linkedin_reader = LinkedInReader(
                    settings.linkedin_email,
                    settings.linkedin_password,
                    li_at=settings.linkedin_li_at,
                )
                engagement = EngagementModule(settings, ai, linkedin_reader, tracker)
                network = NetworkModule(settings, ai, linkedin_reader, tracker)
                st.session_state.linkedin_ok = True
            except Exception as e:
                st.warning(f"⚠️ Login LinkedIn non riuscito ({e}). Continuo in modalità solo-contenuto.")
                st.session_state.linkedin_ok = False

        class _StubEngagement:
            def get_daily_engagement_queue(self, limit=None): return []
            def get_reaction_queue(self, limit=None): return []

        class _StubNetwork:
            def get_connection_queue(self, limit=None): return []

        scheduler = DailyScheduler(
            settings=settings,
            tracker=tracker,
            content_gen=content_gen,
            engagement=engagement or _StubEngagement(),
            network=network or _StubNetwork(),
        )

        plan = scheduler.build_daily_plan(dry_run=dry_run)
        st.session_state.plan = plan
        st.session_state.approved_comments = [True] * len(plan.comments)
        st.session_state.approved_reactions = [True] * len(plan.reactions)
        st.session_state.approved_connections = [True] * len(plan.connections)
        st.session_state.phase = "reviewing"
        st.rerun()

# ---------------------------------------------------------------------------
# FASE 3 — REVIEWING
# ---------------------------------------------------------------------------
elif st.session_state.phase == "reviewing":
    plan = st.session_state.plan

    if not plan or plan.total_actions == 0:
        st.info("Nessuna attività pianificata per oggi.")
        if plan and plan.notes:
            for note in plan.notes:
                st.caption(f"ℹ️ {note}")
    else:
        # Notes
        for note in (plan.notes or []):
            st.caption(f"ℹ️ {note}")

        # ----------------------------------------------------------------
        # POST
        # ----------------------------------------------------------------
        if plan.post_draft:
            st.subheader("📝 Post da pubblicare")
            post = plan.post_draft
            full_text = post.content + "\n\n" + " ".join(post.hashtags)

            edited_text = st.text_area(
                "Testo del post (puoi modificarlo direttamente qui)",
                value=full_text,
                height=250,
                key="post_text",
            )
            char_count = len(edited_text)
            color = "green" if char_count <= 1300 else "red"
            st.markdown(f"<small style='color:{color}'>{char_count}/1300 caratteri</small>", unsafe_allow_html=True)

            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Approva post", type="primary", use_container_width=True):
                    st.session_state.approved_post = edited_text
                    st.session_state.post_skipped = False
                    st.success("Post approvato!")
            with col2:
                if st.button("⏭️ Salta post", use_container_width=True):
                    st.session_state.approved_post = None
                    st.session_state.post_skipped = True
                    st.info("Post saltato.")

        # ----------------------------------------------------------------
        # COMMENTI
        # ----------------------------------------------------------------
        if plan.comments:
            st.subheader(f"💬 Commenti ({len(plan.comments)})")
            for i, comment in enumerate(plan.comments):
                with st.expander(f"Commento su post di **{comment.post_author}**", expanded=i == 0):
                    st.caption(f"Post: _{comment.post_text_snippet}_")
                    st.write(comment.comment_text)
                    st.session_state.approved_comments[i] = st.checkbox(
                        "Approva questo commento",
                        value=st.session_state.approved_comments[i],
                        key=f"comment_{i}",
                    )

        # ----------------------------------------------------------------
        # REAZIONI
        # ----------------------------------------------------------------
        if plan.reactions:
            st.subheader(f"👍 Reazioni ({len(plan.reactions)})")
            for i, reaction in enumerate(plan.reactions):
                with st.expander(f"{'🔁 Diffondi' if reaction.reaction_type == 'repost' else '👍 Consiglia'} post di **{reaction.post_author}**", expanded=False):
                    st.caption(f"_{reaction.post_text_snippet}_")
                    if reaction.motivation:
                        st.info(reaction.motivation)
                    st.session_state.approved_reactions[i] = st.checkbox(
                        "Approva questa reazione",
                        value=st.session_state.approved_reactions[i],
                        key=f"reaction_{i}",
                    )

        # ----------------------------------------------------------------
        # CONNESSIONI
        # ----------------------------------------------------------------
        if plan.connections:
            st.subheader(f"🤝 Connessioni ({len(plan.connections)})")
            for i, conn in enumerate(plan.connections):
                with st.expander(f"**{conn.full_name}** — {conn.headline}", expanded=False):
                    if conn.motivation:
                        st.info(conn.motivation)
                    st.caption(conn.profile_url)
                    st.session_state.approved_connections[i] = st.checkbox(
                        "Approva questa connessione",
                        value=st.session_state.approved_connections[i],
                        key=f"connection_{i}",
                    )

        # ----------------------------------------------------------------
        # Bottone esecuzione
        # ----------------------------------------------------------------
        st.divider()
        n_approved = (
            (1 if st.session_state.approved_post else 0)
            + sum(st.session_state.approved_comments)
            + sum(st.session_state.approved_reactions)
            + sum(st.session_state.approved_connections)
        )

        if n_approved == 0 and st.session_state.post_skipped is not False:
            st.warning("Nessuna azione approvata. Approva almeno un'azione per procedere.")
        else:
            if st.button(f"🚀 Esegui {n_approved} azioni approvate", type="primary", use_container_width=True, disabled=(n_approved == 0)):
                st.session_state.phase = "executing"
                st.rerun()

# ---------------------------------------------------------------------------
# FASE 4 — EXECUTING
# ---------------------------------------------------------------------------
elif st.session_state.phase == "executing":
    plan = st.session_state.plan
    st.subheader("⚙️ Esecuzione in corso...")

    log_area = st.empty()
    progress = st.progress(0)
    log = []

    approved_post_text = st.session_state.approved_post
    approved_comments = [c for i, c in enumerate(plan.comments) if st.session_state.approved_comments[i]]
    approved_reactions = [r for i, r in enumerate(plan.reactions) if st.session_state.approved_reactions[i]]
    approved_connections = [c for i, c in enumerate(plan.connections) if st.session_state.approved_connections[i]]

    total = (
        (1 if approved_post_text else 0)
        + len(approved_comments)
        + len(approved_reactions)
        + len(approved_connections)
    )
    done = 0

    def update(msg, ok=True):
        nonlocal done
        icon = "✅" if ok else "❌"
        log.append(f"{icon} {msg}")
        log_area.text("\n".join(log))
        done += 1
        progress.progress(done / max(total, 1))

    if total == 0:
        st.info("Nessuna azione da eseguire.")
        st.session_state.phase = "done"
        st.rerun()
    else:
        try:
            db_path = settings.data_dir / "activity_log.db"
            tracker = ActivityTracker(db_path)
            tracker.init_db()

            with BrowserSession(settings) as session:
                if approved_post_text:
                    try:
                        post_pub = PostPublisher(session)
                        # Override content with edited text
                        post = plan.post_draft
                        post.content = approved_post_text
                        urn = post_pub.publish(post)
                        tracker.mark_post_published(post.id, urn)
                        update("Post pubblicato su LinkedIn")
                    except Exception as e:
                        update(f"Errore pubblicazione post: {e}", ok=False)
                    session.random_delay()

                for comment in approved_comments:
                    try:
                        comment_pub = CommentPublisher(session)
                        ok = comment_pub.post_comment(comment)
                        if ok:
                            tracker.mark_comment_published(comment.id)
                            update(f"Commento pubblicato su post di {comment.post_author}")
                        else:
                            update(f"Errore commento su {comment.post_author}", ok=False)
                    except Exception as e:
                        update(f"Errore commento: {e}", ok=False)
                    session.random_delay()

                for reaction in approved_reactions:
                    try:
                        reaction_pub = ReactionPublisher(session)
                        ok = reaction_pub.react(reaction)
                        if ok:
                            tracker.mark_reaction_done(reaction.id)
                            update(f"Reazione applicata su post di {reaction.post_author}")
                        else:
                            update(f"Errore reazione su {reaction.post_author}", ok=False)
                    except Exception as e:
                        update(f"Errore reazione: {e}", ok=False)
                    session.random_delay()

                for conn in approved_connections:
                    try:
                        session.page.goto(conn.profile_url, timeout=20000)
                        session.page.wait_for_load_state("networkidle", timeout=15000)
                        session.random_delay()
                        connect_btn = session.page.locator(
                            "button[aria-label*='Collegati'], button[aria-label*='Connect']"
                        ).first
                        connect_btn.click()
                        session.page.wait_for_timeout(2000)
                        try:
                            send_btn = session.page.locator(
                                "button[aria-label*='Invia ora'], button[aria-label*='Send now']"
                            ).first
                            send_btn.click()
                        except Exception:
                            pass
                        tracker.mark_connection_sent(conn.id)
                        update(f"Richiesta connessione inviata a {conn.full_name}")
                    except Exception as e:
                        update(f"Errore connessione {conn.full_name}: {e}", ok=False)
                    session.random_delay()

            st.session_state.execution_log = log
            st.session_state.phase = "done"
            st.rerun()

        except Exception as e:
            st.error(f"Errore durante l'esecuzione: {e}")
            st.session_state.execution_log = log
            st.session_state.phase = "done"
            st.rerun()

# ---------------------------------------------------------------------------
# FASE 5 — DONE
# ---------------------------------------------------------------------------
elif st.session_state.phase == "done":
    st.subheader("✅ Completato!")

    log = st.session_state.execution_log
    if log:
        st.write("**Riepilogo azioni:**")
        for line in log:
            st.write(line)
    else:
        st.info("Nessuna azione eseguita (tutte saltate o modalità demo).")

    st.divider()
    if st.button("🔄 Inizia una nuova sessione", type="primary", use_container_width=True):
        st.session_state.phase = "home"
        st.session_state.plan = None
        st.session_state.approved_post = None
        st.session_state.post_skipped = False
        st.session_state.approved_comments = []
        st.session_state.approved_reactions = []
        st.session_state.approved_connections = []
        st.session_state.execution_log = []
        st.rerun()
