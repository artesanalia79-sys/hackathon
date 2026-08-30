from fastapi import APIRouter

from api.routes import alerts, control, incidents, stream

router = APIRouter(prefix="/api")
router.include_router(incidents.router)
router.include_router(control.router)
router.include_router(stream.router)
router.include_router(alerts.router)
