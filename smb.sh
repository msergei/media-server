#!/bin/bash
set -euo pipefail

SMB_USER=smbuser
SMB_GROUP=smbgroup
SMB_CONF=/etc/samba/smb.conf
SMB_CONF_BASE=/etc/samba/smb.conf.base
SHARE_PATH=/share

SMB_UID="${PUID:-1000}"
SMB_GID="${PGID:-200}"
LOGIN_USER="${USER:?USER is required}"
LOGIN_PASS="${PASS:?PASS is required}"

strip_share_sections() {
    awk '
        /^\[share\][[:space:]]*$/ { skip = 1; next }
        /^\[/ { skip = 0 }
        !skip { print }
    ' "$1"
}

if getent group "$SMB_GROUP" >/dev/null; then
    existing_gid="$(getent group "$SMB_GROUP" | cut -d: -f3)"
    if [ "$existing_gid" != "$SMB_GID" ]; then
        echo "Group $SMB_GROUP already exists with gid $existing_gid, expected $SMB_GID" >&2
        exit 1
    fi
else
    groupadd -g "$SMB_GID" "$SMB_GROUP"
    echo "Added group $SMB_GROUP with gid $SMB_GID"
fi

if id "$SMB_USER" >/dev/null 2>&1; then
    existing_uid="$(id -u "$SMB_USER")"
    existing_gid="$(id -g "$SMB_USER")"
    if [ "$existing_uid" != "$SMB_UID" ] || [ "$existing_gid" != "$SMB_GID" ]; then
        echo "User $SMB_USER already exists as $existing_uid:$existing_gid, expected $SMB_UID:$SMB_GID" >&2
        exit 1
    fi
else
    useradd -g "$SMB_GROUP" -M -u "$SMB_UID" "$SMB_USER"
    echo "Added user $SMB_USER with uid $SMB_UID"
fi

if ! id "$LOGIN_USER" >/dev/null 2>&1; then
    useradd -M "$LOGIN_USER"
    echo "Added login user $LOGIN_USER"
fi

if pdbedit -L -u "$LOGIN_USER" >/dev/null 2>&1; then
    printf '%s\n%s\n' "$LOGIN_PASS" "$LOGIN_PASS" | smbpasswd -s "$LOGIN_USER" >/dev/null
else
    printf '%s\n%s\n' "$LOGIN_PASS" "$LOGIN_PASS" | smbpasswd -s -a "$LOGIN_USER" >/dev/null
fi

if [ ! -f "$SMB_CONF_BASE" ]; then
    strip_share_sections "$SMB_CONF" > "$SMB_CONF_BASE"
fi

tmp_conf="$(mktemp)"
trap 'rm -f "$tmp_conf"' EXIT

strip_share_sections "$SMB_CONF_BASE" > "$tmp_conf"
{
    echo "[share]"
    echo "path = \"$SHARE_PATH\""
    echo "read only = no"
    echo "valid users = $LOGIN_USER"
} >> "$tmp_conf"

mv "$tmp_conf" "$SMB_CONF"
trap - EXIT

echo "Cat smb.conf file:"
cat "$SMB_CONF"

#Update permissions once (marker survives restarts in the share volume;
# remove the marker to force a full re-chown)
PERMS_MARKER="$SHARE_PATH/.smb_perms_done"
if [ ! -f "$PERMS_MARKER" ]; then
    echo "First run: fixing ownership of $SHARE_PATH..."
    chown -R "$SMB_USER" "$SHARE_PATH"
    touch "$PERMS_MARKER"
    chown "$SMB_USER" "$PERMS_MARKER"
fi

echo "Start samba process..."
exec smbd -F --configfile="$SMB_CONF" --no-process-group </dev/null
