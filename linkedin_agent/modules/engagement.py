"""
Discovers relevant LinkedIn posts and generates value-adding comments and reactions.
"""
from __future__ import annotations

from pathlib import Path

from linkedin_agent.config.settings import Settings
from linkedin_agent.core.linkedin_client import FeedPost
from linkedin_agent.core.llm_provider import LLMProvider
from linkedin_agent.modules.context_collector import ContextPost
from linkedin_agent.modules.tracker import ActivityTracker, CommentDraft, ReactionItem

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_REACTION_MOTIVATION_TEMPLATE = (
    "Mettere '{reaction}' su questo post di {author} aumenta la tua visibilità "
    "verso i suoi follower nel niche fondi europei. "
    "Il post tratta: {snippet}"
)


class EngagementModule:
    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        linkedin,
        tracker: ActivityTracker,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._linkedin = linkedin
        self._tracker = tracker
        self._comment_template = (_PROMPTS_DIR / "comment_generation.txt").read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Post discovery
    # ------------------------------------------------------------------

    def discover_posts(self, limit: int = 30) -> list[FeedPost]:
        """
        Fetch recent posts matching niche keywords.
        Filters out: already seen, older than 48h, very low engagement.
        """
        keywords = self._settings.niche.primary_keywords
        raw_posts = self._linkedin.get_feed_posts(keywords=keywords, count=limit * 2)

        filtered: list[FeedPost] = []
        for post in raw_posts:
            if not post.urn:
                continue
            if self._tracker.is_post_seen(post.urn):
                continue
            if post.reaction_count < 5:  # Skip very low engagement posts
                continue
            if not post.text or len(post.text) < 30:
                continue
            filtered.append(post)

        return filtered[:limit]

    def discover_posts_from_snapshot(self, posts: list[ContextPost], limit: int = 30) -> list[FeedPost]:
        filtered: list[FeedPost] = []
        for item in posts:
            post = FeedPost(
                urn=item.urn,
                author_name=item.author_name,
                author_headline=item.author_headline,
                text=item.text,
                reaction_count=item.reaction_count,
                comment_count=item.comment_count,
                url=item.url,
                published_at=item.published_at,
            )
            if self._tracker.is_post_seen(post.urn):
                continue
            if not post.text or len(post.text) < 30:
                continue
            filtered.append(post)
            if len(filtered) >= limit:
                break
        return filtered

    def score_post(self, post: FeedPost) -> float:
        """
        Use the configured LLM to score a post's relevance to the EU funding niche (0.0-1.0).
        Returns 0.0 on error.
        """
        keywords = ", ".join(self._settings.niche.primary_keywords[:8])
        system = (
            "Sei un esperto di fondi europei. Valuta la rilevanza di un post LinkedIn "
            "per il niche 'fondi europei, PNRR, terzo settore, bandi europei'.\n"
            f"Keyword di riferimento: {keywords}\n"
            "Rispondi SOLO con un numero da 0.0 a 1.0. Nessuna spiegazione."
        )
        user = f"POST:\n{post.text[:500]}\n\nAutore headline: {post.author_headline}"
        try:
            raw = self._llm.generate(system, user, max_tokens=10)
            score = float(raw.strip().split()[0])
            return max(0.0, min(1.0, score))
        except (ValueError, IndexError):
            return 0.0

    def generate_comment(self, post: FeedPost) -> CommentDraft:
        """Generate a thoughtful, value-adding comment for a post."""
        tone_map = {
            "formal": "formale e preciso",
            "professional_warm": "professionale ma accessibile",
            "conversational": "colloquiale e diretto",
        }
        tone = tone_map.get(self._settings.user.tone, self._settings.user.tone)

        system_prompt = self._comment_template.format(
            user_name=self._settings.user.name,
            post_author=post.author_name,
            post_author_headline=post.author_headline,
            post_text=post.text[:800],
            tone=tone,
        )
        user_prompt = "Scrivi il commento ora. Solo il testo, nessun prefisso."

        comment_text = self._llm.generate_with_retry(system_prompt, user_prompt, max_tokens=200)

        return CommentDraft(
            post_urn=post.urn,
            post_url=post.url,
            post_author=post.author_name,
            post_text_snippet=post.text[:150],
            comment_text=comment_text.strip(),
            relevance_score=0.0,  # Caller should set this after scoring
        )

    # ------------------------------------------------------------------
    # Queues
    # ------------------------------------------------------------------

    def get_daily_engagement_queue(self, limit: int | None = None, posts_snapshot: list[ContextPost] | None = None) -> list[CommentDraft]:
        """
        Build the day's comment queue: discover posts, score them, generate comments.
        Respects the daily_limits.comments_per_day config.
        """
        max_comments = limit or self._settings.activity.daily_limits.comments_per_day
        already_done = self._tracker.get_daily_comment_count()
        remaining = max_comments - already_done
        if remaining <= 0:
            return []

        posts = (
            self.discover_posts_from_snapshot(posts_snapshot, limit=remaining * 3)
            if posts_snapshot is not None
            else self.discover_posts(limit=remaining * 3)
        )
        scored: list[tuple[float, FeedPost]] = []
        for post in posts:
            score = self.score_post(post)
            self._tracker.mark_post_seen(post.urn, score)
            if score >= 0.5:
                scored.append((score, post))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_posts = [p for _, p in scored[:remaining]]

        comments: list[CommentDraft] = []
        for post in top_posts:
            draft = self.generate_comment(post)
            draft.relevance_score = next(s for s, p in scored if p.urn == post.urn)
            comments.append(draft)

        return comments

    def get_reaction_queue(self, limit: int | None = None, posts_snapshot: list[ContextPost] | None = None) -> list[ReactionItem]:
        """
        Build the day's reaction queue: posts to "consiglia" (like) or "diffondi" (repost).
        Reposting is reserved for very high relevance posts (score >= 0.8).
        """
        max_reactions = limit or self._settings.activity.daily_limits.reactions_per_day
        already_done = self._tracker.get_daily_reaction_count()
        remaining = max_reactions - already_done
        if remaining <= 0:
            return []

        posts = (
            self.discover_posts_from_snapshot(posts_snapshot, limit=remaining * 2)
            if posts_snapshot is not None
            else self.discover_posts(limit=remaining * 2)
        )
        reactions: list[ReactionItem] = []

        for post in posts[:remaining]:
            score = self.score_post(post)
            self._tracker.mark_post_seen(post.urn, score)
            if score < 0.4:
                continue
            reaction_type = "repost" if score >= 0.8 else "like"
            motivation = _REACTION_MOTIVATION_TEMPLATE.format(
                reaction="Diffondi" if reaction_type == "repost" else "Consiglia",
                author=post.author_name,
                snippet=post.text[:100],
            )
            reactions.append(
                ReactionItem(
                    post_urn=post.urn,
                    post_url=post.url,
                    post_author=post.author_name,
                    post_text_snippet=post.text[:150],
                    reaction_type=reaction_type,
                    motivation=motivation,
                )
            )
            if len(reactions) >= remaining:
                break

        return reactions
