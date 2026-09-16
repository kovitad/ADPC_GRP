from fastapi import APIRouter

router = APIRouter(tags=["access"])

# Increment 2: load active Hub membership and role from the database per request.
