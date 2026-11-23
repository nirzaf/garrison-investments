from fastapi import APIRouter, Response

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.feedback import FeedbackCreate, FeedbackReceipt
from app.services.feedback_service import FeedbackService

router = APIRouter(prefix="/feedback", tags=["Feedback"])


@router.post("", status_code=201, response_model=FeedbackReceipt)
async def submit_feedback(
    payload: FeedbackCreate, response: Response, current_user: CurrentUser, session: DbSession
) -> FeedbackReceipt:
    response.headers["Cache-Control"] = "no-store"
    return await FeedbackService(session).submit(current_user, payload)
