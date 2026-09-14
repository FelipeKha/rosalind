from fastapi import FastAPI

from rosalind.api.routes import health

app = FastAPI(title="Rosalind")

app.include_router(health.router)
