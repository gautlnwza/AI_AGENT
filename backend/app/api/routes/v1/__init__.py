"""API v1 router aggregation."""  # ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from fastapi import APIRouter

from app.api.routes.v1 import (
    admin_stats,
    admin_users,
    agent,
    auth,
    files,
    health,
    items,
    oauth,
    users,
)

v1_router = APIRouter()

# Health check routes (no auth required)
v1_router.include_router(health.router, tags=["health"])
# Authentication routes
v1_router.include_router(auth.router, prefix="/auth", tags=["auth"])

# User routes
v1_router.include_router(users.router, prefix="/users", tags=["users"])
# OAuth2 routes
v1_router.include_router(oauth.router, prefix="/oauth", tags=["oauth"])
# File upload/download routes
v1_router.include_router(files.router, tags=["files"])
# AI chat WebSocket + model listing
v1_router.include_router(agent.router, tags=["agent"])
# Admin: user management + impersonation
v1_router.include_router(admin_users.router, prefix="/admin/users", tags=["admin:users"])
v1_router.include_router(admin_stats.router, prefix="/admin", tags=["admin:stats"])
# Example Item CRUD (reference scaffold — safe to delete once you've added your own domain)
v1_router.include_router(items.router, prefix="/items", tags=["items"])
