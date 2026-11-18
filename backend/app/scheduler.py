"""Agendador: verifica os agendamentos a cada 30 s e enfileira as coletas devidas. `python -m app.scheduler`."""
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .main import bootstrap
from .models import AwsAccount, Collection, Schedule
from .services import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("docops.scheduler")
TZ = ZoneInfo(settings.timezone)


def tick(now: datetime | None = None) -> int:
    now = now or datetime.now(TZ)
    fired = 0
    with SessionLocal() as db:
        for s in db.scalars(select(Schedule).where(Schedule.enabled.is_(True))):
            if not croniter.is_valid(s.cron):
                continue
            base = (s.last_run or s.created_at).astimezone(TZ)
            if croniter(s.cron, base).get_next(datetime) > now:
                continue
            s.last_run = now
            db.commit()
            q = select(AwsAccount).where(AwsAccount.tenant_id == s.tenant_id, AwsAccount.active.is_(True), AwsAccount.role_arn.is_not(None))
            if s.account_ids:
                q = q.where(AwsAccount.id.in_(s.account_ids))
            for acc in db.scalars(q).all():
                busy = db.scalar(select(Collection).where(Collection.aws_account_id == acc.id, Collection.status.in_(("queued", "running"))))
                if busy:
                    continue
                pipeline.enqueue_collection(db, acc, "schedule", None)
                fired += 1
            log.info("agendamento '%s' (cliente %s) disparado", s.name, s.tenant_id)
    return fired


if __name__ == "__main__":
    bootstrap()
    log.info("agendador iniciado (fuso %s)", settings.timezone)
    while True:
        try:
            tick()
        except Exception:  # noqa: BLE001
            log.exception("falha no ciclo do agendador")
        time.sleep(30)
