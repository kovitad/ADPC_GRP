"""Flood evidence for the operational flood pilots (ADR-0038).

Sources are read by adapters into one observation shape. The worker fetches and stores them; the
API only reads what is stored. Pilot-specific values live in ``core/data/flood_pilot_*.json``.
"""
