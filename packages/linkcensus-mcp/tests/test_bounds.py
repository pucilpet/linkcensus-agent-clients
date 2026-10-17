import asyncio
import json
import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from linkcensus_mcp.runner import Busy, DeadlineExceeded, SerialRunner
from linkcensus_mcp.tools import MAX_TEXT_BYTES, TOOLS, execute
from linkcensus_mcp.transport import (Admission, Framer, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES,
                                          ReadStream, TransportClosed, WriteStream, contains_secret)

ENVELOPE = {
    "api_version": "v1", "relationship": "candidate", "edition": "fixture-2026-01",
    "ranking_mode": "embedding", "query": "example.com", "resolved_host": "www.example.com",
    "resolution": "www", "total": 9, "gated": True, "truncated": True, "tier": "free",
    "selection_reason": "Link-neighborhood similarity, not confirmed product competition",
    "shared_linkers_scope": "among top 200 retained",
    "filters": {"limit": 5, "min_shared": 0, "tld": None},
    "quota": {"used": 2, "limit": 15, "resets_at": "2026-11-01T00:00:00Z"},
    "results": [{"domain": "candidate.example", "host": "candidate.example", "similarity": 85,
                 "shared_linkers": 3, "shared_linker_names": ["linker.example"], "tld": "example",
                 "rank_band": "10k-100k", "explanation_kind": "shared_linkers", "suppressed": False}],
}
EDITIONS = {"api_version": "v1", "loaded_edition": "fixture-2026-01",
            "editions": [{"id": "fixture-2026-01", "source": "Common Crawl", "isActive": True}]}
RESOLUTION = {key: ENVELOPE[key] for key in (
    "api_version", "query", "resolved_host", "resolution", "edition", "relationship", "selection_reason",
)}

class FakeClient:
    def __init__(self, result=ENVELOPE):
        self.result, self.calls = result, []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.result
        return call


class BoundsTests(unittest.TestCase):
    def test_framer_caps_before_decoding_and_handles_split_utf8(self):
        framer = Framer(maximum=8)
        framer.feed(b'"\xe2\x82')
        self.assertIsNone(framer.pop())
        framer.feed(b'\xac"\n{}\n')
        self.assertEqual(json.loads(framer.pop()), "€")
        self.assertEqual(json.loads(framer.pop()), {})
        with self.assertRaises(TransportClosed):
            framer.feed(b"a" * 9)

    def test_exact_frame_limit_and_many_frames_stay_bounded(self):
        framer = Framer(maximum=8)
        framer.feed(b"a" * 8 + b"\n")
        self.assertEqual(framer.pop(), b"a" * 8)
        for _ in range(100):
            framer.feed(b"{}\n")
            self.assertEqual(framer.pop(), b"{}")
        self.assertEqual(framer.buffer, b"")

    def test_immediate_request_admission_and_notification_bounds(self):
        admission = Admission()
        self.assertTrue(admission.accept({"method": "initialize", "id": 1}))
        with self.assertRaises(TransportClosed):
            admission.accept({"method": "tools/list", "id": 2})
        self.assertTrue(admission.accept({"method": "notifications/initialized"}))
        self.assertTrue(admission.accept({"method": "notifications/cancelled", "params": {"requestId": 1}}))
        self.assertFalse(admission.accept({"method": "notifications/cancelled", "params": {"requestId": 1}}))
        admission.release(1)
        self.assertTrue(admission.accept({"method": "tools/list", "id": 2}))
        with self.assertRaises(TransportClosed):
            for _ in range(40):
                admission.accept({"method": "notifications/progress", "params": {}})

    def test_secret_detection_checks_decoded_values_and_keys(self):
        self.assertTrue(contains_secret({"nested": [{"fixture_key": "value"}]}, "fixture_key"))
        self.assertFalse(contains_secret({"data": "public"}, "fixture_key"))


class AsyncBoundsTests(unittest.IsolatedAsyncioTestCase):
    async def test_deadline_retains_actual_work_permit(self):
        runner = SerialRunner(deadline=0.02)
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        def work():
            started.set()
            release.wait(2)
            finished.set()
            return "done"
        try:
            with self.assertRaises(DeadlineExceeded):
                await runner.run(work)
            self.assertTrue(started.is_set())
            self.assertTrue(runner.busy)
            with self.assertRaises(Busy):
                await runner.run(lambda: None)
        finally:
            release.set()
            for _ in range(100):
                if finished.is_set() and not runner.busy:
                    break
                await asyncio.sleep(0.005)
        self.assertFalse(runner.busy)
        self.assertEqual(await runner.run(lambda: "next"), "next")

    async def test_cancelled_await_does_not_release_thread_permit(self):
        runner = SerialRunner(deadline=1)
        started, release = threading.Event(), threading.Event()
        def work():
            started.set()
            release.wait(2)
        task = asyncio.create_task(runner.run(work))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.005)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(runner.busy)
            with self.assertRaises(Busy):
                await runner.run(lambda: None)
        finally:
            release.set()
            for _ in range(100):
                if not runner.busy:
                    break
                await asyncio.sleep(0.005)
        self.assertFalse(runner.busy)





    async def test_read_pipe_caps_raw_frame_before_decode(self):
        read_fd, write_fd = os.pipe()
        decoded = []
        stream = ReadStream(read_fd, Admission(), lambda *args: decoded.append(args))
        async def write():
            os.set_blocking(write_fd, False)
            try:
                for _ in range(MAX_INPUT_BYTES // 4096 + 1):
                    while True:
                        try:
                            os.write(write_fd, b"x" * 4096)
                            break
                        except BlockingIOError:
                            await asyncio.sleep(0.001)
            finally:
                os.close(write_fd)
        writer = asyncio.create_task(write())
        try:
            with self.assertRaises(StopAsyncIteration):
                await stream.__anext__()
            self.assertEqual(decoded, [])
            self.assertTrue(stream.admission.closed_event.is_set())
        finally:
            await writer
            os.close(read_fd)

    async def test_output_caps_complete_frame_and_releases_only_after_write(self):
        import anyio
        read_fd, write_fd = os.pipe()
        admission = Admission()
        admission.accept({"id": 1, "method": "tools/list"})
        writer = WriteStream(write_fd, admission, secret="fixture_key")
        class Message:
            def __init__(self, value):
                self.value = value
            def model_dump(self, **kwargs):
                return self.value
        try:
            await writer.send(SimpleNamespace(message=Message({"jsonrpc": "2.0", "id": 1, "result": {}})))
            self.assertIsNone(admission.pending)
            self.assertEqual(json.loads(os.read(read_fd, 100)), {"jsonrpc": "2.0", "id": 1, "result": {}})
            for value in ({"result": {"key": "fixture_key"}}, {"result": "x" * MAX_OUTPUT_BYTES}):
                bounded_writer = WriteStream(write_fd, Admission(), secret="fixture_key")
                with self.assertRaises(anyio.BrokenResourceError):
                    await bounded_writer.send(SimpleNamespace(message=Message(value)))
        finally:
            os.close(read_fd)
            os.close(write_fd)

    async def test_stalled_stdout_has_whole_write_deadline_and_no_permit_release(self):
        import anyio
        read_fd, write_fd = os.pipe()
        admission = Admission()
        admission.accept({"id": 1, "method": "tools/call"})
        writer = WriteStream(write_fd, admission)
        message = SimpleNamespace(model_dump=lambda **kwargs: {"jsonrpc": "2.0", "id": 1, "result": "x" * 100000})
        try:
            with patch("linkcensus_mcp.transport.WRITE_SECONDS", 0.02):
                with self.assertRaises(anyio.BrokenResourceError):
                    await writer.send(SimpleNamespace(message=message))
            self.assertEqual(admission.pending, (int, 1))
            self.assertTrue(admission.closed_event.is_set())
        finally:
            os.close(read_fd)
            os.close(write_fd)
