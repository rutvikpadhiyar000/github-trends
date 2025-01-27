from datetime import date, datetime, timedelta
from typing import Optional

from src.data.mongo.secret.functions import update_keys
from src.data.mongo.user import (
    UserMetadata,
    UserModel,
    get_user_by_user_id,
    get_user_metadata,
)
from src.models import UserPackage
from src.publisher.aggregation import trim_package
from src.publisher.processing.pubsub import publish_user

# TODO: replace with call to subscriber so compute not on publisher
from src.subscriber.aggregation import get_user_data
from src.utils import alru_cache


def validate_raw_data(data: Optional[UserPackage]) -> bool:
    """Returns False if invalid data"""
    # NOTE: add more validation as more fields are required
    if data is None or data.contribs is None:
        return False

    if (
        data.contribs.total_stats.commits_count > 0
        and len(data.contribs.total_stats.languages) == 0
    ):
        return False

    return True


def validate_dt(dt: Optional[datetime], td: timedelta):
    """Returns false if invalid date"""
    last_updated = dt if dt is not None else datetime(1970, 1, 1)
    time_diff = datetime.now() - last_updated
    return time_diff <= td


async def update_user(user_id: str, access_token: Optional[str] = None) -> bool:
    """Sends a message to pubsub to request a user update (auto cache updates)"""
    if access_token is None:
        user: Optional[UserMetadata] = await get_user_metadata(user_id)
        if user is None:
            return False
        access_token = user.access_token
    publish_user(user_id, access_token)
    return True


async def _get_user(user_id: str, no_cache: bool = False) -> Optional[UserPackage]:
    db_user: Optional[UserModel] = await get_user_by_user_id(user_id, no_cache=no_cache)
    if db_user is None or db_user.access_token == "":
        raise LookupError("Invalid UserId")

    valid_dt = validate_dt(db_user.last_updated, timedelta(hours=6))
    if not valid_dt or not validate_raw_data(db_user.raw_data):
        if not validate_dt(db_user.lock, timedelta(minutes=1)):
            await update_user(user_id, db_user.access_token)

    if validate_raw_data(db_user.raw_data):
        return db_user.raw_data  # type: ignore

    return None


@alru_cache()
async def get_user(
    user_id: str,
    start_date: date,
    end_date: date,
    no_cache: bool = False,
) -> Optional[UserPackage]:
    output = await _get_user(user_id, no_cache=no_cache)

    if output is None:
        return (False, None)  # type: ignore

    output = trim_package(output, start_date, end_date)

    # TODO: handle timezone_str here

    return (True, output)  # type: ignore


@alru_cache(ttl=timedelta(minutes=15))
async def get_user_demo(
    user_id: str, start_date: date, end_date: date, no_cache: bool = False
) -> UserPackage:
    await update_keys()
    timezone_str = "US/Eastern"
    data = await get_user_data(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        timezone_str=timezone_str,
        access_token=None,
    )
    return (True, data)  # type: ignore
