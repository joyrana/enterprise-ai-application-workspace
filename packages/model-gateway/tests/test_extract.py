from __future__ import annotations

import pytest

from model_gateway import ExtractionError, extract_json_object, strip_reasoning


def test_plain_json() -> None:
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_qwen_think_block_is_removed() -> None:
    text = '<think>The user wants {"not": "this"}. Let me answer.</think>\n{"answer": true}'
    assert extract_json_object(text) == {"answer": True}


def test_unclosed_think_block_yields_no_answer() -> None:
    with pytest.raises(ExtractionError):
        extract_json_object('<think>still reasoning {"partial": 1}')


def test_gpt_oss_harmony_final_channel_is_used() -> None:
    text = (
        '<|channel|>analysis<|message|>Consider {"draft": 1}<|end|>'
        '<|start|>assistant<|channel|>final<|message|>{"final": 2}<|return|>'
    )
    assert extract_json_object(text) == {"final": 2}


def test_code_fences_and_trailing_commentary() -> None:
    text = 'Here you go:\n```json\n{"x": "a } brace in a string", "y": [1, 2]}\n```\nHope this helps! {oops'
    assert extract_json_object(text) == {"x": "a } brace in a string", "y": [1, 2]}


def test_skips_invalid_candidate_and_finds_next_object() -> None:
    assert extract_json_object('{not json} then {"ok": 1}') == {"ok": 1}


def test_escaped_quotes_inside_strings() -> None:
    assert extract_json_object(r'{"q": "say \"hi\" {now}"}') == {"q": 'say "hi" {now}'}


def test_truncated_output_reports_clearly() -> None:
    with pytest.raises(ExtractionError, match="never closed"):
        extract_json_object('{"a": [1, 2')


def test_top_level_array_is_not_accepted() -> None:
    with pytest.raises(ExtractionError):
        extract_json_object("[1, 2, 3]")


def test_empty_response() -> None:
    with pytest.raises(ExtractionError, match="no answer text"):
        extract_json_object("<think>only thoughts</think>   ")


def test_strip_reasoning_keeps_answer() -> None:
    assert strip_reasoning("<think>x</think> answer") == "answer"
