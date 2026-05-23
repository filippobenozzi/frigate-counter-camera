"""Auth: login form + HTTP Basic Auth per API.

Se AUTH_USER e AUTH_PASS NON sono settate -> tutto pubblico (come prima).
"""

from functools import wraps
from hmac import compare_digest

from flask import Response, redirect, request, session, url_for

from app.config import Config


def credentials_match(user: str, pwd: str) -> bool:
    if not Config.auth_enabled():
        return False
    return (
        compare_digest(user or "", Config.AUTH_USER)
        and compare_digest(pwd or "", Config.AUTH_PASS)
    )


def is_logged_in() -> bool:
    """Vero se la richiesta corrente è autenticata in QUALCHE modo."""
    if not Config.auth_enabled():
        return True
    # 1) sessione cookie (form login)
    if session.get("auth_user") == Config.AUTH_USER:
        return True
    # 2) HTTP Basic Auth (utile per curl / script)
    a = request.authorization
    if a and credentials_match(a.username, a.password):
        return True
    return False


def login_required(fn):
    """Protegge una view. Sotto /api/ risponde 401 Basic; altrove redirect a /login."""
    @wraps(fn)
    def wrap(*args, **kwargs):
        if is_logged_in():
            return fn(*args, **kwargs)
        if request.path.startswith("/api/"):
            return Response(
                "Authentication required\n",
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="counter"'},
            )
        return redirect(url_for("login", next=request.path))
    return wrap
