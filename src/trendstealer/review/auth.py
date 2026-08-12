"""Access control for the review dashboard.

Localhost-only is *not* by itself safe — any local process, and any page
you visit in a browser on the same machine, can POST to 127.0.0.1:5000.
The bearer token is the actual access control; the Host header check is a
secondary guard against DNS-rebinding-style requests that present a
different Host than the dashboard is configured to answer for.
"""

from __future__ import annotations

import hmac

from flask import Request


def check_bearer_token(request: Request, expected_token: str) -> bool:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        supplied = auth_header[len("Bearer ") :]
    else:
        supplied = request.args.get("token", "")
    return hmac.compare_digest(supplied, expected_token)


def check_allowed_host(request: Request, allowed_hosts: set[str]) -> bool:
    return request.host in allowed_hosts
