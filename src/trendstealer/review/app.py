"""The human review gate's UI.

Every write here goes through repo.transition(), which re-validates the
edge against states.TRANSITIONS regardless of what this route already
checked — ACTION_TO_STATUS below and repo.transition()'s own guard are two
independent checks on the same bypass the original architecture doc had
(`UPDATE ... SET status = ?` from a raw request.form value).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, cast

from flask import (
    Flask,
    Response,
    abort,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_wtf import CSRFProtect
from werkzeug.wrappers import Response as WerkzeugResponse

from trendstealer import db as db_module
from trendstealer import repo
from trendstealer.review.auth import check_allowed_host, check_bearer_token
from trendstealer.states import (
    MAX_REVISIONS,
    ContentStatus,
    InvalidTransitionError,
    StaleStateError,
)

ACTION_TO_STATUS: dict[str, ContentStatus] = {
    "approve": ContentStatus.APPROVED,
    "reject": ContentStatus.REJECTED,
    "request_changes": ContentStatus.CHANGES_REQUESTED,
}

PAGE_SIZE = 20


def create_app(
    *,
    db_path: Path,
    render_root: Path,
    token: str,
    allowed_hosts: set[str] | None = None,
    secret_key: str | None = None,
) -> Flask:
    if not token:
        raise ValueError("review dashboard token must not be empty")

    app = Flask(__name__)
    app.config["SECRET_KEY"] = secret_key or "dev-only-change-me"
    app.config["TRENDSTEALER_DB_PATH"] = db_path
    app.config["TRENDSTEALER_RENDER_ROOT"] = render_root.resolve()
    app.config["TRENDSTEALER_TOKEN"] = token
    app.config["TRENDSTEALER_ALLOWED_HOSTS"] = allowed_hosts or {
        "127.0.0.1:5000",
        "localhost:5000",
    }
    app.config["WTF_CSRF_TIME_LIMIT"] = None

    CSRFProtect(app)

    @app.before_request
    def _security_gate() -> None:
        if not check_allowed_host(request, app.config["TRENDSTEALER_ALLOWED_HOSTS"]):
            abort(400)
        # The token check re-validates every request (stateless, correct for
        # curl/API use). The session flag is purely a convenience so a human
        # clicking through the dashboard doesn't need ?token= on every link
        # -- it's set below only after a real token check already passed,
        # so it grants nothing check_bearer_token wouldn't have granted.
        if check_bearer_token(request, app.config["TRENDSTEALER_TOKEN"]):
            session["authed"] = True
            return
        if not session.get("authed"):
            abort(401)

    @app.after_request
    def _security_headers(response: Response) -> Response:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'none'; object-src 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.teardown_appcontext
    def _close_db(_exc: BaseException | None) -> None:
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = db_module.connect(app.config["TRENDSTEALER_DB_PATH"])
        return g.db  # type: ignore[no-any-return]

    @app.route("/")
    def index() -> WerkzeugResponse:
        return redirect(url_for("queue"))

    @app.route("/queue")
    def queue() -> str:
        conn = get_db()
        page = max(1, request.args.get("page", 1, type=int))
        offset = (page - 1) * PAGE_SIZE
        items = repo.list_items_for_review(
            conn, ContentStatus.PENDING_REVIEW, limit=PAGE_SIZE, offset=offset
        )
        total = repo.count_items_by_status_value(conn, ContentStatus.PENDING_REVIEW)
        in_flight = repo.list_items_in_flight(conn) if page == 1 else []
        return render_template(
            "queue.html",
            items=items,
            page=page,
            page_size=PAGE_SIZE,
            total=total,
            in_flight=in_flight,
        )

    @app.route("/item/<int:item_id>")
    def item_detail(item_id: int) -> str:
        conn = get_db()
        detail = repo.get_item_detail(conn, item_id)
        if detail is None:
            abort(404)
        latest_revision_no = repo.get_latest_revision_no(conn, item_id)
        revision_cap_reached = (
            latest_revision_no is not None and latest_revision_no >= MAX_REVISIONS
        )
        return render_template("item.html", item=detail, revision_cap_reached=revision_cap_reached)

    @app.route("/item/<int:item_id>/action", methods=["POST"])
    def item_action(item_id: int) -> WerkzeugResponse:
        conn = get_db()
        action = request.form.get("action", "")
        if action not in ACTION_TO_STATUS:
            abort(400)

        item = repo.get_content_item(conn, item_id)
        if item is None:
            abort(404)

        try:
            expected_version = int(request.form.get("version", ""))
        except ValueError:
            abort(400)

        note = request.form.get("note") or None
        to_status = ACTION_TO_STATUS[action]

        if to_status == ContentStatus.CHANGES_REQUESTED:
            latest_revision_no = repo.get_latest_revision_no(conn, item_id)
            if latest_revision_no is not None and latest_revision_no >= MAX_REVISIONS:
                abort(409)

        try:
            repo.transition(
                conn,
                item_id,
                ContentStatus(item["status"]),
                to_status,
                actor="dashboard",
                note=note,
                expected_version=expected_version,
            )
        except (InvalidTransitionError, StaleStateError):
            abort(409)

        return redirect(url_for("queue"))

    @app.route("/media/<int:item_id>/video")
    def media_video(item_id: int) -> Response:
        conn = get_db()
        detail = repo.get_item_detail(conn, item_id)
        if detail is None:
            abort(404)

        current_revision_id = detail["current_revision_id"]
        revisions = cast(list[dict[str, Any]], detail["revisions"])
        revision = next((r for r in revisions if r["id"] == current_revision_id), None)
        if revision is None or not revision.get("video_path"):
            abort(404)

        video_path = Path(revision["video_path"]).resolve()
        render_root = app.config["TRENDSTEALER_RENDER_ROOT"]
        if not video_path.is_relative_to(render_root):
            abort(400)
        if not video_path.exists():
            abort(404)

        return send_file(video_path, conditional=True)

    return app
