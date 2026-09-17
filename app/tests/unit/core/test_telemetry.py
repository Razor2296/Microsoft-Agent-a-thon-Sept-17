from backend.core import telemetry


def test_record_invoke_updates_snapshot():
    before = telemetry.get_metrics_snapshot()["invokes_total"]
    telemetry.record_invoke("get_initial_state", 12.5, ok=True)
    telemetry.record_invoke("send_message", 40.0, ok=False)
    snap = telemetry.get_metrics_snapshot()
    assert snap["invokes_total"] >= before + 2
    assert snap["invokes_error"] >= 1
    assert "invoke_latency_ms_avg" in snap


def test_record_token_usage_by_provider():
    telemetry.record_token_usage("Gemini", 11)
    snap = telemetry.get_metrics_snapshot()
    assert snap["tokens_total"] >= 11
    assert snap["tokens_by_provider"].get("Gemini", 0) >= 11


def test_trace_span_counts():
    with telemetry.trace_span("unit.test_span", {"k": "v"}):
        pass
    snap = telemetry.get_metrics_snapshot()
    assert "unit.test_span" in snap["spans"]
    assert snap["spans"]["unit.test_span"]["count"] >= 1
