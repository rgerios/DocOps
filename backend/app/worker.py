"""Worker de coletas: `python -m app.worker`."""
import logging

from redis import Redis
from rq import Queue, Worker

from .config import settings
from .main import bootstrap

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

def recover_interrupted():
    """Coletas que estavam 'running' quando o worker caiu nunca vão terminar: marca como falhas."""
    from datetime import datetime, timezone
    from sqlalchemy import update
    from .db import SessionLocal
    from .models import Collection
    with SessionLocal() as db:
        db.execute(update(Collection).where(Collection.status == "running").values(
            status="failed", error="Coleta interrompida (worker reiniciado). Dispare novamente.", finished_at=datetime.now(timezone.utc)))
        db.commit()


if __name__ == "__main__":
    bootstrap()
    recover_interrupted()
    conn = Redis.from_url(settings.redis_url)
    Worker([Queue("collections", connection=conn)], connection=conn).work(with_scheduler=False)
