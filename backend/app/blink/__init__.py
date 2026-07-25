"""Blink integration boundary.

Everything Blink-specific flows through :class:`app.blink.service.BlinkService`.
blinkpy (arriving with the Blink-integration feature) is only ever imported
inside this package, so an upstream API change or abandonment is contained to
one module.
"""
