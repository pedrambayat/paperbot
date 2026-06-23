import os
from unittest.mock import patch

from paperbot.config import DEFAULT_OPENAI_MODEL, Settings


def test_settings_allow_missing_app_token_for_serverless():
    # The serverless worker has no Socket Mode app token; it must still load.
    env = {**os.environ, "SLACK_BOT_TOKEN": "xoxb-test", "PAPERBOT_CHANNEL_ID": "C123"}
    env.pop("SLACK_APP_TOKEN", None)
    with patch.dict(os.environ, env, clear=True):
        assert Settings.from_env().slack_app_token == ""


def test_settings_default_to_cheap_openai_model():
    env = {
        **os.environ,
        "SLACK_BOT_TOKEN": "xoxb-test",
        "SLACK_APP_TOKEN": "xapp-test",
        "PAPERBOT_CHANNEL_ID": "C123",
    }
    env.pop("OPENAI_MODEL", None)
    with patch.dict(os.environ, env, clear=True):
        assert Settings.from_env().openai_model == DEFAULT_OPENAI_MODEL
        assert DEFAULT_OPENAI_MODEL == "gpt-5-mini"
