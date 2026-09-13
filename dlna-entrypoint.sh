#!/bin/sh
# Интерфейс LAN определяем по маршруту по умолчанию, чтобы не слушать docker-бриджи
iface=$(awk '$2 == "00000000" { print $1; exit }' /proc/net/route)

exec minidlnad -S -f /etc/minidlna.conf -P /run/minidlna/minidlna.pid ${iface:+-i "$iface"} "$@"
