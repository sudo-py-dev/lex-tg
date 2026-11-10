import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.db.models import FedAdmin, FedBan, FedChat, Federation, FedSubscription
from tests.factories import (
    FedAdminFactory,
    FedBanFactory,
    FedChatFactory,
    FederationFactory,
    FedSubscriptionFactory,
)


@pytest.mark.asyncio
async def test_federation_creation(db_session):
    fed = FederationFactory.build(name="Ultra Fed", ownerId=123)
    db_session.add(fed)
    await db_session.flush()

    result = await db_session.execute(select(Federation).where(Federation.name == "Ultra Fed"))
    fetched = result.scalar_one()
    assert fetched.ownerId == 123
    assert fetched.id is not None


@pytest.mark.asyncio
async def test_federation_duplicate_id(db_session):
    fed1 = FederationFactory.build(id="fed-unique")
    db_session.add(fed1)
    await db_session.flush()
    db_session.expunge(fed1)

    fed2 = FederationFactory.build(id="fed-unique")
    db_session.add(fed2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_fedchat_creation(db_session):
    fed = FederationFactory.build()
    db_session.add(fed)
    await db_session.flush()

    fc = FedChatFactory.build(fedId=fed.id, chatId=-100)
    db_session.add(fc)
    await db_session.flush()

    result = await db_session.execute(select(FedChat).where(FedChat.chatId == -100))
    fetched = result.scalar_one()
    assert fetched.fedId == fed.id


@pytest.mark.asyncio
async def test_fedchat_unique_chatId(db_session):
    fed = FederationFactory.build()
    db_session.add(fed)
    await db_session.flush()

    fc1 = FedChatFactory.build(fedId=fed.id, chatId=-111)
    db_session.add(fc1)
    await db_session.flush()

    fc2 = FedChatFactory.build(fedId=fed.id, chatId=-111)
    db_session.add(fc2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_fedchat_fk_violation(db_session):
    fc = FedChatFactory.build(fedId="non-existent")
    db_session.add(fc)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_fedadmin_creation(db_session):
    fed = FederationFactory.build()
    db_session.add(fed)
    await db_session.flush()

    fa = FedAdminFactory.build(fedId=fed.id, userId=444)
    db_session.add(fa)
    await db_session.flush()

    result = await db_session.execute(select(FedAdmin).where(FedAdmin.userId == 444))
    fetched = result.scalar_one()
    assert fetched.fedId == fed.id


@pytest.mark.asyncio
async def test_fedban_creation(db_session):
    fed = FederationFactory.build()
    db_session.add(fed)
    await db_session.flush()

    fb = FedBanFactory.build(fedId=fed.id, userId=555, reason="bad actor")
    db_session.add(fb)
    await db_session.flush()

    result = await db_session.execute(select(FedBan).where(FedBan.userId == 555))
    fetched = result.scalar_one()
    assert fetched.reason == "bad actor"


@pytest.mark.asyncio
async def test_fedsubscription_creation(db_session):
    fed1 = FederationFactory.build()
    fed2 = FederationFactory.build()
    db_session.add_all([fed1, fed2])
    await db_session.flush()

    sub = FedSubscriptionFactory.build(subscriberId=fed1.id, publisherId=fed2.id)
    db_session.add(sub)
    await db_session.flush()

    result = await db_session.execute(
        select(FedSubscription).where(FedSubscription.subscriberId == fed1.id)
    )
    fetched = result.scalar_one()
    assert fetched.publisherId == fed2.id
