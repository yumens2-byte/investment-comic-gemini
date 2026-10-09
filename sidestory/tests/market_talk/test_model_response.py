import json
from types import SimpleNamespace

import pytest

from sidestory.market_talk import __main__ as cli
from sidestory.market_talk.diagnostics import PhaseFailure
from sidestory.market_talk.generation import ModelResponseError, generate, review
from sidestory.tests.market_talk.test_content_and_delivery import Store, sample


def client(text):
    return SimpleNamespace(
        messages=SimpleNamespace(
            count_tokens=lambda **kw: SimpleNamespace(input_tokens=100),
            create=lambda **kw: SimpleNamespace(
                stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)]
            ),
        )
    )


@pytest.mark.parametrize("fence", [False, True])
def test_generation_plain_or_whole_json_fence(fence):
    draft = sample()
    text = draft.text.model_dump_json()
    if fence:
        text = "```json\n" + text + "\n```"
    assert (
        generate(
            draft.context,
            Store(),
            "123",
            model="fixture",
            input_rate=1,
            output_rate=2,
            client=client(text),
        )
        == draft.text
    )


@pytest.mark.parametrize(
    "text,code",
    [
        ("", "MODEL_RESPONSE_INVALID_JSON"),
        ('설명 {"evidence_ids":[]}', "MODEL_RESPONSE_INVALID_JSON"),
        ('{"commentary":"unfinished', "MODEL_RESPONSE_INVALID_JSON"),
        ("[]", "MODEL_RESPONSE_INVALID_SCHEMA"),
        (
            '{"evidence_ids":[],"commentary":"short","dialogue":"short"}',
            "MODEL_RESPONSE_INVALID_SCHEMA",
        ),
    ],
)
def test_invalid_generation_fails_without_releasing_cost_or_retry(text, code):
    store = Store()
    with pytest.raises(ModelResponseError) as exc:
        generate(
            sample().context,
            store,
            "123",
            model="fixture",
            input_rate=1,
            output_rate=2,
            client=client(text),
        )
    assert exc.value.phase == "generation" and exc.value.code == code
    with pytest.raises(PhaseFailure, match="reservation"):
        generate(
            sample().context,
            store,
            "123",
            model="fixture",
            input_rate=1,
            output_rate=2,
            client=client(text),
        )


def test_fenced_review_and_strict_booleans():
    verdict = dict(
        evidence_supported=True,
        canon_consistent=True,
        no_invented_events=True,
        no_trading_advice=True,
        readable_korean=True,
    )
    args = dict(model="fixture", input_rate=1, output_rate=2)
    assert review(
        sample(), Store(), "123", client=client("```json\n" + json.dumps(verdict) + "\n```"), **args
    ).accepted
    verdict["evidence_supported"] = "true"
    with pytest.raises(ModelResponseError) as exc:
        review(sample(), Store(), "123", client=client(json.dumps(verdict)), **args)
    assert exc.value.phase == "review" and exc.value.code == "MODEL_RESPONSE_INVALID_SCHEMA"


def test_cli_reports_safe_phase_without_model_text(monkeypatch, capsys):
    monkeypatch.setenv("FACE_PAGE_ID", "123")
    monkeypatch.setenv("MARKET_TALK_AUTO_ENABLED", "true")
    monkeypatch.setattr(cli, "connection", lambda: object())
    monkeypatch.setattr(cli, "TalkStore", lambda _: Store())

    def fail(*a, **kw):
        raise ModelResponseError("generation", "MODEL_RESPONSE_INVALID_JSON")

    monkeypatch.setattr("sidestory.market_talk.automation.automatic_draft", fail)
    assert cli.main(["--stage", "automate"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["phase"] == "generation" and report["reservation_retained"]
    assert report["automatic_retry"] is False
