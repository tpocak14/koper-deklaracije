"""Pripomočki za safe scheduling background opravil v Flask + Heroku okolju.

Problem: Heroku gunicorn worker thread-i (`threading.Thread.start()`) so
fragile — pri dyno cycling (vsakih 24h) ali OOM kill-u worker-ja se
thread tiho ubije sredi izvajanja. To je še posebej kritično za PDF
generacijo + Mandrill send, kjer izgubljen thread = stranka ne dobi
deklaracije.

Rešitev: namesto thread-a uporabi `schedule_one_shot()`, ki naloži
opravilo v APScheduler. APScheduler:
  - persistira ob restartu (z `coalesce=True` se misfired job ponovi)
  - ima centraliziran error handling in logging
  - omogoča preverjanje statusa preko `scheduler.get_jobs()`

Fallback: če scheduler ni na voljo (npr. v development brez scheduler-ja,
ali v test mode), pademo nazaj na threading.Thread z opozorilom.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Callable

from flask import Flask, current_app

logger = logging.getLogger(__name__)


def schedule_one_shot(
    func: Callable[..., Any],
    *,
    args: tuple = (),
    kwargs: dict | None = None,
    delay_seconds: float = 0,
    job_id: str | None = None,
    app: Flask | None = None,
) -> str:
    """Naroči enkratno opravilo v APScheduler.

    Args:
        func: funkcija, ki naj se izvede. NE SME pričakovati Flask app
            kontekst-a — helper ga zagotovi sam.
        args: positional argumenti za func
        kwargs: keyword argumenti za func
        delay_seconds: koliko sekund čakati pred izvajanjem (0 = takoj)
        job_id: opcionalni ID joba (za deduplication). Če podan in job z
            tem ID-jem že obstaja, vrne obstoječ ID.
        app: Flask app objekt; če None, uporabi current_app.

    Returns:
        Job ID (lahko nov ali obstoječi)

    Raises:
        RuntimeError: če scheduler ni na voljo in fallback ni varen
    """
    kwargs = kwargs or {}
    app_obj = app or current_app._get_current_object()
    scheduler = _get_scheduler(app_obj)

    def _wrapper(*a, **kw):
        with app_obj.app_context():
            try:
                return func(*a, **kw)
            except Exception as e:
                app_obj.logger.error(
                    f"schedule_one_shot job '{job_id or func.__name__}' failed: {e}",
                    exc_info=True,
                )
                raise

    if scheduler is None:
        # Fallback: thread (z opozorilom). To naredi kod backward-kompatibilen
        # za development okolja brez scheduler-ja.
        logger.warning(
            "APScheduler ni na voljo, padam nazaj na threading.Thread za %s. "
            "To je nevarno na Heroku — dyno cycling lahko ubije thread.",
            func.__name__,
        )
        t = threading.Thread(
            target=_wrapper, args=args, kwargs=kwargs, daemon=True
        )
        t.start()
        return f"thread:{t.ident}"

    from datetime import timedelta as _td
    run_date = datetime.now() + _td(seconds=delay_seconds) if delay_seconds > 0 else datetime.now()

    # `coalesce=True` zagotovi, da če APScheduler restarta in misfira ta
    # job, se izvede točno enkrat ob naslednjem startu (ne večkrat).
    job = scheduler.add_job(
        _wrapper,
        args=args,
        kwargs=kwargs,
        trigger='date',
        run_date=run_date,
        id=job_id,
        coalesce=True,
        misfire_grace_time=60 * 30,  # 30 min toleranca po restartu
        replace_existing=True,
    )
    logger.info(
        "Scheduled one-shot job %s (func=%s, run_date=%s)",
        job.id, func.__name__, run_date.isoformat(),
    )
    return job.id


def _get_scheduler(app: Flask):
    """Vrne APScheduler instance ali None."""
    try:
        return app.extensions.get('apscheduler')
    except Exception:
        return None
