"""Tests for analysis/rag_eval.py — the Ask Dad RAG faithfulness eval harness.

Plan 0007. Exercises pure logic only: the deterministic scorers (abstention
detection, retrieved-title citation matching), the LLM-judge response parser,
and the harness run loop / aggregation / report. The compute-heavy seams
(retrieval, generation, LLM judge) are injected as fakes, so no conductor and
no network are touched here.
"""

import json

from analysis.rag_eval import (
    aggregate,
    cited_retrieved_titles,
    evaluate,
    is_abstention,
    load_questions,
    normalize,
    parse_judgment,
    write_report,
)


class TestNormalize:
    def test_lowercases_and_strips_punctuation(self):
        assert normalize("The Fed!") == "the fed"

    def test_collapses_whitespace(self):
        assert normalize("a   b\tc") == "a b c"

    def test_handles_curly_quotes(self):
        # corpus titles use typographic quotes; matching must survive them
        assert normalize("“Whatever It Takes”") == "whatever it takes"


class TestIsAbstention:
    def test_detects_canonical_refusal(self):
        assert is_abstention("I haven't written about that specifically.")

    def test_detects_variant_phrasing(self):
        assert is_abstention("I have not written about that topic.")

    def test_substantive_answer_is_not_abstention(self):
        ans = 'The Fed prints alpha by backstopping markets ("Prints Alpha", 2020).'
        assert not is_abstention(ans)

    def test_empty_answer_counts_as_abstention(self):
        assert is_abstention("")


class TestCitedRetrievedTitles:
    def test_finds_retrieved_title_mentioned_in_answer(self):
        retrieved = [
            {"title": "Does Inflation Still Exist?"},
            {"title": "The Fed Doesn't Just Print Money, It Also Prints Alpha"},
        ]
        answer = "As I argued in Does Inflation Still Exist?, the data is murky."
        present, absent = cited_retrieved_titles(answer, retrieved)
        assert "Does Inflation Still Exist?" in present
        assert "The Fed Doesn't Just Print Money, It Also Prints Alpha" in absent

    def test_matching_ignores_case_and_punctuation(self):
        retrieved = [{"title": "Europe’s Hamiltonian Moment – What Is It Really?"}]
        answer = "see europes hamiltonian moment  what is it really for details"
        present, absent = cited_retrieved_titles(answer, retrieved)
        assert present == ["Europe’s Hamiltonian Moment – What Is It Really?"]
        assert absent == []

    def test_no_titles_when_none_mentioned(self):
        retrieved = [{"title": "Huawei Is Happy With Crappy"}]
        present, absent = cited_retrieved_titles("A generic answer.", retrieved)
        assert present == []
        assert absent == ["Huawei Is Happy With Crappy"]


class TestParseJudgment:
    def test_parses_clean_object(self):
        text = json.dumps(
            {
                "claims_total": 4,
                "claims_grounded": 3,
                "citations_valid": True,
                "abstained": False,
            }
        )
        out = parse_judgment(text)
        assert out["claims_total"] == 4
        assert out["claims_grounded"] == 3
        assert out["citations_valid"] is True
        assert out["abstained"] is False

    def test_tolerates_markdown_fence_and_prose(self):
        text = (
            "Here is my assessment:\n```json\n"
            '{"claims_total": 2, "claims_grounded": 2, '
            '"citations_valid": true, "abstained": false}\n```\nDone.'
        )
        out = parse_judgment(text)
        assert out["claims_total"] == 2
        assert out["claims_grounded"] == 2

    def test_returns_none_on_garbage(self):
        assert parse_judgment("no json here") is None

    def test_clamps_grounded_to_total(self):
        text = '{"claims_total": 2, "claims_grounded": 5, "citations_valid": true}'
        out = parse_judgment(text)
        assert out["claims_grounded"] == 2

    def test_missing_fields_default_safely(self):
        out = parse_judgment('{"claims_total": 3}')
        assert out["claims_total"] == 3
        assert out["claims_grounded"] == 0
        assert out["citations_valid"] is False
        assert out["abstained"] is False


class TestEvaluate:
    def _fakes(self, answer, judgment):
        def retrieve(_q, top_k=8):
            return [
                {"title": "Does Inflation Still Exist?", "date": "2020-05-20",
                 "url": "http://x/1", "slug": "inflation"},
            ]

        def generate(_q, _sources):
            return answer

        def judge(_q, _answer, _sources):
            return judgment

        return retrieve, generate, judge

    def test_records_one_row_per_question(self):
        questions = [
            {"id": "a01", "question": "q", "answerable": True},
            {"id": "u01", "question": "q2", "answerable": False},
        ]
        retrieve, generate, judge = self._fakes(
            "Inflation is murky (Does Inflation Still Exist?, 2020).",
            {"claims_total": 1, "claims_grounded": 1, "citations_valid": True,
             "abstained": False},
        )
        records = evaluate(questions, retrieve, generate, judge)
        assert len(records) == 2
        assert records[0]["id"] == "a01"
        assert records[0]["num_retrieved"] == 1
        assert records[0]["cited_present"] == ["Does Inflation Still Exist?"]

    def test_abstention_flagged_from_answer_text(self):
        questions = [{"id": "u01", "question": "q", "answerable": False}]
        retrieve, generate, judge = self._fakes(
            "I haven't written about that specifically.",
            {"claims_total": 0, "claims_grounded": 0, "citations_valid": True,
             "abstained": True},
        )
        records = evaluate(questions, retrieve, generate, judge)
        assert records[0]["abstained"] is True
        assert records[0]["abstention_correct"] is True


class TestAggregate:
    def test_computes_headline_metrics(self):
        records = [
            # answerable, grounded, cited a retrieved title, did not abstain
            {"id": "a01", "answerable": True, "abstained": False,
             "claims_total": 4, "claims_grounded": 4,
             "cited_present": ["T"], "cited_absent": [], "abstention_correct": None},
            # answerable, partial grounding, one fabricated citation
            {"id": "a02", "answerable": True, "abstained": False,
             "claims_total": 4, "claims_grounded": 2,
             "cited_present": ["T"], "cited_absent": ["X"], "abstention_correct": None},
            # unanswerable, correctly abstained
            {"id": "u01", "answerable": False, "abstained": True,
             "claims_total": 0, "claims_grounded": 0,
             "cited_present": [], "cited_absent": [], "abstention_correct": True},
            # unanswerable, failed to abstain (hallucinated)
            {"id": "u02", "answerable": False, "abstained": False,
             "claims_total": 3, "claims_grounded": 0,
             "cited_present": [], "cited_absent": [], "abstention_correct": False},
        ]
        agg = aggregate(records)
        assert agg["n_questions"] == 4
        assert agg["n_answerable"] == 2
        assert agg["n_unanswerable"] == 2
        # grounding rate over answerable claims: (4+2)/(4+4) = 0.75
        assert abs(agg["grounding_rate"] - 0.75) < 1e-9
        # hallucination rate = 1 - grounding_rate
        assert abs(agg["hallucination_rate"] - 0.25) < 1e-9
        # abstention accuracy on unanswerable: 1 of 2
        assert abs(agg["abstention_accuracy"] - 0.5) < 1e-9
        # neither answerable question abstained → no false abstentions
        assert agg["false_abstention_rate"] == 0.0

    def test_false_abstention_counts_over_refusal_on_answerable(self):
        records = [
            {"id": "a01", "answerable": True, "abstained": True,
             "claims_total": 0, "claims_grounded": 0,
             "cited_present": [], "cited_absent": [], "abstention_correct": None},
            {"id": "a02", "answerable": True, "abstained": False,
             "claims_total": 2, "claims_grounded": 2,
             "cited_present": ["T"], "cited_absent": [], "abstention_correct": None},
        ]
        agg = aggregate(records)
        # one of two answerable questions wrongly refused
        assert abs(agg["false_abstention_rate"] - 0.5) < 1e-9

    def test_empty_records_safe(self):
        agg = aggregate([])
        assert agg["n_questions"] == 0
        assert agg["grounding_rate"] == 0.0
        assert agg["abstention_accuracy"] == 0.0
        assert agg["false_abstention_rate"] == 0.0


class TestWriteReport:
    def test_writes_json_with_summary_and_records(self, tmp_path):
        records = [
            {"id": "a01", "answerable": True, "abstained": False,
             "claims_total": 1, "claims_grounded": 1,
             "cited_present": ["T"], "cited_absent": [], "abstention_correct": None},
        ]
        out = tmp_path / "rag_eval.json"
        write_report(records, out)
        data = json.loads(out.read_text())
        assert "summary" in data
        assert "records" in data
        assert data["summary"]["n_questions"] == 1
        assert "generated_at" in data


class TestLoadQuestions:
    def test_loads_the_shipped_fixture(self):
        questions = load_questions()
        assert len(questions) >= 10
        ids = {q["id"] for q in questions}
        assert "a01" in ids
        # at least one deliberately-unanswerable question for abstention testing
        assert any(not q["answerable"] for q in questions)
