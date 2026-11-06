"""Fixture copy of CLI 2.1.294 Bp defaults (bundle offset 210613402)."""


def zero_bootstrap_usage() -> dict:
    return {
        "output_tokens_details": {"thinking_tokens": 0},
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
        "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
        "service_tier": "standard",
        "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0},
        "inference_geo": "",
        "iterations": [],
        "speed": "standard",
        "fallback_credit": None,
    }
