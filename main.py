from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
from fastapi.openapi.utils import get_openapi

from app.database import Base, engine
from app import models
from app.auth import router as auth_router
from app.clubs import router as clubs_router
from app.tables_api import router as tables_router
from app import routes_user
from app.ws_api import ws_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Poker Platform MVP")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="Poker Platform MVP",
        version="1.0.0",
        description="API for the poker platform",
        routes=app.routes,
    )

    openapi_schema["components"]["securitySchemes"] = {
        "OAuth2PasswordBearer": {
            "type": "oauth2",
            "flows": {
                "password": {
                    "tokenUrl": "/auth/token",
                    "scopes": {}
                }
            }
        }
    }

    openapi_schema["security"] = [{"OAuth2PasswordBearer": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# ---- Include all routers ----
app.include_router(auth_router)          # /auth/...
app.include_router(clubs_router)         # /clubs/...
app.include_router(routes_user.router)   # /me, /wallet/topup, /me/club
app.include_router(tables_router)        # /tables/...
app.include_router(ws_router)            # /ws/tables/{id}

# ---- Static files (/static/...) ----
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def read_root():
    return {"status": "ok"}
