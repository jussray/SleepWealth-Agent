from scripts.verify_vercel_deployed_runtime import verify_deployment


EXPECTED = "a" * 40
BASE = "https://sleepwealth-paper-lab.vercel.app"


def _boundary():
    return {
        "classification": "BLOCKED",
        "authority": "sandbox-simulation-only",
        "override_effect": "none",
        "execution_authorized": False,
        "real_money": False,
        "live_execution": False,
        "wallet_connection": False,
        "funding": False,
        "signing": False,
        "brokerage_order_submission": False,
    }


def _green_fetcher(url):
    if url == f"{BASE}/health":
        return 200, {
            "x-sleepwealth-source-sha": EXPECTED,
            "x-sleepwealth-live-execution": "false",
            "x-sleepwealth-real-money": "false",
        }, {"mode": "paper", "live_execution": False}
    if url == f"{BASE}/pump-live-box/health":
        return 200, {}, {
            "runtime_identity": {
                "source_sha": EXPECTED,
                "exact_source_known": True,
                "execution_authorized": False,
            },
            "money_boundary": _boundary(),
        }
    if url == f"{BASE}/pump-live-box/api/money-boundary":
        return 200, {}, _boundary()
    raise AssertionError(url)


def _classifications(receipt):
    return {check["code"]: check["classification"] for check in receipt["checks"]}


def test_deployed_runtime_receipt_verifies_exact_head_and_fail_closed_boundary():
    receipt = verify_deployment(BASE, EXPECTED, fetcher=_green_fetcher)

    assert receipt["classification"] == "VERIFIED"
    assert all(value == "VERIFIED" for value in _classifications(receipt).values())
    assert receipt["execution_authorized"] is False
    assert receipt["real_money"] is False
    assert receipt["live_execution"] is False
    assert receipt["fingerprint"].startswith("vercel-deployed-runtime-v1:")


def test_stale_paper_sha_is_separate_from_safety_and_pump_receipts():
    def fetcher(url):
        status, headers, payload = _green_fetcher(url)
        if url == f"{BASE}/health":
            headers = {**headers, "x-sleepwealth-source-sha": "b" * 40}
        return status, headers, payload

    receipt = verify_deployment(BASE, EXPECTED, fetcher=fetcher)
    classifications = _classifications(receipt)

    assert receipt["classification"] == "BLOCKED"
    assert classifications["PAPER_RUNTIME_EXACT_SHA"] == "BLOCKED"
    assert classifications["PAPER_RUNTIME_AUTHORITY_CEILING"] == "VERIFIED"
    assert classifications["PUMP_RUNTIME_EXACT_SHA"] == "VERIFIED"
    assert classifications["PUMP_INLINE_MONEY_BOUNDARY"] == "VERIFIED"
    assert classifications["PUMP_MONEY_BOUNDARY_ENDPOINT"] == "VERIFIED"


def test_missing_pump_boundary_endpoint_does_not_overwrite_other_receipts():
    def fetcher(url):
        if url == f"{BASE}/pump-live-box/api/money-boundary":
            raise RuntimeError("404")
        return _green_fetcher(url)

    receipt = verify_deployment(BASE, EXPECTED, fetcher=fetcher)
    classifications = _classifications(receipt)

    assert receipt["classification"] == "BLOCKED"
    assert classifications["PUMP_MONEY_BOUNDARY_ENDPOINT"] == "BLOCKED"
    assert classifications["PUMP_RUNTIME_REACHABLE"] == "VERIFIED"
    assert classifications["PUMP_RUNTIME_EXACT_SHA"] == "VERIFIED"
    assert classifications["PUMP_INLINE_MONEY_BOUNDARY"] == "VERIFIED"


def test_pump_runtime_identity_missing_is_independent_of_inline_boundary():
    def fetcher(url):
        status, headers, payload = _green_fetcher(url)
        if url == f"{BASE}/pump-live-box/health":
            payload = {"money_boundary": _boundary()}
        return status, headers, payload

    receipt = verify_deployment(BASE, EXPECTED, fetcher=fetcher)
    classifications = _classifications(receipt)

    assert classifications["PUMP_RUNTIME_EXACT_SHA"] == "BLOCKED"
    assert classifications["PUMP_INLINE_MONEY_BOUNDARY"] == "VERIFIED"
    assert classifications["PUMP_MONEY_BOUNDARY_ENDPOINT"] == "VERIFIED"
