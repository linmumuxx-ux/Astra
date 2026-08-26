from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.bootstrap import bootstrap_employees
from app.config.settings import get_settings
from app.database import SessionLocal, init_database
from app.seed import seed_demo_data

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_database()
    if settings.seed_demo:
        async with SessionLocal() as session:
            await seed_demo_data(session)
    else:
        async with SessionLocal() as session:
            await bootstrap_employees(session, settings.config_dir)
    yield


app = FastAPI(
    title="Astra API",
    version="0.2.0",
    description="常驻型数字员工平台 API",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
