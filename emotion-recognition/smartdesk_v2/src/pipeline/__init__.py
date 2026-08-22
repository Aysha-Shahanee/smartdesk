"""Pipeline controllers for project runtime flows."""

from src.pipeline.session_schedule import SmartDeskSessionSchedule, build_smartdesk_session_schedule


def __getattr__(name: str):
    if name in {"SmartDeskFrameResult", "SmartDeskPipeline", "SmartDeskPipelineUpdate"}:
        from src.pipeline.smartdesk_pipeline import SmartDeskFrameResult, SmartDeskPipeline, SmartDeskPipelineUpdate

        return {
            "SmartDeskFrameResult": SmartDeskFrameResult,
            "SmartDeskPipeline": SmartDeskPipeline,
            "SmartDeskPipelineUpdate": SmartDeskPipelineUpdate,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "SmartDeskFrameResult",
    "SmartDeskPipeline",
    "SmartDeskPipelineUpdate",
    "SmartDeskSessionSchedule",
    "build_smartdesk_session_schedule",
]
