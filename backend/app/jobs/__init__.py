"""Minimum job/artifact substrate for Gjallar MVP workflows."""

from app.jobs.models import ApprovalRecord, ArtifactRecord, JobRecord

__all__ = ["ApprovalRecord", "ArtifactRecord", "JobRecord"]
