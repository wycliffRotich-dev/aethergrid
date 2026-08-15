from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.application.services.list_events_service import (
    ListEventsService,
)
from app.presentation.auth import (
    require_api_key,
    require_rate_limit,
)
from app.presentation.dependencies import (
    get_list_events_service,
)
from app.presentation.schemas.list_events_response import (
    EventResponse,
    ListEventsResponse,
)

router = APIRouter(
    prefix="/events",
    tags=["Events"],
    dependencies=[
        Depends(require_api_key),
        Depends(require_rate_limit),
    ],
)


@router.get(
    "",
    response_model=ListEventsResponse,
    status_code=status.HTTP_200_OK,
)
def list_events(
    service: Annotated[
        ListEventsService,
        Depends(get_list_events_service),
    ],
) -> ListEventsResponse:
    """
    Return every recorded domain event across the cluster,
    in the order they occurred. Backs the dashboard's live
    event feed.
    """
    events = service.execute()

    return ListEventsResponse(
        events=[
            EventResponse(
                id=str(event.id),
                aggregate_id=event.aggregate_id,
                aggregate_type=event.aggregate_type,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                payload=event.payload,
            )
            for event in events
        ]
    )
