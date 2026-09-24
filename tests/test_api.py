import copy
import time
from dataclasses import replace

import pytest
from conftest import NativeApi, serve, source_json, transcript_page, turn

from kimi_memory.config import ApiConfig
from kimi_memory.errors import (
    CompatibilityError,
    ConfigurationError,
    IncompleteHistoryError,
    TransportError,
)
from kimi_memory.http import JsonHttp, local_origin, model_origin
from kimi_memory.kimi import KimiClient, validate_page


def client(origin, **kwargs):
    return KimiClient(origin, lambda: "test-native-token-never-log", replace(ApiConfig(), **kwargs))


def test_native_api_handshake_and_paginated_history(transcript):
    data = replace(transcript, items=[turn(transcript.source, i) for i in range(1, 6)])
    with serve(NativeApi([data])) as (origin, requests):
        api = client(origin, page_size=2)
        api.handshake("test-native")
        result = api.transcript(data.source)
    assert result == data
    paths = [r[1] for r in requests]
    assert sum("/transcript?" in p for p in paths) == 3
    assert all("/messages" not in p and "/snapshot" not in p for p in paths)
    assert api.server_version == "2.1.0"


def test_session_pagination_is_complete_and_keeps_archived_for_citations(transcript):
    copies = [
        replace(
            transcript,
            source=replace(
                transcript.source,
                id=f"session_{i}",
                updated_at=transcript.source.updated_at + i,
                archived=i == 2,
            ),
        )
        for i in range(5)
    ]
    with serve(NativeApi(copies)) as (origin, _):
        result = client(origin, page_size=2).sessions(since=0, limit=10)
    assert result == [t.source for t in reversed(copies)]


def test_scan_cap_is_not_mistaken_for_complete_history(transcript):
    copies = [replace(transcript, source=replace(transcript.source, id=f"s{i}")) for i in range(3)]
    with serve(NativeApi(copies)) as (origin, _), pytest.raises(IncompleteHistoryError):
        client(origin).sessions(since=0, limit=2)


@pytest.mark.parametrize(
    "limits", [{"max_transcript_pages": 1, "page_size": 1}, {"max_transcript_bytes": 64}]
)
def test_history_limits_fail_closed(transcript, limits):
    data = replace(transcript, items=[turn(transcript.source, i) for i in range(1, 4)])
    with serve(NativeApi([data])) as (origin, _), pytest.raises(IncompleteHistoryError):
        client(origin, **limits).transcript(data.source)


def test_new_version_needs_explicit_acceptance(transcript):
    with serve(NativeApi([transcript], version="2.2.0")) as (origin, _):
        with pytest.raises(CompatibilityError):
            client(origin).handshake()
        allowed = client(origin, allow_unverified_version=True)
        allowed.handshake()
        assert allowed.unverified is True


def test_server_identity_mismatch_is_rejected(transcript):
    with serve(NativeApi([transcript])) as (origin, _), pytest.raises(CompatibilityError):
        client(origin).handshake("not-this-server")


def test_matching_version_does_not_override_missing_contract(transcript):
    server = NativeApi([transcript])
    server.overrides["/openapi.json"] = (200, {"paths": {}})
    with serve(server) as (origin, _), pytest.raises(CompatibilityError):
        client(origin).handshake()


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(agent_id="subagent"),
        lambda p: p.update(has_more="false"),
        lambda p: p.pop("interactions"),
        lambda p: p["items"][0]["origin"].update(kind="new_unknown_origin"),
        lambda p: p["items"][0]["steps"][0]["frames"][0].update(kind="new_message"),
        lambda p: p["items"][0]["steps"][0]["frames"][0].update(role="developer"),
    ],
)
def test_unknown_semantic_shapes_are_not_ignored(transcript, change):
    page = copy.deepcopy(transcript_page(transcript))
    change(page)
    with pytest.raises(CompatibilityError):
        validate_page(page)


def test_additive_metadata_does_not_break_current_contract(transcript):
    page = copy.deepcopy(transcript_page(transcript))
    page["new_diagnostic"] = {"harmless": True}
    page["items"][0]["steps"][0]["new_timing_measure"] = 7
    validate_page(page)


def test_torn_snapshot_metadata_is_detected(transcript):
    native = NativeApi([transcript])
    modified = source_json(replace(transcript.source, updated_at=time.time()))
    native.overrides["/api/v1/sessions/" + transcript.source.id] = (
        200,
        {"code": 0, "data": modified},
    )
    with serve(native) as (origin, _), pytest.raises(IncompleteHistoryError):
        client(origin).transcript(transcript.source)


def test_changed_global_entities_during_paging_are_detected(transcript):
    data = replace(transcript, items=[turn(transcript.source, i) for i in (1, 2, 3)])
    native = NativeApi([data])
    counter = 0

    def callback(method, path, body, headers):
        nonlocal counter
        status, result = native(method, path, body, headers)
        if "/transcript?" in path:
            result["data"]["seq"] = counter
            counter += 1
        return status, result

    with serve(callback) as (origin, _), pytest.raises(IncompleteHistoryError):
        client(origin, page_size=1).transcript(data.source)


def test_native_auth_401_refreshes_token_once(transcript):
    count = 0

    def token():
        nonlocal count
        count += 1
        return "old-token" if count == 1 else "test-native-token-never-log"

    with serve(NativeApi([transcript])) as (origin, requests):
        api = KimiClient(origin, token, ApiConfig())
        api.handshake()
    assert len(requests) == 3


def test_http_errors_never_echo_service_body_or_credential():
    with serve(lambda *_: (500, {"error": "secret credential and private transcript"})) as (
        origin,
        _,
    ):
        with pytest.raises(TransportError) as error:
            JsonHttp().request(origin)
    assert "500" in str(error.value) and "secret" not in str(error.value)


def test_http_response_limit():
    with serve(lambda *_: (200, {"text": "x" * 500})) as (origin, _), pytest.raises(TransportError):
        JsonHttp(max_bytes=20).request(origin)


def test_redirect_never_forwards_authenticated_request():
    with serve(lambda *_: (200, {"ok": True})) as (target, received):
        with serve(lambda *_: (302, {}, {"Location": target + "/capture"})) as (origin, _):
            with pytest.raises(TransportError):
                JsonHttp().request(origin, headers={"Authorization": "Bearer private"})
        assert received == []


def test_answered_question_cannot_silently_lose_its_response(transcript):
    page = transcript_page(transcript)
    page["interactions"] = [
        {
            "interactionId": "q",
            "interactionKind": "question",
            "state": "answered",
            "request": {"question": "Which?"},
        }
    ]
    with pytest.raises(CompatibilityError):
        validate_page(page)


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.test:1234",
        "http://127.0.0.1:1234/path",
        "http://u:p@localhost:1234",
        "file:///etc/passwd",
        "http://127.0.0.1:1234#token=secret",
    ],
)
def test_api_is_loopback_only_without_embedded_credentials(origin):
    with pytest.raises(ConfigurationError):
        local_origin(origin)


def test_model_transport_requires_tls_except_loopback():
    assert model_origin("https://example.test/v1") == "https://example.test/v1"
    assert model_origin("http://127.0.0.1:2345/v1") == "http://127.0.0.1:2345/v1"
    with pytest.raises(ConfigurationError):
        model_origin("http://example.test/v1")


def test_non_success_envelope_is_not_empty_data():
    with (
        serve(lambda *_: (200, {"code": 50001, "data": {"items": []}})) as (origin, _),
        pytest.raises(TransportError),
    ):
        client(origin).get("/api/v1/sessions")
