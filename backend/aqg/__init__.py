"""aqg: the pure-Python core of AI Quality Gate.

This package holds everything the standalone gate needs: the quality-evidence
model (M1) and, in later milestones, importers, policy, baselines and the CLI.

It must stay light enough to install into any project's CI. It never imports
FastAPI, SQLite, OpenTelemetry, LangChain or AI SDKs, and it never imports the
``app`` server package. ``tests/aqg/test_import_isolation.py`` enforces this.
"""
