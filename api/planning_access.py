"""Planning-role or Hub Admin checks shared by planning, catalog and assessments."""

from api.errors import GrpError, not_found
from api.sessions import CurrentPrincipal
from core.access_models import PLANNING_MEMBER_ROLES
from core.identity import MembershipView


def planner_membership(principal: CurrentPrincipal, hub_code: str | None) -> MembershipView:
    """NDMO Planner, Hub Expert / GIS Specialist, or Hub Admin of the selected Hub.

    `hub_code` only picks among the person's own memberships; it never grants access.
    """

    members = [m for m in principal.memberships if m.role in PLANNING_MEMBER_ROLES]
    if hub_code:
        members = [m for m in members if m.hub_code == hub_code.strip().lower()]
        if not members:
            raise not_found()
    if not members:
        raise GrpError(403, "ACCESS_NOT_AUTHORIZED", "Access not authorized.")
    return members[0]
