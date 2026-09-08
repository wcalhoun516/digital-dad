"""Tests for training/prepare.py — the Geo LLM dataset builder (plan 0008, step 26a).

Exercises the pure shaping/splitting logic on small fixtures (no corpus, no
conductor): instruction-record shaping, the #25-eval-overlap mapping, and the
deterministic train/held-out partition.
"""

import json
import re

from training import prepare
from training.prepare import (
    TASK_SHAPES,
    build_instruct_record,
    build_passage_record,
    build_passage_records,
    chunk_body,
    eval_grounded_slugs,
    passage_budget_chars,
    split_articles,
)


def _record_chars(record: dict) -> int:
    return sum(len(m["content"]) for m in record["messages"])


def _paragraph(n_sentences: int, marker: str = "x") -> str:
    return " ".join(f"Sentence {i} about {marker}." for i in range(n_sentences))


class TestBuildInstructRecord:
    def test_has_system_user_assistant_messages(self):
        rec = build_instruct_record("Why The Fed Prints Alpha", "The body.")
        roles = [m["role"] for m in rec["messages"]]
        assert roles == ["system", "user", "assistant"]

    def test_user_prompt_derives_topic_from_title(self):
        # leading "Why" + trailing "?" are stripped by _article_to_topic
        rec = build_instruct_record("Why Is Inflation Real?", "Body text here.")
        assert rec["messages"][1]["content"] == "Write an analysis of Is Inflation Real."

    def test_assistant_content_is_the_body(self):
        rec = build_instruct_record("Some Title", "The full article body.")
        assert rec["messages"][2]["content"] == "The full article body."


class TestChunkBody:
    """Plan 0009 step 1: article bodies become passage-sized chunks that fit the
    fine-tune window, split on paragraph boundaries and never mid-sentence.
    """

    def test_short_body_is_one_chunk(self):
        body = _paragraph(3)
        assert chunk_body(body, max_chars=1000) == [body]

    def test_no_chunk_exceeds_the_budget(self):
        body = "\n\n".join(_paragraph(6, marker=f"topic{i}") for i in range(12))
        chunks = chunk_body(body, max_chars=400)
        assert chunks
        assert all(len(c) <= 400 for c in chunks)

    def test_splits_on_paragraph_boundaries(self):
        # each paragraph fits alone, so no chunk may contain a partial paragraph
        paragraphs = [_paragraph(4, marker=f"topic{i}") for i in range(8)]
        chunks = chunk_body("\n\n".join(paragraphs), max_chars=300)
        emitted = [p for c in chunks for p in c.split("\n\n")]
        assert emitted == paragraphs

    def test_packs_multiple_paragraphs_into_one_chunk(self):
        paragraphs = [_paragraph(2, marker=f"topic{i}") for i in range(6)]
        chunks = chunk_body("\n\n".join(paragraphs), max_chars=2000)
        assert len(chunks) == 1

    def test_never_ends_a_chunk_mid_sentence(self):
        body = "\n\n".join(_paragraph(5, marker=f"topic{i}") for i in range(10))
        for chunk in chunk_body(body, max_chars=350):
            assert chunk.endswith("."), chunk

    def test_preserves_every_sentence_exactly_once(self):
        body = "\n\n".join(_paragraph(5, marker=f"topic{i}") for i in range(10))
        chunks = chunk_body(body, max_chars=350)
        rejoined = " ".join(" ".join(c.split()) for c in chunks)
        assert rejoined == " ".join(body.split())

    def test_oversized_paragraph_is_split_at_a_sentence_boundary(self):
        # one paragraph, far over budget: it must still be cut between sentences
        body = _paragraph(40)
        chunks = chunk_body(body, max_chars=300)
        assert len(chunks) > 1
        assert all(len(c) <= 300 for c in chunks)
        assert all(c.endswith(".") for c in chunks)

    def test_blank_body_yields_no_chunks(self):
        assert chunk_body("   \n\n  ", max_chars=500) == []


class TestBoilerplateParagraphs:
    """His Forbes footer — author bio, contact line, book blurb, and Forbes' own
    comment-policy text — repeats verbatim across scores of articles. Truncated
    article-level records never reached it; passage records do, and identical text
    on both sides of the split also registers as leakage (plan 0009 step 1).
    """

    BIO = "My second career: In 2003, I joined Stevens Institute of Technology."
    ONE_OFF = "A paragraph that belongs to a single argument."

    def _bodies(self):
        return [
            f"Body one opens here.\n\n{self.BIO}",
            f"Body two opens here.\n\n{self.BIO}",
            f"Body three opens here.\n\n{self.BIO}",
            f"Body four opens here.\n\n{self.ONE_OFF}",
            f"Body five opens here.\n\n{self.ONE_OFF}",
        ]

    def test_flags_a_paragraph_repeated_across_enough_articles(self):
        assert self.BIO in prepare.boilerplate_paragraphs(self._bodies())

    def test_leaves_a_paragraph_shared_by_only_two_articles(self):
        # two articles can legitimately reuse a line; three is a footer
        assert self.ONE_OFF not in prepare.boilerplate_paragraphs(self._bodies())

    def test_threshold_is_configurable(self):
        assert self.ONE_OFF in prepare.boilerplate_paragraphs(self._bodies(), min_articles=2)

    def test_repeats_within_one_article_are_not_boilerplate(self):
        bodies = [f"{self.BIO}\n\n{self.BIO}\n\n{self.BIO}"]
        assert prepare.boilerplate_paragraphs(bodies) == set()

    def test_strip_removes_the_boilerplate_and_keeps_the_argument(self):
        body = f"Opening argument.\n\n{self.BIO}\n\nClosing argument."
        stripped = prepare.strip_boilerplate(body, {self.BIO})
        assert self.BIO not in stripped
        assert stripped == "Opening argument.\n\nClosing argument."

    def test_strip_of_an_all_boilerplate_body_is_empty(self):
        assert prepare.strip_boilerplate(self.BIO, {self.BIO}) == ""


class TestBuildPassageRecord:
    """One passage, one task shape. The shape is recorded so the voice eval can
    slice results by it (plan 0009 step 1)."""

    PASSAGE = "The first claim is bold. The second sentence qualifies it. A third lands."

    def test_every_shape_produces_a_well_formed_chat_record(self):
        for shape in TASK_SHAPES:
            rec = build_passage_record("A Title", self.PASSAGE, shape)
            roles = [m["role"] for m in rec["messages"]]
            assert roles == ["system", "user", "assistant"], shape
            assert all(m["content"].strip() for m in rec["messages"]), shape

    def test_record_carries_its_shape(self):
        for shape in TASK_SHAPES:
            assert build_passage_record("A Title", self.PASSAGE, shape)["shape"] == shape

    def test_write_on_topic_completion_is_the_whole_passage(self):
        rec = build_passage_record("Why Inflation Persists?", self.PASSAGE, "write-on-topic")
        assert rec["messages"][2]["content"] == self.PASSAGE
        assert "Inflation Persists" in rec["messages"][1]["content"]

    def test_continue_passage_puts_the_opening_in_the_prompt(self):
        rec = build_passage_record("A Title", self.PASSAGE, "continue-passage")
        user, assistant = rec["messages"][1]["content"], rec["messages"][2]["content"]
        assert "The first claim is bold." in user
        assert assistant == "The second sentence qualifies it. A third lands."

    def test_respond_to_claim_quotes_the_claim_and_answers_it(self):
        rec = build_passage_record("A Title", self.PASSAGE, "respond-to-claim")
        user, assistant = rec["messages"][1]["content"], rec["messages"][2]["content"]
        assert "The first claim is bold." in user
        assert "The first claim is bold." not in assistant

    def test_split_shapes_lose_no_text_from_the_passage(self):
        for shape in ("continue-passage", "respond-to-claim"):
            rec = build_passage_record("A Title", self.PASSAGE, shape)
            user, assistant = rec["messages"][1]["content"], rec["messages"][2]["content"]
            assert self.PASSAGE.split(". ")[0] in user
            assert assistant in self.PASSAGE

    def test_single_sentence_passage_falls_back_to_write_on_topic(self):
        # nothing to continue from, so the split shapes would emit an empty turn
        rec = build_passage_record("A Title", "One lonely sentence.", "continue-passage")
        assert rec["shape"] == "write-on-topic"
        assert rec["messages"][2]["content"] == "One lonely sentence."

    def test_unknown_shape_is_rejected(self):
        try:
            build_passage_record("A Title", self.PASSAGE, "freestyle")
        except ValueError:
            return
        raise AssertionError("expected ValueError for an unknown task shape")


class TestBuildPassageRecords:
    """A whole article body becomes several in-budget records — the fix for D15's
    100%-over-budget dataset."""

    def _body(self, n_paragraphs=14):
        return "\n\n".join(_paragraph(8, marker=f"topic{i}") for i in range(n_paragraphs))

    def test_every_record_fits_the_sequence_budget(self):
        budget = passage_budget_chars()
        records = build_passage_records("A Title", self._body(60), slug="a-title")
        assert records
        assert all(_record_chars(r) <= budget for r in records)

    def test_a_long_body_yields_several_records(self):
        records = build_passage_records("A Title", self._body(60), slug="a-title")
        assert len(records) > 1

    def test_the_whole_body_reaches_the_model(self):
        body = self._body(60)
        records = build_passage_records("A Title", body, slug="a-title")
        seen = " ".join(
            " ".join((r["messages"][1]["content"] + " " + r["messages"][2]["content"]).split())
            for r in records
        )
        for sentence in {s.strip() for s in body.replace("\n\n", " ").split(". ") if s.strip()}:
            assert sentence.rstrip(".") in seen

    def test_task_shapes_vary_across_an_article(self):
        records = build_passage_records("A Title", self._body(60), slug="a-title")
        assert len({r["shape"] for r in records}) > 1

    def test_is_deterministic(self):
        body = self._body()
        assert build_passage_records("A Title", body, slug="s") == build_passage_records(
            "A Title", body, slug="s"
        )

    def test_shape_rotation_differs_between_articles(self):
        body = self._body()
        first = [r["shape"] for r in build_passage_records("T", body, slug="alpha")]
        second = [r["shape"] for r in build_passage_records("T", body, slug="beta-two")]
        assert first != second

    def test_empty_body_yields_no_records(self):
        assert build_passage_records("A Title", "   ", slug="s") == []


class TestEvalGroundedSlugs:
    def _articles(self):
        return [
            {"slug": "inflation-still-exist", "title": "Does Inflation Still Exist?"},
            {
                "slug": "fed-prints-alpha",
                "title": "The Fed Doesn’t Just Print Money, It Also Prints Alpha",
            },
            {"slug": "unrelated-piece", "title": "A Totally Different Subject"},
        ]

    def test_matches_article_whose_title_appears_in_a_topic_hint(self):
        questions = [{"question": "Does inflation still exist?", "topic_hint": "Does Inflation Still Exist? (2020)"}]  # noqa: E501
        assert eval_grounded_slugs(questions, self._articles()) == {"inflation-still-exist"}

    def test_leaves_unreferenced_articles_out(self):
        questions = [{"question": "Does inflation still exist?", "topic_hint": "Does Inflation Still Exist? (2020)"}]  # noqa: E501
        assert "unrelated-piece" not in eval_grounded_slugs(questions, self._articles())

    def test_robust_to_typographic_punctuation(self):
        # article title carries a curly apostrophe; the hint uses a straight one
        hint = "The Fed Doesn't Just Print Money, It Also Prints Alpha (2020)"
        questions = [{"question": "Fed alpha?", "topic_hint": hint}]
        assert "fed-prints-alpha" in eval_grounded_slugs(questions, self._articles())

    def test_no_questions_yields_empty_set(self):
        assert eval_grounded_slugs([], self._articles()) == set()


class TestSplitArticles:
    def test_excluded_slugs_land_in_neither_split(self):
        slugs = ["a", "b", "c", "d"]
        train, heldout = split_articles(slugs, excluded={"b"})
        assert "b" not in train
        assert "b" not in heldout

    def test_partition_is_deterministic(self):
        slugs = [f"slug-{i}" for i in range(50)]
        first = split_articles(slugs)
        second = split_articles(slugs)
        assert first == second

    def test_train_and_heldout_are_disjoint_and_cover_remaining(self):
        slugs = [f"slug-{i}" for i in range(50)]
        excluded = {"slug-0", "slug-1"}
        train, heldout = split_articles(slugs, excluded=excluded)
        assert set(train).isdisjoint(heldout)
        assert set(train) | set(heldout) == set(slugs) - excluded

    def test_zero_fraction_puts_everything_in_train(self):
        slugs = [f"slug-{i}" for i in range(20)]
        train, heldout = split_articles(slugs, heldout_frac=0.0)
        assert heldout == []
        assert set(train) == set(slugs)

    def test_heldout_excludes_eval_grounded_slugs(self):
        articles = [
            {"slug": "inflation-still-exist", "title": "Does Inflation Still Exist?"},
            {"slug": "other-1", "title": "Some Other Piece One"},
            {"slug": "other-2", "title": "Some Other Piece Two"},
        ]
        questions = [{"question": "q", "topic_hint": "Does Inflation Still Exist? (2020)"}]
        excluded = eval_grounded_slugs(questions, articles)
        train, heldout = split_articles([a["slug"] for a in articles], excluded=excluded)
        assert "inflation-still-exist" not in heldout
        assert "inflation-still-exist" not in train


class TestRunEmitsPassageLevelSplits:
    """`run()` writes the fine-tune's train/held-out splits at **passage** level
    (so 100% of each body fits the window) while the *partition* stays at
    **article** level — every chunk of an article lands on one side or the other,
    never both, or the voice eval leaks (plan 0009 step 1).
    """

    N_ARTICLES = 12

    def _corpus(self, tmp_path, monkeypatch, footer=""):
        raw = tmp_path / "raw"
        raw.mkdir()
        entries = []
        for i in range(self.N_ARTICLES):
            slug = f"article-{i}"
            # distinctive per-article token so a straddling chunk is detectable
            body = "\n\n".join(
                " ".join(f"Sentence {s} about marker{i}." for s in range(8)) for _ in range(40)
            )
            if footer:  # the same trailing paragraph on every article
                body = f"{body}\n\n{footer}"
            title, date = f"Title Number {i}", f"2021-01-{i + 1:02d}"
            (raw / f"{slug}.json").write_text(
                json.dumps({"title": title, "body": body, "date": date})
            )
            entries.append({
                "slug": slug, "url": f"https://f.com/{slug}/", "file": f"raw/{slug}.json",
                "title": title, "date": date, "word_count": 1000,
            })
        (tmp_path / "manifest.json").write_text(
            json.dumps({"total_articles": len(entries), "articles": entries})
        )
        monkeypatch.setattr(prepare, "DATA_DIR", tmp_path)
        monkeypatch.setattr(prepare, "MANIFEST_PATH", tmp_path / "manifest.json")
        monkeypatch.setattr(prepare, "TRAINING_DIR", tmp_path / "training")
        monkeypatch.setattr(prepare, "LINGUISTICS_PATH", tmp_path / "absent.json")
        monkeypatch.setattr(prepare, "EVAL_QUESTIONS_PATH", tmp_path / "absent.json")
        return tmp_path / "training"

    def _read(self, out, name):
        return [json.loads(x) for x in (out / name).read_text().splitlines() if x.strip()]

    def _markers(self, records):
        return {
            m.group()
            for r in records
            for msg in r["messages"]
            if (m := re.search(r"marker\d+", msg["content"]))
        }

    def test_splits_hold_more_records_than_articles(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch)
        prepare.run()
        n_records = len(self._read(out, "train.jsonl")) + len(self._read(out, "heldout.jsonl"))
        assert n_records > self.N_ARTICLES

    def test_both_sides_of_the_split_are_populated(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch)
        prepare.run()
        assert self._read(out, "train.jsonl")
        assert self._read(out, "heldout.jsonl")

    def test_no_articles_passages_straddle_the_split(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch)
        prepare.run()
        train_markers = self._markers(self._read(out, "train.jsonl"))
        heldout_markers = self._markers(self._read(out, "heldout.jsonl"))
        assert train_markers and heldout_markers
        assert train_markers.isdisjoint(heldout_markers)

    def test_every_split_record_fits_the_sequence_budget(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch)
        prepare.run()
        budget = passage_budget_chars()
        records = self._read(out, "train.jsonl") + self._read(out, "heldout.jsonl")
        assert all(_record_chars(r) <= budget for r in records)

    def test_split_records_carry_their_task_shape(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch)
        prepare.run()
        records = self._read(out, "train.jsonl") + self._read(out, "heldout.jsonl")
        assert all(r["shape"] in TASK_SHAPES for r in records)

    def test_instruct_jsonl_stays_one_record_per_article(self, tmp_path, monkeypatch, capsys):
        # the dashboard's geo-llm tab counts these lines as the corpus size
        out = self._corpus(tmp_path, monkeypatch)
        prepare.run()
        assert len(self._read(out, "instruct.jsonl")) == self.N_ARTICLES

    def test_shared_footer_never_reaches_the_passage_records(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch, footer="Contact me at gcalhoun@example.edu.")
        prepare.run()
        records = self._read(out, "train.jsonl") + self._read(out, "heldout.jsonl")
        assert records
        assert not any(
            "gcalhoun@example.edu" in m["content"] for r in records for m in r["messages"]
        )

    def test_the_splits_share_no_passage(self, tmp_path, monkeypatch, capsys):
        # identical text on both sides is leakage: it inflates validation
        out = self._corpus(tmp_path, monkeypatch, footer="Contact me at gcalhoun@example.edu.")
        prepare.run()
        train = {r["messages"][2]["content"] for r in self._read(out, "train.jsonl")}
        heldout = {r["messages"][2]["content"] for r in self._read(out, "heldout.jsonl")}
        assert train and heldout
        assert train.isdisjoint(heldout)

    def test_eval_grounded_articles_stay_out_of_both_splits(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch)
        questions = {"questions": [{"question": "q", "topic_hint": "Title Number 3 (2021)"}]}
        (tmp_path / "questions.json").write_text(json.dumps(questions))
        monkeypatch.setattr(prepare, "EVAL_QUESTIONS_PATH", tmp_path / "questions.json")
        prepare.run()
        records = self._read(out, "train.jsonl") + self._read(out, "heldout.jsonl")
        assert "marker3" not in self._markers(records)


class TestRunDeduplicatesTheCorpus:
    """`run()` walks the manifest directly, so it inherits the duplicate-slug defect:
    23 articles appear twice in data/manifest.json, and each was written to
    finetune.jsonl/instruct.jsonl twice — silently over-weighting them in the QLoRA run.
    """

    def _corpus(self, tmp_path, monkeypatch):
        raw = tmp_path / "raw"
        raw.mkdir()
        body = "Sentence about the economy. " * 200  # clears the 400-word quality bar
        for name in ("dup", "solo"):
            (raw / f"{name}.json").write_text(
                json.dumps({"title": f"Title {name}", "body": body, "date": "2021-01-01"})
            )
        entries = [
            {"slug": "dup", "url": "http://f.com/dup/", "file": "raw/dup.json",
             "title": "Title dup", "date": "2021-01-01", "word_count": 1000},
            {"slug": "dup", "url": "https://f.com/dup/", "file": "raw/dup.json",
             "title": "Title dup", "date": "2021-01-01", "word_count": 1000},
            {"slug": "solo", "url": "https://f.com/solo/", "file": "raw/solo.json",
             "title": "Title solo", "date": "2021-01-02", "word_count": 1000},
        ]
        (tmp_path / "manifest.json").write_text(
            json.dumps({"total_articles": len(entries), "articles": entries})
        )
        monkeypatch.setattr(prepare, "DATA_DIR", tmp_path)
        monkeypatch.setattr(prepare, "MANIFEST_PATH", tmp_path / "manifest.json")
        monkeypatch.setattr(prepare, "TRAINING_DIR", tmp_path / "training")
        monkeypatch.setattr(prepare, "LINGUISTICS_PATH", tmp_path / "absent.json")
        monkeypatch.setattr(prepare, "EVAL_QUESTIONS_PATH", tmp_path / "absent.json")
        return tmp_path / "training"

    def test_finetune_jsonl_has_one_line_per_article(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch)
        prepare.run()
        lines = (out / "finetune.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2

    def test_instruct_jsonl_has_one_line_per_article(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch)
        prepare.run()
        lines = (out / "instruct.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2

    def test_the_duplicated_article_body_appears_once(self, tmp_path, monkeypatch, capsys):
        out = self._corpus(tmp_path, monkeypatch)
        prepare.run()
        records = [json.loads(x) for x in (out / "finetune.jsonl").read_text().splitlines()]
        assert sum(1 for r in records if "Sentence about the economy" in r["text"]) == 2
