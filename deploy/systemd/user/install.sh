#!/usr/bin/env bash
# Install the systemd units into the *user* manager -- no root, no sudo.
#
# The units under deploy/systemd/ target a system-wide install (a dedicated
# `trendstealer` user, /opt/trendstealer, /etc/trendstealer/env). Rather than
# keep a second hand-written copy in sync, this renders those same files for
# `systemctl --user` by rewriting the paths and dropping the directives the
# user manager rejects (User=, and multi-user.target as an install target).
#
# Nothing is enabled or started here: installing the files is reversible,
# enabling the publish timer is what starts posting to a live account. The
# script prints the enable commands and stops.
#
# Usage: deploy/systemd/user/install.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [[ ! -x "$REPO/.venv/bin/trendstealer" ]]; then
    echo "no venv at $REPO/.venv -- run 'make dev' first" >&2
    exit 1
fi
if [[ ! -f "$REPO/.env" ]]; then
    echo "no $REPO/.env -- copy .env.example and fill it in first" >&2
    exit 1
fi

mkdir -p "$DEST"

for src in "$REPO"/deploy/systemd/*.service "$REPO"/deploy/systemd/*.timer; do
    name="$(basename "$src")"
    sed \
        -e '/^User=/d' \
        -e "s#/opt/trendstealer#$REPO#g" \
        -e "s#^EnvironmentFile=.*#EnvironmentFile=$REPO/.env#" \
        -e "s#^ReadWritePaths=.*#ReadWritePaths=$REPO/var %h/.cache#" \
        -e 's#^WantedBy=multi-user.target#WantedBy=default.target#' \
        "$src" > "$DEST/$name"
done

systemctl --user daemon-reload

cat <<EOF
Installed to $DEST:
$(cd "$DEST" && ls viral-*)

Nothing is enabled yet. To start the always-on dashboard:

    systemctl --user enable --now viral-review.service

To let the worker render approved-for-revision items every 2 minutes:

    systemctl --user enable --now viral-worker.timer

The publish timer posts to the live account unattended -- enable it only
once you are happy for that to happen without you watching:

    systemctl --user enable --now viral-publish.timer

User services stop at logout unless lingering is on. Check with:

    loginctl show-user \$USER | grep Linger
EOF
