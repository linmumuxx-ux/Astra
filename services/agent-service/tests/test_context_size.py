"""网关后面的模型名要落到对应模型卡的 context_size。"""

from agent_service import card_context_size


class _Card:
    def __init__(self, name: str, context_size: int) -> None:
        self.name = name
        self.context_size = context_size


class _OpenAI:
    @staticmethod
    def list_models():
        return [_Card("gpt-4.1", 1047576)]


class _DeepSeek:
    @staticmethod
    def list_models():
        return [_Card("deepseek-v4-flash", 1_000_000)]


def test_gateway_model_uses_the_matching_card_not_the_openai_default():
    model_context = 128000
    size = card_context_size("deepseek-v4-flash", [_OpenAI, _DeepSeek])
    assert size == 1_000_000
    assert size != model_context
    assert card_context_size("gpt-4.1", [_OpenAI, _DeepSeek]) == 1047576
    assert card_context_size("custom-route", [_OpenAI, _DeepSeek]) is None
