from fastapi import APIRouter
from app.api.trace import router as trace_router

api_router = APIRouter()
api_router.include_router(trace_router, tags=["Trace"])
