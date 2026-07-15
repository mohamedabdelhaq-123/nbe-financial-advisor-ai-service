"""Unit tests for the chat stream-contract schemas (envelope/widget/reference)."""

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from app.features.chat.schemas import (
    AllocationSliderWidget,
    ChatTurnRequest,
    DoneEvent,
    DonePayload,
    ProductCardWidget,
    Reference,
    TokenEvent,
    Widget,
)

_widget_adapter = TypeAdapter(Widget)


def test_token_event_serializes_to_envelope():
    assert TokenEvent(data="x").model_dump_json() == '{"event":"token","data":"x"}'


def test_done_event_has_no_id_key_anywhere():
    payload = DonePayload(
        content="reply",
        widget=AllocationSliderWidget.model_validate(
            {
                "type": "allocation_slider",
                "payload": {"allocations": [{"category": "x", "percentage": 100}]},
            }
        ),
        references=[
            Reference(target_type="transaction", target_id="b3f1c2d4-0000-0000-0000-000000000000")
        ],
    )
    rendered = json.loads(DoneEvent(data=payload).model_dump_json())

    assert rendered["event"] == "done"
    assert "id" not in rendered
    assert "id" not in rendered["data"]
    assert "widget" in rendered["data"]
    assert "references" in rendered["data"]
    assert rendered["data"]["widget"]["type"] == "allocation_slider"
    assert rendered["data"]["references"][0]["target_type"] == "transaction"


def test_done_payload_defaults_widget_null_references_empty():
    payload = DonePayload(content="hi")
    assert payload.widget is None
    assert payload.references == []

    rendered = json.loads(DoneEvent(data=payload).model_dump_json())
    assert rendered["data"]["widget"] is None
    assert rendered["data"]["references"] == []
    assert "id" not in rendered["data"]


@pytest.mark.parametrize("bad_type", ["products", "transaction_id", "txns", ""])
def test_reference_rejects_unknown_target_type(bad_type):
    with pytest.raises(ValidationError):
        Reference(target_type=bad_type, target_id="b3f1c2d4-0000-0000-0000-000000000000")  # type: ignore[arg-type]


def test_reference_accepts_transaction_and_statement():
    for allowed in ("transaction", "statement"):
        ref = Reference(target_type=allowed, target_id="b3f1c2d4-0000-0000-0000-000000000000")
        assert ref.target_type == allowed


def test_widget_union_accepts_both_types():
    alloc = _widget_adapter.validate_python(
        {
            "type": "allocation_slider",
            "payload": {"allocations": [{"category": "x", "percentage": 50}]},
        }
    )
    assert isinstance(alloc, AllocationSliderWidget)

    card = _widget_adapter.validate_python(
        {
            "type": "product_card",
            "payload": {
                "products": [
                    {
                        "product_id": "5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f",
                        "product_name": "Savings",
                        "similarity": 0.9,
                    }
                ]
            },
        }
    )
    assert isinstance(card, ProductCardWidget)


def test_widget_union_rejects_unknown_type():
    with pytest.raises(ValidationError):
        _widget_adapter.validate_python({"type": "mystery_widget", "payload": {}})


def test_allocation_percentage_bounds_enforced():
    with pytest.raises(ValidationError):
        AllocationSliderWidget.model_validate(
            {
                "type": "allocation_slider",
                "payload": {"allocations": [{"category": "x", "percentage": 150}]},
            }
        )


def test_product_similarity_bounds_enforced():
    with pytest.raises(ValidationError):
        ProductCardWidget.model_validate(
            {
                "type": "product_card",
                "payload": {
                    "products": [
                        {
                            "product_id": "5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f",
                            "product_name": "S",
                            "similarity": 1.5,
                        }
                    ]
                },
            }
        )


def test_envelope_fields_carry_descriptions():
    # T027: documented fields expose a description for OpenAPI schema generation.
    assert DonePayload.model_fields["widget"].description
    assert DonePayload.model_fields["references"].description
    assert Reference.model_fields["target_type"].description
    assert Reference.model_fields["target_id"].description


def test_envelope_models_carry_examples():
    # T027: json_schema_extra examples render for the headline models.
    assert DoneEvent.model_json_schema().get("examples")
    assert AllocationSliderWidget.model_json_schema().get("examples")


def test_chat_turn_request_rejects_non_uuid_user_id():
    # FR-001: a non-UUID user_id must be rejected before any privileged action runs.
    with pytest.raises(ValidationError):
        ChatTurnRequest(conversation_id="c1", user_id=1001, message="hi")


def test_chat_turn_request_accepts_uuid_user_id():
    request = ChatTurnRequest(
        conversation_id="c1",
        user_id="7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
        message="hi",
    )
    assert str(request.user_id) == "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d"
