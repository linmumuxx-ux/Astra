from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.bootstrap import bootstrap_categories, bootstrap_employees
from app.config.settings import get_settings
from app.database import SessionLocal, init_database
from app.runtime.recovery import audit_incomplete_tasks
from app.seed import seed_demo_data

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_database()
    async with SessionLocal() as session:
        await bootstrap_categories(session)
    if settings.seed_demo:
        async with SessionLocal() as session:
            await seed_demo_data(session)
    else:
        async with SessionLocal() as session:
            await bootstrap_employees(session, settings.config_dir)
    async with SessionLocal() as session:
        await audit_incomplete_tasks(session, settings)
    yield


app = FastAPI(
    title="Astra API",
    version="0.4.0",
    description="长期数字员工任务分配、工作观察、人工介入和结果管理 API",
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
