from paperbot.slack_verify import verify_slack_signature

# Published example vector from Slack's request-signing docs.
SECRET = "8f742231b10e8888abcd99yyyzzz85a5"
TIMESTAMP = "1531420618"
BODY = (
    b"token=xyzz0WbapA4vBCDEFasx0q6G&team_id=T1DC2JH3J&team_domain=testteamnow"
    b"&channel_id=G8PSS9T3V&channel_name=foobar&user_id=U2CERLKJA&user_name=roadrunner"
    b"&command=%2Fwebhook-collect&text=&response_url=https%3A%2F%2Fhooks.slack.com%2Fcommands"
    b"%2FT1DC2JH3J%2F397700885554%2F96rGlfmibIGlgcZRskXaIFfN&trigger_id=398738663015.47445629121.803a0bc887a14d10d2c447fce8b6703c"
)
EXPECTED_SIG = "v0=a2114d57b48eac39b9ad189dd8316235a7b4a8d21a10bd27519666489c69b503"

# A timestamp "now" close to the signed timestamp so the request isn't seen as stale.
FRESH_NOW = int(TIMESTAMP) + 5


def test_valid_signature_passes():
    assert verify_slack_signature(SECRET, TIMESTAMP, EXPECTED_SIG, BODY, now=FRESH_NOW) is True


def test_wrong_signature_fails():
    bad = "v0=" + "0" * 64
    assert verify_slack_signature(SECRET, TIMESTAMP, bad, BODY, now=FRESH_NOW) is False


def test_tampered_body_fails():
    assert verify_slack_signature(SECRET, TIMESTAMP, EXPECTED_SIG, BODY + b"&evil=1", now=FRESH_NOW) is False


def test_wrong_secret_fails():
    assert verify_slack_signature("not-the-secret", TIMESTAMP, EXPECTED_SIG, BODY, now=FRESH_NOW) is False


def test_stale_timestamp_fails_replay_protection():
    # Correct signature, but the request is 10 minutes old -> reject.
    stale_now = int(TIMESTAMP) + 600
    assert verify_slack_signature(SECRET, TIMESTAMP, EXPECTED_SIG, BODY, now=stale_now) is False


def test_non_numeric_timestamp_fails():
    assert verify_slack_signature(SECRET, "not-a-number", EXPECTED_SIG, BODY, now=FRESH_NOW) is False
