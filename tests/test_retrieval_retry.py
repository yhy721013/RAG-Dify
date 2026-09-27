"""只读检索的临时失败恢复；合成故障，不是线上准确性评测。"""
from types import SimpleNamespace

import pytest

from app.errors import DomainError
from evals.evaluate_retrieval import retrieve_with_retries, transient_retrieval_error


def test_timeout_then_success_keeps_failure(monkeypatch):
    delays, calls = [], []
    monkeypatch.setattr("evals.evaluate_retrieval.time.sleep", delays.append)

    def retrieve(query, model):
        calls.append((query, model))
        if len(calls) == 1:
            raise DomainError("dify_timeout", "synthetic timeout")
        return ["synthetic hit"]

    hits, errors = retrieve_with_retries(SimpleNamespace(retrieve=retrieve), "same query", {"same": True}, 2, 7)
    assert hits == ["synthetic hit"] and len(errors) == 1
    assert errors[0]["error"]["code"] == "dify_timeout"
    assert calls[0] == calls[1] and delays == [7]


@pytest.mark.parametrize("code,status,expected_calls", [
    ("dify_timeout", None, 3), ("dify_http_error", 503, 3),
    ("dify_http_error", 401, 1), ("dify_http_error", 400, 1), ("mapping_error", None, 1),
])
def test_retry_is_bounded_and_does_not_hide_final_error(monkeypatch, code, status, expected_calls):
    monkeypatch.setattr("evals.evaluate_retrieval.time.sleep", lambda seconds: None)
    calls = []

    def retrieve(query, model):
        calls.append(query)
        raise DomainError(code, "synthetic", details={"upstream_status": status})

    hits, errors = retrieve_with_retries(SimpleNamespace(retrieve=retrieve), "query", {}, 2, 7)
    assert hits is None and len(calls) == expected_calls and len(errors) == expected_calls
    assert errors[-1]["error"]["code"] == code


def test_plugin_disconnect_is_retryable_but_other_model_errors_are_not():
    def error(message):
        return DomainError("dify_http_error", "synthetic", details={
            "upstream_status": 400, "upstream_message": message})
    assert transient_retrieval_error(error("PluginInvokeError: RemoteDisconnected"))
    assert not transient_retrieval_error(error("PluginInvokeError: invalid model"))


def test_long_retry_after_stops_without_ignoring_rate_limit(monkeypatch):
    def forbidden_sleep(seconds):
        pytest.fail("must not ignore the requested long delay")
    monkeypatch.setattr("evals.evaluate_retrieval.time.sleep", forbidden_sleep)

    def retrieve(query, model):
        raise DomainError("dify_http_error", "synthetic", details={"upstream_status": 429, "retry_after": "120"})
    hits, errors = retrieve_with_retries(SimpleNamespace(retrieve=retrieve), "query", {}, 2, 7)
    assert hits is None and len(errors) == 1
