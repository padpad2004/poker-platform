from fastapi import FastAPI
from fastapi.security import OAuth2PasswordBearer
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app import models
from app.auth import router as auth_router
from app.clubs import router as clubs_router
from app import routes_user

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Poker Platform MVP")

app.mount("/static", StaticFiles(directory="static"), name="static")


# ---- ADD OAUTH2 SECURITY SCHEME (THIS CREATES THE AUTHORIZE BUTTON) ----

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

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
                    "tokenUrl": "/auth/login",
                    "scopes": {}
                }
            }
        }
    }

    openapi_schema["security"] = [{"OAuth2PasswordBearer": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# -----------------------------------------------------------------------

# Include your existing routers
app.include_router(auth_router)
app.include_router(clubs_router)
app.include_router(routes_user.router)

# Serve static/index.html at the root URL
app.mount("/", StaticFiles(directory="static", html=True), name="static")
