import asyncio

from agent_service import claim_event, finish_event, reset_event_claims


def test_same_event_is_delivered_once_until_failure_releases_it():
    async def scenario():
        reset_event_claims()
        assert await claim_event("evt-1") == "owner"
        assert await claim_event("evt-1") == "inflight"
        await finish_event("evt-1", delivered=False)
        assert await claim_event("evt-1") == "owner"
        await finish_event("evt-1", delivered=True)
        assert await claim_event("evt-1") == "done"
        assert await claim_event("") == "owner"
        assert await claim_event(None) == "owner"

    asyncio.run(scenario())
