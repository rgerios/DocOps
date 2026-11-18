#!/bin/sh
# Backup diário do PostgreSQL em disco local (pasta ./backups do servidor).
# Roda dentro do container "backup": faz um dump na hora BACKUP_HOUR e apaga dumps mais antigos que BACKUP_RETENTION_DAYS.
set -eu
HOUR="${BACKUP_HOUR:-2}"
KEEP="${BACKUP_RETENTION_DAYS:-14}"

dump() {
  f="/backups/docops_$(date +%Y%m%d_%H%M).dump"
  if pg_dump -Fc -f "$f.tmp"; then
    mv "$f.tmp" "$f"
    echo "$(date '+%F %T') backup ok: $f ($(du -h "$f" | cut -f1))"
  else
    rm -f "$f.tmp"; echo "$(date '+%F %T') ERRO no backup" >&2
  fi
  find /backups -name 'docops_*.dump' -mtime +"$KEEP" -delete
}

[ "${1:-}" = "--once" ] && { dump; exit 0; }   # backup manual

echo "agendador de backup: todo dia às ${HOUR}h, retenção de ${KEEP} dias"
[ -n "$(ls /backups/docops_*.dump 2>/dev/null)" ] || dump   # primeiro backup imediato
while true; do
  now=$(date +%s)
  next=$(date -d "$(date +%F) ${HOUR}:00:00" +%s 2>/dev/null || date -D '%Y-%m-%d %H:%M:%S' -d "$(date +%F) ${HOUR}:00:00" +%s)
  [ "$next" -le "$now" ] && next=$((next + 86400))
  sleep $((next - now))
  dump
done
