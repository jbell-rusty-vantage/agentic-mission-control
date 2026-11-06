"""Vercel ASGI entrypoint; build the reviewed closure before deployment."""

from mission_control.bootstrap.ingress import configured_ingress_app

app = configured_ingress_app()
