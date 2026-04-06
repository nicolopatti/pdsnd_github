from linkedin_agent.core.ai_client import AIClient


def test_extract_json_payload_handles_none():
    assert AIClient.extract_json_payload(None) == ""


def test_parse_json_response_safe_handles_fenced_json():
    raw = """```json
    {"content": "ciao", "hashtags": ["#x"]}
    ```"""
    parsed = AIClient.parse_json_response_safe(raw)
    assert parsed["content"] == "ciao"
    assert parsed["hashtags"] == ["#x"]
