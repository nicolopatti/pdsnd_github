"""
LinkedIn Growth Agent — Interfaccia web (Streamlit)
Avvio: streamlit run linkedin_agent/scripts/app.py
"""
from __future__ import annotations
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

# ── Settings ──────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _load():
    try:
        return load_settings(), None
    except Exception as e:
        return None, str(e)

settings, err = _load()

# ── Session state ─────────────────────────────────────────────────────────────
for k, v in {
    "phase": "home", "plan": None, "dry_run": False,
    "approved_post": None, "post_skipped": False,
    "approved_comments": [], "approved_reactions": [], "approved_connections": [],
    "exec_log": [],
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_user = st.columns([3, 1])
with col_title:
    st.title("💼 LinkedIn Growth Agent")
    if settings:
        st.caption(f"Gestione account: **{settings.linkedin_email}** · Niche: fondi europei & PNRR")
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

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_piano, tab_profilo, tab_stats = st.tabs(["📋 Piano Giornaliero", "🔍 Analisi Profilo", "📊 Statistiche"])

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — PIANO GIORNALIERO
# ════════════════════════════════════════════════════════════════════════════
with tab_piano:

    # Sidebar-like controls in an expander
    with st.expander("⚙️ Opzioni", expanded=False):
        dry_run = st.checkbox("Modalità demo (dati finti, nessuna chiamata API)", value=False)
        st.session_state.dry_run = dry_run

    # ── PHASE: HOME ──────────────────────────────────────────────────────────
    if st.session_state.phase == "home":
        st.markdown("""
        <div class='card'>
          <h4 style='margin:0 0 8px;color:#0077B5'>Come funziona</h4>
          <ol style='margin:0;padding-left:18px;line-height:1.8'>
            <li><b>Genera piano</b> — l'AI analizza la tua nicchia e prepara post, commenti, reazioni e connessioni</li>
            <li><b>Rivedi ogni azione</b> — vedi il contenuto e la spiegazione strategica, approva o salta</li>
            <li><b>Esegui</b> — l'agente pubblica automaticamente su LinkedIn ciò che hai approvato</li>
          </ol>
        </div>
        """, unsafe_allow_html=True)

        if st.button("📋 Genera Piano Giornaliero", type="primary", use_container_width=True):
            st.session_state.phase = "planning"
            st.rerun()

    # ── PHASE: PLANNING ──────────────────────────────────────────────────────
    elif st.session_state.phase == "planning":
        with st.spinner("Generazione piano in corso — Gemini AI sta analizzando la tua nicchia..."):
            db_path = settings.data_dir / "activity_log.db"
            tracker = ActivityTracker(db_path)
            tracker.init_db()
            ai = AIClient(api_key=settings.gemini_api_key)
            content_gen = ContentGenerator(settings, ai)
            advisor = StrategyAdvisor(settings, ai, tracker)

            linkedin_reader = engagement = network = None
            if not st.session_state.dry_run:
                try:
                    linkedin_reader = LinkedInReader(settings.linkedin_email, settings.linkedin_password, li_at=settings.linkedin_li_at)
                    engagement = EngagementModule(settings, ai, linkedin_reader, tracker)
                    network = NetworkModule(settings, ai, linkedin_reader, tracker)
                except Exception as e:
                    st.warning(f"⚠️ Login LinkedIn non riuscito: {e}. Continuo in modalità solo-contenuto.")

            class _SE:
                def get_daily_engagement_queue(self, limit=None): return []
                def get_reaction_queue(self, limit=None): return []
            class _SN:
                def get_connection_queue(self, limit=None): return []

            scheduler = DailyScheduler(settings, tracker, content_gen, engagement or _SE(), network or _SN())
            plan = scheduler.build_daily_plan(dry_run=st.session_state.dry_run)
            st.session_state.plan = plan
            st.session_state.approved_comments = [True] * len(plan.comments)
            st.session_state.approved_reactions = [True] * len(plan.reactions)
            st.session_state.approved_connections = [True] * len(plan.connections)
            st.session_state.phase = "reviewing"
            st.rerun()

    # ── PHASE: REVIEWING ─────────────────────────────────────────────────────
    elif st.session_state.phase == "reviewing":
        plan = st.session_state.plan

        if plan.notes:
            for note in plan.notes:
                st.info(f"ℹ️ {note}")

        if plan.total_actions == 0:
            st.warning("Nessuna attività pianificata per oggi.")
            if st.button("← Torna alla home"):
                st.session_state.phase = "home"
                st.rerun()
        else:
            # ── POST ──────────────────────────────────────────────────────────
            if plan.post_draft:
                post = plan.post_draft
                st.markdown("### 📝 Post da pubblicare")
                st.markdown(f"""
                <div class='card'>
                  <div>
                    <span class='pill'>{post.pillar}</span>
                    <span class='pill'>{post.format_type}</span>
                  </div>
                  <br>
                </div>
                """, unsafe_allow_html=True)

                edited = st.text_area("Testo del post (modificabile)", value=post.content + "\n\n" + " ".join(post.hashtags), height=220, key="post_text")
                chars = len(edited)
                bar_pct = min(chars / 1300, 1.0)
                color = "#27ae60" if chars <= 1300 else "#e74c3c"
                st.markdown(f"""
                <div style='display:flex;align-items:center;gap:10px;margin-bottom:8px'>
                  <div class='score-bar' style='flex:1'><div class='score-fill' style='width:{bar_pct*100:.0f}%;background:{color}'></div></div>
                  <span style='font-size:0.82em;color:{color};white-space:nowrap'>{chars}/1300 caratteri</span>
                </div>
                """, unsafe_allow_html=True)

                # Why this post
                _format_why = {
                    "guida_pratica": "Le guide pratiche step-by-step ottengono **2× più salvataggi** rispetto ai post di opinione nel B2B (fonte: LinkedIn Internal Data 2024). I lettori le conservano come riferimento futuro.",
                    "sintesi_bando": "Le sintesi di bandi con scadenza imminente generano **alta urgency** e vengono condivise da colleghi del settore. Posizionano l'autore come punto di riferimento per le novità.",
                    "caso_studio": "I casi studio con numeri reali (es. €X ottenuti) ottengono **3× più commenti** perché stimolano domande concrete e confronti con esperienze proprie.",
                    "checklist": "Le checklist sono i contenuti più **salvati su LinkedIn B2B**: forniscono valore immediato e vengono consultate ripetutamente, generando impression organiche nel tempo.",
                    "errori_comuni": "I post sugli errori da evitare attivano la **loss aversion** cognitiva — le persone reagiscono più agli errori che ai consigli positivi. Alto engagement garantito.",
                    "dato_sorprendente": "I post con dati inaspettati come hook ottengono **+34% di click sul 'vedi altro'** (Richard van der Blom, LinkedIn Algorithm Report 2024). Il contrasto con le aspettative cattura l'attenzione.",
                    "risorsa": "Le liste di risorse gratuite sono tra i contenuti più **condivisi organicamente**: chi le condivide aggiunge valore al proprio network, moltiplicando la tua visibilità.",
                }
                why = _format_why.get(post.format_type, "Questo formato è stato selezionato in base ai pilastri della tua strategia di contenuto e al peso configurato.")
                st.markdown(f"<div class='why-box'>💡 <b>Perché questo post?</b><br>{why}</div>", unsafe_allow_html=True)

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ Approva post", type="primary", use_container_width=True):
                        st.session_state.approved_post = edited
                        st.success("Approvato!")
                with col2:
                    if st.button("⏭️ Salta post", use_container_width=True):
                        st.session_state.approved_post = None
                        st.session_state.post_skipped = True
                        st.info("Saltato.")

                st.divider()

            # ── COMMENTI ──────────────────────────────────────────────────────
            if plan.comments:
                st.markdown("### 💬 Commenti suggeriti")
                for i, c in enumerate(plan.comments):
                    score_pct = int(c.relevance_score * 100)
                    with st.expander(f"**{c.post_author}** — rilevanza {score_pct}%", expanded=(i == 0)):
                        st.markdown(f"<div class='card card-yellow'><b>Post originale:</b><br><i>\"{c.post_text_snippet}\"</i></div>", unsafe_allow_html=True)
                        st.markdown(f"**Il tuo commento proposto:**\n\n{c.comment_text}")
                        st.markdown(f"""<div class='why-box'>💡 <b>Perché commentare?</b><br>
                        Commentare post con rilevanza >{score_pct-10}% nel tuo niche aumenta la tua visibilità verso i follower di <b>{c.post_author}</b>.
                        I commenti di valore (con dati o insight specifici) vengono segnalati dall'algoritmo LinkedIn come contenuto esperto,
                        ampliando il tuo reach organico senza pubblicare un post.</div>""", unsafe_allow_html=True)
                        st.session_state.approved_comments[i] = st.checkbox("✅ Approva commento", value=st.session_state.approved_comments[i], key=f"c_{i}")

                st.divider()

            # ── REAZIONI ──────────────────────────────────────────────────────
            if plan.reactions:
                st.markdown("### 👍 Reazioni suggerite")
                for i, r in enumerate(plan.reactions):
                    icon = "🔁 Diffondi" if r.reaction_type == "repost" else "👍 Consiglia"
                    with st.expander(f"{icon} — post di **{r.post_author}**", expanded=False):
                        st.markdown(f"<div class='card card-purple'><i>\"{r.post_text_snippet}\"</i></div>", unsafe_allow_html=True)
                        if r.motivation:
                            st.markdown(f"<div class='why-box'>💡 <b>Perché questa reazione?</b><br>{r.motivation}</div>", unsafe_allow_html=True)
                        else:
                            action = "Diffondere" if r.reaction_type == "repost" else "Consigliare"
                            st.markdown(f"""<div class='why-box'>💡 <b>Perché questa reazione?</b><br>
                            {action} un post rilevante nel tuo niche segnala all'algoritmo LinkedIn che sei attivo nel settore.
                            Aumenta la tua visibilità verso i follower dell'autore e costruisce relazioni prima ancora di una richiesta di connessione.</div>""", unsafe_allow_html=True)
                        st.session_state.approved_reactions[i] = st.checkbox("✅ Approva reazione", value=st.session_state.approved_reactions[i], key=f"r_{i}")

                st.divider()

            # ── CONNESSIONI ───────────────────────────────────────────────────
            if plan.connections:
                st.markdown("### 🤝 Connessioni suggerite")
                for i, conn in enumerate(plan.connections):
                    score_pct = int(conn.relevance_score * 100)
                    with st.expander(f"**{conn.full_name}** · {conn.headline} — {score_pct}% match", expanded=False):
                        st.markdown(f"<div class='card card-green'>🔗 <a href='{conn.profile_url}' target='_blank'>{conn.profile_url}</a></div>", unsafe_allow_html=True)
                        if conn.motivation:
                            st.markdown(f"<div class='why-box'>💡 <b>Perché connettersi?</b><br>{conn.motivation}</div>", unsafe_allow_html=True)
                        st.session_state.approved_connections[i] = st.checkbox("✅ Approva connessione", value=st.session_state.approved_connections[i], key=f"k_{i}")

                st.divider()

            # ── EXECUTE BUTTON ────────────────────────────────────────────────
            n = (
                (1 if st.session_state.approved_post else 0)
                + sum(st.session_state.approved_comments)
                + sum(st.session_state.approved_reactions)
                + sum(st.session_state.approved_connections)
            )
            col_exec, col_back = st.columns([2, 1])
            with col_exec:
                if st.button(f"🚀 Esegui {n} azioni approvate", type="primary", use_container_width=True, disabled=(n == 0)):
                    st.session_state.phase = "executing"
                    st.rerun()
            with col_back:
                if st.button("← Ricomincia", use_container_width=True):
                    st.session_state.phase = "home"
                    st.rerun()

    # ── PHASE: EXECUTING ─────────────────────────────────────────────────────
    elif st.session_state.phase == "executing":
        plan = st.session_state.plan
        st.markdown("### ⚙️ Esecuzione in corso")
        log_slot = st.empty()
        prog = st.progress(0)
        log = []

        ap = st.session_state.approved_post
        ac = [c for i, c in enumerate(plan.comments) if st.session_state.approved_comments[i]]
        ar = [r for i, r in enumerate(plan.reactions) if st.session_state.approved_reactions[i]]
        ak = [k for i, k in enumerate(plan.connections) if st.session_state.approved_connections[i]]
        total = (1 if ap else 0) + len(ac) + len(ar) + len(ak)
        done = [0]

        def _upd(msg, ok=True):
            log.append(("✅" if ok else "❌") + " " + msg)
            log_slot.markdown("\n\n".join(log))
            done[0] += 1
            prog.progress(done[0] / max(total, 1))

        try:
            db_path = settings.data_dir / "activity_log.db"
            tracker = ActivityTracker(db_path)
            tracker.init_db()
            with BrowserSession(settings) as session:
                if ap:
                    try:
                        plan.post_draft.content = ap
                        urn = PostPublisher(session).publish(plan.post_draft)
                        tracker.mark_post_published(plan.post_draft.id, urn)
                        _upd("Post pubblicato su LinkedIn")
                    except Exception as e:
                        _upd(f"Errore post: {e}", False)
                    session.random_delay()
                for c in ac:
                    try:
                        ok = CommentPublisher(session).post_comment(c)
                        if ok:
                            tracker.mark_comment_published(c.id)
                            _upd(f"Commento su post di {c.post_author}")
                        else:
                            _upd(f"Errore commento su {c.post_author}", False)
                    except Exception as e:
                        _upd(f"Errore: {e}", False)
                    session.random_delay()
                for r in ar:
                    try:
                        ok = ReactionPublisher(session).react(r)
                        if ok:
                            tracker.mark_reaction_done(r.id)
                            _upd(f"Reazione su post di {r.post_author}")
                        else:
                            _upd(f"Errore reazione su {r.post_author}", False)
                    except Exception as e:
                        _upd(f"Errore: {e}", False)
                    session.random_delay()
                for k in ak:
                    try:
                        session.page.goto(k.profile_url, timeout=20000)
                        session.page.wait_for_load_state("networkidle", timeout=15000)
                        session.random_delay()
                        session.page.locator("button[aria-label*='Collegati'], button[aria-label*='Connect']").first.click()
                        session.page.wait_for_timeout(2000)
                        try:
                            session.page.locator("button[aria-label*='Invia ora'], button[aria-label*='Send now']").first.click()
                        except Exception:
                            pass
                        tracker.mark_connection_sent(k.id)
                        _upd(f"Connessione inviata a {k.full_name}")
                    except Exception as e:
                        _upd(f"Errore connessione {k.full_name}: {e}", False)
                    session.random_delay()
        except Exception as e:
            _upd(f"Errore sessione browser: {e}", False)

        st.session_state.exec_log = log
        st.session_state.phase = "done"
        st.rerun()

    # ── PHASE: DONE ──────────────────────────────────────────────────────────
    elif st.session_state.phase == "done":
        st.success("✅ Sessione completata!")
        if st.session_state.exec_log:
            st.markdown("**Riepilogo azioni:**")
            for line in st.session_state.exec_log:
                st.write(line)
        else:
            st.info("Nessuna azione eseguita (modalità demo o tutte saltate).")
        if st.button("🔄 Nuova sessione", type="primary"):
            for k in ["phase","plan","approved_post","post_skipped","approved_comments","approved_reactions","approved_connections","exec_log"]:
                st.session_state[k] = "home" if k=="phase" else ([] if "approved" in k or k=="exec_log" else (None if k in ("plan","approved_post") else False))
            st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — ANALISI PROFILO
# ════════════════════════════════════════════════════════════════════════════
with tab_profilo:
    st.markdown("### 🔍 Analisi del tuo posizionamento LinkedIn")
    st.caption("L'AI analizza la tua configurazione e ti dà raccomandazioni concrete per crescere nel niche fondi europei.")

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
        run_analysis = st.button("🔍 Analizza profilo", type="primary", use_container_width=True)

    if run_analysis:
        with st.spinner("Gemini sta analizzando il tuo posizionamento..."):
            db_path = settings.data_dir / "activity_log.db"
            tracker = ActivityTracker(db_path)
            tracker.init_db()
            ai = AIClient(api_key=settings.gemini_api_key)
            advisor = StrategyAdvisor(settings, ai, tracker)
            analysis = advisor.analyze_profile_positioning()
            st.session_state["profile_analysis"] = analysis

    if "profile_analysis" in st.session_state:
        a = st.session_state["profile_analysis"]

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
        report = tracker.export_progress_report()

        # KPI metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Post pubblicati", report["all_time"]["posts_published"], delta=f"{report['this_week']['posts']} questa settimana")
        c2.metric("Commenti postati", report["all_time"]["comments_posted"], delta=f"{report['today']['comments']} oggi")
        c3.metric("Reazioni fatte", report["all_time"]["reactions_done"], delta=f"{report['today']['reactions']} oggi")
        c4.metric("Connessioni inviate", report["all_time"]["connections_sent"], delta=f"{report['today']['connections']} oggi")

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
