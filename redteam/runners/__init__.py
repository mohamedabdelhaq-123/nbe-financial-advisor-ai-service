"""Infrastructure that drives the application for a red-team scenario:
a fake chat-model double that records exactly what it was called with (no
network, no API key), an SSE response parser, and a thin chat-turn helper.
"""
