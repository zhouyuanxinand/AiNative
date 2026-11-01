"""Durable local workpackage scheduling with heartbeat and cancellation fencing."""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, store, executor, poll_interval=0.5, lease_seconds=60):
        self.store, self.executor = store, executor
        self.poll_interval, self.lease_seconds = poll_interval, lease_seconds
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def tick(self):
        claim = self.store.claim_node(lease_seconds=self.lease_seconds)
        if claim is None:
            return False
        finished, lost = threading.Event(), threading.Event()

        def heartbeat():
            while not finished.wait(max(0.01, self.lease_seconds / 3)):
                if self._stop.is_set() or not self.store.renew_claim(claim, self.lease_seconds):
                    lost.set()
                    return

        pulse = threading.Thread(target=heartbeat, name="rd-lease-heartbeat", daemon=True)
        pulse.start()

        def cancelled():
            return self._stop.is_set() or lost.is_set() or not self.store.is_claim_active(claim)

        def progress(payload):
            return self.store.progress(claim, payload)

        try:
            execute = getattr(self.executor, "execute", self.executor)
            outcome = execute(claim["action_id"], claim["snapshot"], claim["previous_results"], claim["work_dir"], progress, cancelled)
            if not self._stop.is_set() and not lost.is_set():
                self.store.complete_node(claim, outcome)
        except Exception as error:
            logger.exception("Research action failed: %s", claim["action_id"])
            self.store.complete_node(claim, {"status": "failed", "result": {}, "artifacts": [], "obligations": [],
                                             "blocked_reasons": [f"动作执行异常（{type(error).__name__}），请查看服务日志。"]})
        finally:
            finished.set()
            pulse.join(timeout=1)
        return True

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="rd-workpackage-worker", daemon=True)
            self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                worked = self.tick()
            except Exception:
                logger.exception("Research scheduler tick failed")
                worked = False
            if not worked:
                self._stop.wait(self.poll_interval)

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)
