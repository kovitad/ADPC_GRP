from fastapi import APIRouter

router = APIRouter(prefix="/integrations/sig", tags=["sig"])

# Increment 3: machine-authenticated, read-only evidence for Admin-shared assessments.
