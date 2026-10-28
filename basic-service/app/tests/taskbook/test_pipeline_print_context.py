"""Generation print callbacks must never capture another request's output."""

from __future__ import annotations

import asyncio
import builtins
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread

import pytest

from src.pipeline_cli import _capture_print, _patch_print, _restore_print


def test_overlapping_generations_receive_only_their_own_prints(capsys):
    first_entered = Event()
    second_entered = Event()
    first_finished = Event()
    captured = {"first": [], "second": []}
    original_print = builtins.print

    def first_job():
        _patch_print(captured["first"].append)
        try:
            first_entered.set()
            assert second_entered.wait(5)
            print("first request event")
        finally:
            _restore_print()
            first_finished.set()

    def second_job():
        assert first_entered.wait(5)
        _patch_print(captured["second"].append)
        try:
            second_entered.set()
            assert first_finished.wait(5)
            print("second request event")
        finally:
            _restore_print()

    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = [executor.submit(first_job), executor.submit(second_job)]
        for job in jobs:
            job.result(timeout=10)

    assert captured == {
        "first": ["first request event"],
        "second": ["second request event"],
    }
    assert capsys.readouterr().out == ""
    assert builtins.print is original_print


def test_unrelated_thread_print_keeps_normal_file_separator_and_end(capsys):
    captured = []
    outputs = []
    _patch_print(captured.append)
    try:

        def unrelated_job():
            output = io.StringIO()
            print("ordinary", "file", sep="|", end="!", file=output, flush=True)
            print("unrelated console output")
            outputs.append(output.getvalue())

        # Production executors intentionally propagate request ContextVars;
        # a genuinely unrelated thread must start without that request context.
        thread = Thread(target=unrelated_job)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert outputs == ["ordinary|file!"]
        print("this request only")
    finally:
        _restore_print()
    assert captured == ["this request only"]
    assert capsys.readouterr().out == "unrelated console output\n"


def test_request_child_executor_inherits_its_own_progress_callback(capsys):
    # Import the same executor context propagation used by real generation.
    from jonhon_taskbook import llm_client  # noqa: F401

    captured = []
    original_print = builtins.print
    with _capture_print(captured.append):
        print("parent request event")
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(print, "child request event").result(timeout=5)
        print("parent request completed")
    assert captured == [
        "parent request event",
        "child request event",
        "parent request completed",
    ]
    assert capsys.readouterr().out == ""
    assert builtins.print is original_print


def test_nested_capture_restores_outer_callback_and_printing_callback_does_not_recurse(
    capsys,
):
    captured = []
    inner = []

    def callback(message):
        captured.append(message)
        print("console:", message)

    _patch_print(callback)
    try:
        print("outer-before")
        _patch_print(inner.append)
        try:
            print("inner-only")
        finally:
            _restore_print()
        print("outer-after")
    finally:
        _restore_print()
    assert captured == ["outer-before", "outer-after"]
    assert inner == ["inner-only"]
    assert capsys.readouterr().out == "console: outer-before\nconsole: outer-after\n"


def test_callback_error_falls_back_to_console_and_restores_print(capsys):
    original_print = builtins.print

    def failing_callback(message):
        raise RuntimeError("synthetic callback failure")

    _patch_print(failing_callback)
    try:
        print("still observable")
    finally:
        _restore_print()
    print("normal output")
    assert capsys.readouterr().out == "still observable\nnormal output\n"
    assert builtins.print is original_print


def test_async_tasks_on_one_thread_keep_independent_callbacks(capsys):
    captured = {"first": [], "second": []}
    original_print = builtins.print

    async def run_overlapping_tasks():
        first_entered = asyncio.Event()
        second_entered = asyncio.Event()
        first_finished = asyncio.Event()

        async def first_job():
            with _capture_print(captured["first"].append):
                first_entered.set()
                await second_entered.wait()
                print("first async event")
            first_finished.set()

        async def second_job():
            await first_entered.wait()
            with _capture_print(captured["second"].append):
                second_entered.set()
                await first_finished.wait()
                print("second async event")

        await asyncio.wait_for(asyncio.gather(first_job(), second_job()), 5)

    asyncio.run(run_overlapping_tasks())
    assert captured == {
        "first": ["first async event"],
        "second": ["second async event"],
    }
    assert capsys.readouterr().out == ""
    assert builtins.print is original_print


def test_aborted_capture_restores_ordinary_print(capsys):
    captured = []
    original_print = builtins.print
    with pytest.raises(KeyboardInterrupt), _capture_print(captured.append):
        print("before interruption")
        raise KeyboardInterrupt()
    print("ordinary after interruption")
    assert captured == ["before interruption"]
    assert capsys.readouterr().out == "ordinary after interruption\n"
    assert builtins.print is original_print
