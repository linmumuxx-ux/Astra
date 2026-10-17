import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.environment_routes import router as environment_router
from app.api.gateway_routes import gateway_error_handler
from app.api.gateway_routes import router as gateway_router
from app.api.library_routes import library_error_handler
from app.api.library_routes import router as library_router
from app.api.routes import router
from app.api.worker_routes import router as worker_router
from app.api.workspace_routes import router as workspace_router
from app.assistant.api import router as assistant_router
from app.assistant.orchestrator import AssistantOrchestrator, get_orchestrator, set_orchestrator
from app.bootstrap import bootstrap_categories, bootstrap_employees, bootstrap_knowledge_spaces
from app.config.settings import get_settings
from app.database import SessionLocal, init_database
from app.gateway.security import CredentialError
from app.gateway.service import GatewayError
from app.library_service import LibraryError
from app.runtime.recovery import supervise_sessions
from app.seed import seed_demo_data
from app.worker_gateway.routes import router as worker_gateway_router

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_database()
    async with SessionLocal() as session:
        await bootstrap_categories(session)
        await bootstrap_knowledge_spaces(session)
    if settings.seed_demo:
        async with SessionLocal() as session:
            await seed_demo_data(session)
    else:
        async with SessionLocal() as session:
            await bootstrap_employees(session, settings.resolved_config_dir)
    from app.worker_gateway.admin_key import warn_if_admin_key_missing
    from app.worker_gateway.service import sweep_worker_gateway

    warn_if_admin_key_missing(settings.worker_gateway_admin_key)
    supervisor = asyncio.create_task(supervise_sessions())
    worker_sweep = asyncio.create_task(sweep_worker_gateway())
    # 平台助手是增强能力：启动失败不得影响核心任务执行链。
    # 已注入 Orchestrator（测试 / 嵌入式部署）时保持原有实例。
    if settings.assistant_enabled and get_orchestrator() is None:
        try:
            orchestrator = AssistantOrchestrator(settings)
            set_orchestrator(orchestrator)
            await orchestrator.start()
        except Exception:
            set_orchestrator(None)
    try:
        yield
    finally:
        supervisor.cancel()
        worker_sweep.cancel()
        await asyncio.gather(supervisor, worker_sweep, return_exceptions=True)
        orchestrator = get_orchestrator()
        if orchestrator:
            await orchestrator.stop()
            set_orchestrator(None)
        from app.executors.opencode_remote_server import close_remote_mcp_tunnels
        from app.worker_gateway.service import get_gateway

        await get_gateway().aclose()
        await close_remote_mcp_tunnels()


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
app.include_router(worker_router)
app.include_router(worker_gateway_router)
app.include_router(environment_router)
app.include_router(workspace_router)
app.include_router(library_router)
app.include_router(assistant_router)
app.include_router(gateway_router)
app.add_exception_handler(LibraryError, library_error_handler)
app.add_exception_handler(GatewayError, gateway_error_handler)
app.add_exception_handler(CredentialError, gateway_error_handler)
