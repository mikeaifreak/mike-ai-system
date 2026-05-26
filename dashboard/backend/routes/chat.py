from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from auth import get_current_user
from db import get_conn
from nova import stream_nova_response

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be empty")
        if len(v) > 500:
            raise ValueError("message must be 500 characters or fewer")
        return v


@router.post("/")
async def chat(
    body: ChatRequest,
    current_user: str = Depends(get_current_user),
):
    async def event_stream():
        try:
            with get_conn() as conn:
                async for chunk in stream_nova_response(body.message, conn):
                    yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
