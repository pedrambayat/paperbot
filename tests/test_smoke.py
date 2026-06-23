from unittest.mock import patch

import pytest

from paperbot.smoke import build_smoke_summarizer
from paperbot.summarizer import DryRunSummarizer


def test_smoke_defaults_to_dry_run_without_openai_key():
    with patch.dict("os.environ", {}, clear=True):
        assert isinstance(build_smoke_summarizer(real=False, model="gpt-5-mini"), DryRunSummarizer)


def test_smoke_real_mode_requires_openai_key():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            build_smoke_summarizer(real=True, model="gpt-5-mini")
