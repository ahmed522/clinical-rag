import json

from app.routers import evaluation
from evaluate_rag import citation_metrics, summarize


def test_citation_metrics_require_expected_source_page_and_answer_text():
    query = {
        "expected_source": "guideline.pdf",
        "expected_pages": [7],
        "must_contain": ["HbA1c"],
    }
    sources = [
        {
            "source": "guideline.pdf",
            "page_number": 7,
            "text": "The guideline recommends measuring HbA1c regularly.",
        },
        {
            "source": "other.pdf",
            "page_number": 7,
            "text": "HbA1c",
        },
    ]

    correct = citation_metrics(query, sources, [1])
    wrong_document = citation_metrics(query, sources, [2])
    invalid = citation_metrics(query, sources, [3])

    assert correct == {"valid": True, "page_correct": True, "answer_support": True}
    assert wrong_document == {"valid": True, "page_correct": False, "answer_support": False}
    assert invalid == {"valid": False, "page_correct": False, "answer_support": False}


def test_summary_reports_grounding_abstention_citations_and_latency():
    results = [
        {
            "scope": "in_scope",
            "grounded": True,
            "abstained": False,
            "citation_valid": True,
            "citation_page_correct": True,
            "citation_answer_support": True,
            "latency_ms": {"total": 100.0},
            "error": None,
        },
        {
            "scope": "in_scope",
            "grounded": False,
            "abstained": True,
            "citation_valid": False,
            "citation_page_correct": False,
            "citation_answer_support": False,
            "latency_ms": {"total": 200.0},
            "error": "provider error",
        },
        {
            "scope": "out_of_scope",
            "grounded": False,
            "abstained": True,
            "citation_valid": False,
            "citation_page_correct": False,
            "citation_answer_support": False,
            "latency_ms": {"total": 300.0},
            "error": None,
        },
    ]

    report = summarize(results)

    assert report["in_scope"]["grounded_answers"] == 1
    assert report["in_scope"]["correct_page_citations"] == 1
    assert report["out_of_scope"]["correct_abstentions"] == 1
    assert report["errors"] == 1
    assert report["latency_ms"] == {"p50_total": 200.0, "p95_total": 300.0}


def test_latest_evaluation_report_uses_newest_available_artifact(tmp_path, monkeypatch):
    baseline = tmp_path / "rag_report.json"
    configured = tmp_path / "rag_report_configured.json"
    baseline.write_text(json.dumps({"provider": "mock"}), encoding="utf-8")
    configured.write_text(json.dumps({"provider": "configured"}), encoding="utf-8")
    configured.touch()
    monkeypatch.setattr(evaluation, "REPORT_PATHS", (configured, baseline))

    assert evaluation.latest_report(None)["provider"] == "configured"
