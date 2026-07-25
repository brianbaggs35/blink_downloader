"""Clip byte storage, behind an adapter.

Local disk today; S3/Google Drive/OneDrive land later as additional
implementations of the same :class:`~app.storage.service.ClipStorage`
protocol (see docs/ROADMAP.md) — application code should only ever depend on
that protocol, never on filesystem specifics.
"""
