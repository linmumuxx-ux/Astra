import asyncio

from agent_service import claim_event, finish_event


def test_same_event_is_delivered_once_until_failure_releases_it():
    async def scenario():
        assert await claim_event("evt-1") is True
        assert await claim_event("evt-1") is False
        await finish_event("evt-1", delivered=False)
        assert await claim_event("evt-1") is True
        await finish_event("evt-1", delivered=True)
        assert await claim_event("evt-1") is False
        assert await claim_event("") is True

    asyncio.run(scenario())
