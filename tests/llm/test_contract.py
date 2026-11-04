from tests.fakes.llm import FakeLLM, run_provider_contract


def test_fake_llm_passes_the_provider_contract():
    run_provider_contract(FakeLLM)


def test_fake_llm_records_calls_and_timeouts():
    fake = FakeLLM(["a", "b"])
    fake.generate_text("one", timeout_s=60)
    fake.generate_text("two")
    assert fake.calls == ["one", "two"] and fake.timeouts == [60, None]
