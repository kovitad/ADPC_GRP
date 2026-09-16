from enum import StrEnum


class AssessmentState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CenterStatus(StrEnum):
    POTENTIALLY_EXPOSED = "potentially_exposed"
    NOT_EXPOSED_UNDER_SCENARIO = "not_exposed_under_scenario"
    UNABLE_TO_ASSESS = "unable_to_assess"
