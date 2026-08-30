from fastapi import APIRouter

from api.routes import control, incidents, stream

router = APIRouter(prefix="/api")
router.include_router(incidents.router)
router.include_router(control.router)
router.include_router(stream.router)
