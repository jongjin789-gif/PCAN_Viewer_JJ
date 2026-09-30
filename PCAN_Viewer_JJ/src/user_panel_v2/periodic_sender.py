"""Bus-local periodic transmission, independent of the Qt GUI event loop."""
import threading
import time


class PeriodicTask:
    def __init__(self, sender, runtime):
        self.sender, self.runtime = sender, runtime
        self.lock = threading.RLock()
        self.active = True
        self.period = runtime.packet['cycle'] / 1000.0
        self.deadline = time.perf_counter() + self.period
        self.sent = self.missed = 0
        self.max_lateness_ms = 0.0

    def stop(self):
        # Once this returns, an in-flight send has completed and no new one can start.
        with self.lock:
            self.active = False
        with self.sender.condition:
            self.sender.tasks.discard(self)
            self.sender.condition.notify_all()

    def deleteLater(self):
        self.stop()

    def isActive(self):
        return self.active


class PeriodicSender:
    def __init__(self, bus, completed, failed):
        self.completed, self.failed = completed, failed
        self.condition = threading.Condition()
        self.tasks = set()
        self.closed = False
        self.thread = threading.Thread(target=self._run, name=f'Panel TX BUS {bus}', daemon=True)
        self.thread.start()

    def add(self, runtime):
        task = PeriodicTask(self, runtime)
        with self.condition:
            self.tasks.add(task)
            self.condition.notify_all()
        return task

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.thread.join()

    def _run(self):
        while True:
            with self.condition:
                if self.closed:
                    return
                if not self.tasks:
                    self.condition.wait()
                    continue
                task = min(self.tasks, key=lambda item: item.deadline)
                delay = task.deadline - time.perf_counter()
                if delay > 0:
                    self.condition.wait(delay)
                    continue
            with task.lock:
                if not task.active:
                    continue
                started = time.perf_counter()
                task.max_lateness_ms = max(task.max_lateness_ms, (started-task.deadline)*1000)
                try:
                    payload = task.runtime.send(record=False)
                except Exception as exc:
                    task.stop()
                    self.failed(task, str(exc))
                    continue
                sent_at = time.time()
                task.sent += 1
                finished = time.perf_counter()
                following = task.deadline + task.period
                if following <= finished:
                    task.missed += int((finished-following)/task.period) + 1
                    following = finished + task.period  # Never burst to replay missed periods.
                task.deadline = following
                self.completed(task, payload, sent_at)
