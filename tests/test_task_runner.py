import threading
import time

from PySide6.QtCore import QThread

from app.core.task_runner import TaskRunner


def test_result_delivered_on_gui_thread(qtbot):
    runner = TaskRunner()
    main_thread = QThread.currentThread()
    seen = {}

    def work():
        seen["worker_thread"] = threading.current_thread().name
        return 42

    def on_result(v):
        seen["value"] = v
        seen["callback_on_main"] = QThread.currentThread() is main_thread

    runner.submit(work, on_result=on_result, on_finished=lambda: seen.setdefault("done", True))
    qtbot.waitUntil(lambda: bool(seen.get("done")), timeout=3000)
    assert seen["value"] == 42
    assert seen["callback_on_main"]
    assert seen["worker_thread"] != threading.main_thread().name
    assert runner.active_count == 0


def test_error_delivered_not_swallowed(qtbot):
    runner = TaskRunner()
    errors = []

    def boom():
        raise RuntimeError("bad")

    runner.submit(boom, on_error=errors.append)
    qtbot.waitUntil(lambda: bool(errors), timeout=3000)
    assert isinstance(errors[0], RuntimeError)


def test_unhandled_error_is_logged(qtbot, caplog):
    runner = TaskRunner()
    done = []
    runner.submit(lambda: 1 / 0, on_finished=lambda: done.append(1), name="divide")
    qtbot.waitUntil(lambda: bool(done), timeout=3000)
    assert "divide" in caplog.text


def test_args_and_kwargs_and_concurrency(qtbot):
    runner = TaskRunner(max_threads=4)
    results = []
    for i in range(4):
        runner.submit(lambda x, y=0: (time.sleep(0.2), x + y)[1], i, y=10, on_result=results.append)
    start = time.monotonic()
    qtbot.waitUntil(lambda: len(results) == 4, timeout=3000)
    assert sorted(results) == [10, 11, 12, 13]
    assert time.monotonic() - start < 0.7  # ran in parallel, not 0.8s sequentially
