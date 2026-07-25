"""Admin-editable runtime settings, stored in the database.

Distinct from :mod:`app.config`, which is environment-driven and fixed at
process start. This is for values an admin reasonably expects to change from
the Settings UI without restarting the stack — starting with the local clip
storage directory.
"""
