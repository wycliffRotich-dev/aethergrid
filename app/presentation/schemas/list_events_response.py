from datetime import datetime

from pydantic import BaseModel


class EventResponse(BaseModel):
    """
    A single domain event, as shown on the live event feed.
    """

    id: str
    aggregate_id: str
    aggregate_type: str
    event_type: str
    occurred_at: datetime
    payload: dict[str, str]


class ListEventsResponse(BaseModel):
    """
    HTTP response returned when listing every recorded
    domain event.
    """

    events: list[EventResponse]
