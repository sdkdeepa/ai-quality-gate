"""Adapters turn existing AI Quality Gate results into quality evidence."""

from aqg.adapters.llm import PROVIDER_CHECK_NAME, evidence_from_llm_run, metric_status

__all__ = ["PROVIDER_CHECK_NAME", "evidence_from_llm_run", "metric_status"]
