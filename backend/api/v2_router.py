from fastapi import APIRouter

from .projects import router as projects_router
from .chapters import router as chapters_router
from .outlines import router as outlines_router
from .graph import router as graph_router
from .engine import router as engine_router
from .generate import router as generate_router
from .chat import router as chat_router
from .stage import router as stage_router

router = APIRouter(prefix="/api/v2", tags=["v2"])

router.include_router(projects_router)
router.include_router(chapters_router)
router.include_router(outlines_router)
router.include_router(graph_router)
router.include_router(engine_router)
router.include_router(generate_router)
router.include_router(chat_router)
router.include_router(stage_router)
