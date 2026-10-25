import copy
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from test_cli import CLI, SNAPSHOT


class EventPeer:
    """Concurrent disposable NDJSON server for the public watch command."""

    def __init__(self, directory):
        self.path = str(Path(directory) / "events.sock")
        self.snapshot = copy.deepcopy(SNAPSHOT)
        self.requests = []
        self.connections = []
        self.errors = []
        self.extra_requests = []
        self.on_subscribe = lambda connection, request, number: None
        self.on_snapshot = lambda number: None
        self.snapshot_errors = set()
        self.snapshots = 0
        self.subscriptions = 0
        self.stop = threading.Event()
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.bind(self.path)
        self.listener.listen()
        self.listener.settimeout(0.05)
        self.threads = []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    @staticmethod
    def send(connection, frame):
        connection.sendall((json.dumps(frame) + "\n").encode())

    def status(self, state, seq):
        self.snapshot["agents"][0].update(agent_status=state, state_change_seq=seq)
        self.snapshot["panes"][0]["agent_status"] = state

    def event(self, connection, state="working"):
        self.send(connection, {"event": "pane_agent_status_changed", "data": {
            "type": "pane_agent_status_changed", "pane_id": "scratch:p1",
            "workspace_id": "scratch", "agent_status": state,
        }})

    def serve(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            self.connections.append(connection)
            thread = threading.Thread(target=self.handle, args=(connection,), daemon=True)
            self.threads.append(thread)
            thread.start()

    def handle(self, connection):
        try:
            with connection, connection.makefile("rb") as stream:
                request = json.loads(stream.readline())
                self.requests.append(request)
                method = request["method"]
                if method == "events.subscribe":
                    self.subscriptions += 1
                    if self.on_subscribe(connection, request, self.subscriptions) is False:
                        return
                    if connection.fileno() < 0:
                        return
                    self.send(connection, {"id": request["id"], "result": {"type": "subscription_started"}})
                    while not self.stop.wait(0.01):
                        ready, _, _ = select.select([connection], [], [], 0)
                        if ready:
                            data = connection.recv(65536)
                            if data:
                                self.extra_requests.append(data.decode())
                            return
                elif method == "session.snapshot":
                    self.snapshots += 1
                    snapshot = self.on_snapshot(self.snapshots)
                    if self.snapshots in self.snapshot_errors:
                        self.send(connection, {"id": request["id"], "error": {"code": "unavailable"}})
                        return
                    self.send(connection, {"id": request["id"], "result": {
                        "snapshot": self.snapshot if snapshot is None else snapshot,
                    }})
                elif method == "ping":
                    self.send(connection, {"id": request["id"], "result": {"type": "pong"}})
                else:
                    raise AssertionError("unexpected request " + method)
        except (OSError, ValueError):
            pass
        except Exception as error:
            self.errors.append(repr(error))

    def later(self, delay, action):
        def run():
            if not self.stop.wait(delay):
                try:
                    action()
                except OSError:
                    pass
        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(2)
        for thread in self.threads:
            thread.join(2)
        self.listener.close()


class EventLoopTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="loop-test-", dir="/tmp")
        self.peer = EventPeer(self.temp.name)

    def tearDown(self):
        self.peer.close()
        self.assertEqual(self.peer.errors, [])
        self.temp.cleanup()

    def watch(self, **params):
        command = {"command": "watch", "params": {
            "workspace_id": "scratch", "duration_seconds": 0.65,
            "floor_seconds": 0.15, "ping_seconds": 0.1,
            "expected_event_seconds": 0.1, "silence_periods": 20,
            "retry_seconds": 0.05, "request_timeout_seconds": 0.2,
            **params,
        }}
        self.log_lines = []
        self.log_arrived = threading.Condition()
        log_read, log_write = os.pipe()
        with subprocess.Popen(
            [sys.executable, str(CLI), "--socket", self.peer.path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log_write, text=True,
        ) as process:
            os.close(log_write)
            follower = threading.Thread(target=self.follow_logs, args=(log_read,), daemon=True)
            follower.start()
            try:
                output, _ = process.communicate(json.dumps(command), timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                raise
            follower.join()
        self.assertTrue(output.strip(), f"watch printed nothing: exit {process.returncode}, "
                                        f"stderr tail {''.join(self.log_lines)[-500:]!r}")
        return process.returncode, json.loads(output), [json.loads(line) for line in self.log_lines]

    def follow_logs(self, descriptor):
        with open(descriptor, encoding="utf-8") as stream:
            for line in stream:
                with self.log_arrived:
                    self.log_lines.append(line)
                    self.log_arrived.notify_all()

    def wait_for_log(self, kind):
        """Block a peer thread until the watch process has logged a row of this kind."""
        with self.log_arrived:
            arrived = self.log_arrived.wait_for(
                lambda: any(json.loads(line)["kind"] == kind for line in self.log_lines), 5)
        if not arrived:
            raise AssertionError("the watch never logged " + kind)

    def test_floor_catches_unannounced_transition_and_pings_leave_stream_alive(self):
        def subscribed(connection, request, number):
            self.peer.later(0.22, lambda: self.peer.status("blocked", 2))
        self.peer.on_subscribe = subscribed
        # 1.6 s leaves the floor (0.15 s) many chances after the 0.22 s change even when subscribing
        # is slow; 40 silence periods (4 s) keep the silence watchdog out of a test about pings.
        code, result, logs = self.watch(duration_seconds=1.6, silence_periods=40)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["result"]["picture"]["members"][0]["agent_status"], "blocked")
        self.assertEqual(self.peer.subscriptions, 1)
        self.assertEqual(self.peer.extra_requests, [])
        self.assertGreaterEqual(result["result"]["stats"]["pings"], 3)
        self.assertTrue(any(row["kind"] == "reconcile" and row["reason"] == "floor"
                            and any(c["after"]["agent_status"] == "blocked"
                                    for c in row["changes"] if c["after"]) for row in logs))
        subscriptions = [r for r in self.peer.requests if r["method"] == "events.subscribe"]
        self.assertIn({"type": "pane.agent_status_changed", "pane_id": "scratch:p1"},
                      subscriptions[0]["params"]["subscriptions"])
        self.assertNotIn("pane.read", [r["method"] for r in self.peer.requests])

    def test_events_own_fast_path_and_payload_never_overwrites_snapshot(self):
        def subscribed(connection, request, number):
            def change():
                self.peer.status("blocked", 2)
                self.peer.event(connection, "working")  # Deliberately stale payload.
            self.peer.later(0.2, change)
        self.peer.on_subscribe = subscribed
        # The floor is 5 s, so an event reconcile inside this 2 s watch can only come from the event path.
        code, result, logs = self.watch(duration_seconds=2.0, floor_seconds=5, silence_periods=100)
        self.assertEqual(code, 0, result)
        changes = [r for r in logs if r["kind"] == "reconcile" and r["reason"] == "event"]
        self.assertEqual(changes[0]["changes"][0]["after"]["agent_status"], "blocked")
        self.assertEqual(result["result"]["picture"]["members"][0]["agent_status"], "blocked")
        event = next(r for r in logs if r["kind"] == "event")
        self.assertLess(changes[0]["elapsed_seconds"] - event["elapsed_seconds"], 0.5)

    def test_bootstrap_buffers_during_snapshot_then_invalidates_without_replay(self):
        streams = []
        self.peer.on_subscribe = lambda connection, request, number: streams.append(connection)
        def snapshot(number):
            if streams and number == 2:  # The bootstrap.
                old = copy.deepcopy(self.peer.snapshot)
                self.peer.status("blocked", 2)
                self.peer.event(streams[0], "idle")  # Deliberately stale payload.
                # Hold the old reply until the loop has read the event, so the event always lands during the
                # bootstrap whatever the thread scheduling; a timer or a sleep would only bet on the order.
                self.wait_for_log("event")
                return old
        self.peer.on_snapshot = snapshot
        code, result, logs = self.watch(floor_seconds=5, request_timeout_seconds=2.0)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["result"]["picture"]["members"][0]["agent_status"], "blocked")
        applied = [r for r in logs if r["kind"] == "bootstrap_applied"]
        self.assertTrue(applied[0]["invalidated"], logs)
        bootstrap = next(i for i, r in enumerate(logs) if r["kind"] == "snapshot_start" and r["reason"] == "bootstrap")
        subscribed = next(i for i, r in enumerate(logs) if r["kind"] == "subscribed")
        self.assertLess(subscribed, bootstrap)
        self.assertTrue(any(r["kind"] == "reconcile" and r["reason"] == "event" for r in logs))

    def recovery(self, failure):
        def subscribed(connection, request, number):
            if number == 1:
                def fail():
                    self.peer.status("blocked", 2)
                    if failure == "events_lost":
                        self.peer.send(connection, {"id": request["id"], "error": {"code": "events_lost"}})
                    if failure != "silence":
                        connection.shutdown(socket.SHUT_RDWR)
                self.peer.later(0.16, fail)
            else:
                self.peer.later(0.06, lambda: self.peer.event(connection, "blocked"))
        self.peer.on_subscribe = subscribed
        # Only the silence variant may let the watchdog fire. Elsewhere a late peer thread would turn the
        # injected failure into a silence death (the 0.16 s timer has 0.14 s of slack against 3 periods).
        silence_periods = 3 if failure == "silence" else 100
        code, result, logs = self.watch(duration_seconds=2.0, floor_seconds=5, silence_periods=silence_periods)
        self.assertEqual(code, 0, result)
        self.assertGreaterEqual(result["result"]["stats"]["reconnects"], 1)
        self.assertEqual(result["result"]["picture"]["members"][0]["agent_status"], "blocked")
        death = next(r for r in logs if r["kind"] == "death")
        self.assertEqual(death["reason"], failure)
        bootstraps = [r for r in logs if r["kind"] == "reconcile" and r["reason"] == "bootstrap"]
        self.assertGreaterEqual(len(bootstraps), 2)
        self.assertEqual(self.peer.extra_requests, [])
        return death, logs

    def test_killed_stream_reconnects_resubscribes_and_reconciles(self):
        self.recovery("stream_closed")

    def test_events_lost_recovers_with_new_subscription_before_snapshot(self):
        self.recovery("events_lost")

    def test_silent_starvation_fires_within_threshold_despite_successful_pings(self):
        death, logs = self.recovery("silence")
        # Threshold is 3 x 0.1 s. Pings that reset the clock would postpone the death past the watch
        # (no death at all), and a doubled threshold would reach 0.6 s.
        self.assertGreaterEqual(death["silence_seconds"], 0.3)
        self.assertLess(death["silence_seconds"], 0.6)
        self.assertTrue(any(r["kind"] == "ping" for r in logs))

    def test_rejected_entry_refreshes_panes_and_retries_whole_subscription(self):
        def subscribed(connection, request, number):
            if number == 1:
                self.peer.snapshot["panes"] = []
                self.peer.snapshot["agents"] = []
                self.peer.send(connection, {"id": request["id"], "error": {"code": "not_found"}})
                return False
        self.peer.on_subscribe = subscribed
        code, result, logs = self.watch()
        self.assertEqual(code, 0, result)
        requests = [r for r in self.peer.requests if r["method"] == "events.subscribe"]
        self.assertEqual(len(requests), 2)
        self.assertFalse(any("pane_id" in p for p in requests[1]["params"]["subscriptions"]))
        error = next(i for i, r in enumerate(logs) if r["kind"] == "subscribe_error")
        reconcile = next(i for i, r in enumerate(logs[error:], error)
                         if r["kind"] == "reconcile" and r["reason"] == "subscription_refresh")
        retry = next(i for i, r in enumerate(logs[error:], error) if r["kind"] == "subscribe_start")
        self.assertLess(reconcile, retry)

    def test_hung_subscription_ack_does_not_stop_floor_or_watch_deadline(self):
        def subscribed(connection, request, number):
            self.peer.later(0.15, lambda: self.peer.status("blocked", 2))
            time.sleep(0.5)
            return False
        self.peer.on_subscribe = subscribed
        code, result, logs = self.watch()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["result"]["picture"]["members"][0]["agent_status"], "blocked")
        self.assertGreaterEqual(result["result"]["stats"]["floor_reconciliations"], 2)
        self.assertTrue(any(r["kind"] == "subscribe_error" for r in logs))

    def test_slow_snapshot_does_not_block_watchdog_and_refreshes_are_serialized(self):
        active = []
        overlapping = []
        def snapshot(number):
            if active:
                overlapping.append(number)
            active.append(number)
            if number == 2:
                time.sleep(1.5)
            active.remove(number)
        self.peer.on_snapshot = snapshot
        code, result, logs = self.watch(duration_seconds=3.0, silence_periods=2, request_timeout_seconds=3.0)
        self.assertEqual(code, 0, result)
        death = next(r for r in logs if r["kind"] == "death")
        stalled = next(r for r in logs if r["kind"] == "snapshot_start" and r["reason"] == "bootstrap")
        # The 0.2 s silence threshold trips while the 1.5 s bootstrap snapshot is still in flight; a watchdog
        # blocked behind that snapshot would trip only after it returns.
        self.assertLess(death["elapsed_seconds"] - stalled["elapsed_seconds"], 1.0)
        self.assertEqual(overlapping, [])
        self.assertGreaterEqual(result["result"]["stats"]["pings"], 3)

    def test_unrelated_workspace_traffic_cannot_mask_fleet_starvation(self):
        def subscribed(connection, request, number):
            for i in range(15):
                self.peer.later(0.03 * (i + 1), lambda: self.peer.send(connection, {
                    "event": "pane_updated", "data": {"type": "pane_updated", "pane": {
                        "pane_id": "human:p1", "workspace_id": "human",
                    }},
                }))
        self.peer.on_subscribe = subscribed
        code, result, logs = self.watch(silence_periods=2, include_updates=True)
        self.assertEqual(code, 0, result)
        self.assertTrue(any(r["kind"] == "death" and r["reason"] == "silence" for r in logs))
        self.assertEqual(result["result"]["stats"]["events"], 0)

    def test_fragmented_event_survives_idle_reads(self):
        def subscribed(connection, request, number):
            frame = json.dumps({"event": "pane.agent_status_changed", "data": {
                "type": "pane_agent_status_changed", "pane_id": "scratch:p1", "workspace_id": "scratch",
            }}).encode() + b"\n"
            self.peer.later(0.1, lambda: connection.sendall(frame[:30]))
            def finish():
                self.peer.status("blocked", 2)
                connection.sendall(frame[30:])
            self.peer.later(0.25, finish)
        self.peer.on_subscribe = subscribed
        code, result, logs = self.watch(floor_seconds=5)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["result"]["picture"]["members"][0]["agent_status"], "blocked")
        self.assertEqual(result["result"]["stats"]["deaths"], 0)
        self.assertTrue(any(r["kind"] == "reconcile" and r["reason"] == "event" for r in logs))

    def test_new_pane_is_discovered_and_subscription_fanout_rebuilt(self):
        def subscribed(connection, request, number):
            if number == 1:
                def add():
                    pane = {**self.peer.snapshot["panes"][0], "pane_id": "scratch:p2"}
                    self.peer.snapshot["panes"].append(pane)
                    self.peer.send(connection, {"event": "pane_created", "data": {
                        "type": "pane_created", "pane": pane,
                    }})
                self.peer.later(0.15, add)
        self.peer.on_subscribe = subscribed
        code, result, logs = self.watch(floor_seconds=5)
        self.assertEqual(code, 0, result)
        requests = [r for r in self.peer.requests if r["method"] == "events.subscribe"]
        self.assertEqual(len(requests), 2)
        self.assertEqual({p["pane_id"] for p in requests[-1]["params"]["subscriptions"] if "pane_id" in p},
                         {"scratch:p1", "scratch:p2"})

    def test_continuous_updates_are_debounced_with_one_second_cap(self):
        def subscribed(connection, request, number):
            for i in range(17):
                self.peer.later(0.04 + i * 0.09, lambda i=i: self.peer.send(connection, {
                    "event": "pane.updated" if i % 2 else "pane_updated", "data": {"type": "pane_updated", "pane": {
                        "pane_id": "scratch:p1", "workspace_id": "scratch",
                    }},
                }))
        self.peer.on_subscribe = subscribed
        # 100 silence periods (10 s): a silence death would resubscribe and replay the whole burst.
        code, result, logs = self.watch(duration_seconds=4.0, floor_seconds=5, silence_periods=100,
                                        include_updates=True)
        self.assertEqual(code, 0, result)
        updates = [r["elapsed_seconds"] for r in logs if r["kind"] == "event"]
        reads = [r["elapsed_seconds"] for r in logs if r["kind"] == "snapshot_start" and r["reason"] == "event"]
        # Precondition, read from the loop's own rows: the peer must have delivered one continuous burst
        # (no gap near the 0.2 s quiet period, about 1.5 s long). Starved peer threads can stretch or
        # split it, and then the cap is not what this run measures.
        gaps = [later - earlier for earlier, later in zip(updates, updates[1:])]
        if not gaps or max(gaps) >= 0.19 or updates[-1] - updates[0] >= 1.9:
            self.skipTest(f"peer did not deliver a continuous burst (max gap {max(gaps, default=0):.2f} s, "
                          f"span {updates[-1] - updates[0] if updates else 0:.2f} s)")
        self.assertEqual(len(reads), 2, logs)
        # The cap counts from the first update and fires while updates still arrive (they run about 1.5 s);
        # with no cap the one read would wait for the quiet period after the last update.
        self.assertGreaterEqual(reads[0] - updates[0], 0.99)
        self.assertLess(reads[0] - updates[0], 1.5)
        self.assertLess(reads[0], updates[-1])
        self.assertGreaterEqual(reads[1] - updates[-1], 0.19)

    def test_invalid_watch_options_and_subscribe_typos_never_connect(self):
        for params in ({"floor_seconds": 0}, {"duration_seconds": True},
                       {"silence_periods": -1}, {"workspace_id": ""},
                       {"include_updates": "yes"}, {"subscription": []},
                       {"floor_seconds": 10 ** 1000},
                       {"expected_event_seconds": 1e308, "silence_periods": 1e308}):
            code, result, logs = self.watch(**params)
            self.assertEqual(code, 1, result)
        self.assertEqual(self.peer.requests, [])
        process = subprocess.run([sys.executable, str(CLI)], input=json.dumps({
            "command": "validate", "params": {"method": "events.subscribe", "params": {
                "subscriptions": [{"type": "pane.agent_status_changed", "pane_id": "scratch:p1", "typo": 1}],
            }},
        }), capture_output=True, text=True)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout)["error"]["code"], "schema_invalid")

    def test_retry_interval_has_fifty_millisecond_minimum(self):
        code, result, logs = self.watch(retry_seconds=0.049)
        self.assertEqual(code, 1, result)
        self.assertEqual(result["error"]["code"], "schema_invalid")
        self.assertIn("retry_seconds must be at least 0.05", result["error"]["message"])
        self.assertEqual(self.peer.requests, [])
        code, result, logs = self.watch(retry_seconds=0.05, duration_seconds=0.15)
        self.assertEqual(code, 0, result)

    def test_exit_flushes_pending_debounce_before_returning_picture(self):
        def subscribed(connection, request, number):
            # Updates arrive every 0.05 s past the deadline: the debounce never goes quiet (0.2 s) and its
            # 1 s cap is not reached inside a 1 s watch, so only the exit flush can read the change.
            self.peer.later(0.03, lambda: self.peer.status("blocked", 2))
            for i in range(40):
                self.peer.later(0.04 + i * 0.05, lambda: self.peer.send(connection, {
                    "event": "pane.updated", "data": {"pane_id": "scratch:p1", "workspace_id": "scratch"},
                }))
        self.peer.on_subscribe = subscribed
        code, result, logs = self.watch(duration_seconds=1.0, floor_seconds=5, include_updates=True)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["result"]["picture"]["members"][0]["state_change_seq"], 2)
        flushes = [r for r in logs if r["kind"] == "reconcile" and r["reason"] == "exit"]
        self.assertEqual(len(flushes), 1, logs)
        self.assertFalse(any(r["kind"] == "snapshot_start" and r["reason"] == "event" for r in logs))
        self.assertEqual(self.peer.extra_requests, [])

    def test_snapshot_failures_preserve_picture_pace_retries_and_recover(self):
        for failures in (100, 2):
            with self.subTest(failed_calls=failures):
                base = self.peer.snapshots
                self.peer.status("idle", 1)
                self.peer.snapshot_errors = set(range(base + 2, base + failures + 2))
                def snapshot(number):
                    if number == base + 2:
                        self.peer.status("blocked", 2)
                self.peer.on_snapshot = snapshot
                code, result, logs = self.watch(duration_seconds=1.2, floor_seconds=0.3, retry_seconds=0.09)
                self.assertEqual(code, 0, result)
                value = result["result"]
                errors = [r for r in logs if r["kind"] == "snapshot_error"]
                self.assertGreaterEqual(len(errors), 2)
                self.assertTrue(all(r["code"] == "server_error" for r in errors))
                first_error = next(i for i, r in enumerate(logs) if r["kind"] == "snapshot_error")
                self.assertTrue(any(r["kind"] == "ping" for r in logs[first_error + 1:]), logs)
                self.assertTrue(any(r["kind"] == "snapshot_start" and r["reason"] == "floor"
                                    for r in logs))
                # Floor probes stay independent, but bootstrap retries must be paced.
                last_error = None
                retries = 0
                for row in logs:
                    if row["kind"] == "snapshot_error":
                        last_error = row["elapsed_seconds"]
                    if row["kind"] == "snapshot_start" and row["reason"] == "bootstrap" and last_error is not None:
                        self.assertGreaterEqual(row["elapsed_seconds"] - last_error, 0.085)
                        retries += 1
                self.assertGreaterEqual(retries, 1)
                if failures == 100:
                    self.assertEqual(value["picture"]["members"][0]["state_change_seq"], 1)
                    self.assertEqual(value["snapshot_error"], "server_error")
                    self.assertGreater(value["snapshot_age_seconds"], 0.5)
                    self.assertEqual(value["stats"]["reconciliations"], 1)
                else:
                    self.assertEqual(len(errors), 2)
                    self.assertEqual(value["picture"]["members"][0]["state_change_seq"], 2)
                    self.assertIsNone(value["snapshot_error"])
                    self.assertGreaterEqual(value["stats"]["floor_reconciliations"], 1)

    def test_event_during_floor_snapshot_reconciles_without_sequence_regression(self):
        streams = []
        def subscribed(connection, request, number):
            streams.append(connection)
            def change():
                self.peer.status("working", 2)
                self.peer.event(connection)
            self.peer.later(0.06, change)
        def snapshot(number):
            if number == 4:  # Initial, bootstrap, event, then floor.
                old = copy.deepcopy(self.peer.snapshot)
                self.peer.status("blocked", 3)
                self.peer.event(streams[0], "blocked")
                time.sleep(0.6)
                return old
        self.peer.on_subscribe = subscribed
        self.peer.on_snapshot = snapshot
        # The floor (1 s) comes after the early event's snapshot (#3) unless subscribing takes nearly a second.
        code, result, logs = self.watch(duration_seconds=3.0, floor_seconds=1.0, silence_periods=100,
                                        request_timeout_seconds=2.0)
        self.assertEqual(code, 0, result)
        start = next(i for i, r in enumerate(logs) if r["kind"] == "snapshot_start" and r["reason"] == "floor")
        finish = next(i for i, r in enumerate(logs) if r["kind"] == "reconcile" and r["reason"] == "floor")
        self.assertTrue(any(r["kind"] == "event" for r in logs[start + 1:finish]), logs)
        self.assertTrue(any(r["kind"] == "reconcile" and r["reason"] == "event"
                            for r in logs[finish + 1:]), logs)
        changes = [c for r in logs if r["kind"] == "reconcile" for c in r["changes"] if c["after"]]
        self.assertEqual([c["after"]["state_change_seq"] for c in changes], [1, 2, 3])
        for change in changes:
            if change["before"]:
                self.assertGreaterEqual(change["after"]["state_change_seq"], change["before"]["state_change_seq"])
        self.assertEqual(result["result"]["picture"]["members"][0]["state_change_seq"], 3)

    def test_exit_drains_inflight_floor_before_flushing_dirty_event(self):
        streams = []
        self.peer.on_subscribe = lambda connection, request, number: streams.append(connection)
        def snapshot(number):
            if number == 3:
                old = copy.deepcopy(self.peer.snapshot)
                self.peer.status("blocked", 2)
                self.peer.event(streams[0], "blocked")
                time.sleep(1.0)
                return old
        self.peer.on_snapshot = snapshot
        # The floor starts at 1.0 s and stays in flight until 2.0 s, so the 1.5 s deadline lands inside it.
        code, result, logs = self.watch(duration_seconds=1.5, floor_seconds=1.0,
                                        request_timeout_seconds=2.0)
        self.assertEqual(code, 0, result)
        reconciles = [r for r in logs if r["kind"] == "reconcile"]
        self.assertEqual([r["reason"] for r in reconciles],
                         ["subscription_refresh", "bootstrap", "floor", "exit"])
        self.assertEqual([c["after"]["state_change_seq"] for r in reconciles for c in r["changes"]], [1, 2])
        self.assertEqual(result["result"]["picture"]["members"][0]["state_change_seq"], 2)

    def test_exit_flush_timeout_preserves_picture_and_returns_bounded_error(self):
        def subscribed(connection, request, number):
            # Updates keep arriving past the deadline, so the debounce never goes quiet (0.2 s) and its 1 s cap
            # is never reached: the pending update can only leave through the exit flush, however late the
            # subscription is.
            for i in range(40):
                self.peer.later(0.04 + i * 0.05, lambda: self.peer.send(connection, {
                    "event": "pane.updated", "data": {"pane_id": "scratch:p1", "workspace_id": "scratch"},
                }))
        def snapshot(number):
            if number == 3:  # the exit flush
                self.peer.status("blocked", 2)
                time.sleep(5)
        self.peer.on_subscribe = subscribed
        self.peer.on_snapshot = snapshot
        code, result, logs = self.watch(duration_seconds=1.0, floor_seconds=5,
                                        include_updates=True, request_timeout_seconds=0.1)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["result"]["picture"]["members"][0]["state_change_seq"], 1)
        self.assertEqual(result["result"]["snapshot_error"], "transport_error")
        self.assertTrue(any(r["kind"] == "snapshot_error" and r["reason"] == "exit" for r in logs))
        self.assertEqual(self.peer.snapshots, 3)
        # Duration 1.0 + request timeout 0.1 + generous slack; waiting out the 5 s stall would not fit.
        self.assertLess(logs[-1]["elapsed_seconds"], 2.1)

    def test_events_lost_in_batch_with_valid_frames_replaces_cache_on_bootstrap(self):
        def subscribed(connection, request, number):
            if number == 1:
                def lose():
                    self.peer.snapshot["agents"] = []
                    self.peer.snapshot["panes"] = []
                    event = {"event": "pane.agent_status_changed", "data": {
                        "pane_id": "scratch:p1", "workspace_id": "scratch",
                        "agent_status": "working", "state_change_seq": 99,
                    }}
                    frames = [event, event, {"id": request["id"], "error": {"code": "events_lost"}}]
                    connection.sendall("".join(json.dumps(frame) + "\n" for frame in frames).encode())
                self.peer.later(0.1, lose)
        self.peer.on_subscribe = subscribed
        code, result, logs = self.watch(floor_seconds=5)
        self.assertEqual(code, 0, result)
        death = next(i for i, r in enumerate(logs) if r["kind"] == "death" and r["reason"] == "events_lost")
        subscribed = next(i for i, r in enumerate(logs) if i > death and r["kind"] == "subscribed")
        bootstrap = next(i for i, r in enumerate(logs) if i > subscribed
                         and r["kind"] == "reconcile" and r["reason"] == "bootstrap")
        self.assertEqual(logs[bootstrap]["changes"][0]["pane_id"], "scratch:p1")
        self.assertIsNone(logs[bootstrap]["changes"][0]["after"])
        self.assertEqual(result["result"]["picture"]["members"], [])
        self.assertEqual(result["result"]["picture"]["panes"], [])
        self.assertEqual(self.peer.extra_requests, [])

    def test_removed_pane_disappears_from_cache_and_subscription_fanout(self):
        for kind in ("pane.closed", "pane.exited"):
            with self.subTest(event=kind):
                self.peer.snapshot = copy.deepcopy(SNAPSHOT)
                first_subscription = self.peer.subscriptions + 1
                def subscribed(connection, request, number):
                    if number == first_subscription:
                        def remove():
                            self.peer.snapshot["panes"] = []
                            self.peer.snapshot["agents"] = []
                            self.peer.send(connection, {"event": kind, "data": {
                                "pane_id": "scratch:p1", "workspace_id": "scratch",
                            }})
                        self.peer.later(0.1, remove)
                self.peer.on_subscribe = subscribed
                code, result, logs = self.watch(floor_seconds=5)
                self.assertEqual(code, 0, result)
                self.assertEqual(result["result"]["picture"]["panes"], [])
                self.assertEqual(result["result"]["picture"]["members"], [])
                requests = [r for r in self.peer.requests if r["method"] == "events.subscribe"]
                entries = requests[-1]["params"]["subscriptions"]
                self.assertFalse(any("pane_id" in entry for entry in entries))
                self.assertEqual(len(entries), 5)  # Keep all topology subscriptions.
                self.assertEqual(result["result"]["stats"]["subscriptions"], 2)
                self.assertTrue(any(r["kind"] == "resubscribe" and r["reason"] == "topology_changed" for r in logs))

    def test_malformed_ack_recovers_instead_of_crashing(self):
        def subscribed(connection, request, number):
            if number == 1:
                self.peer.send(connection, {"id": request["id"], "result": []})
                return False
        self.peer.on_subscribe = subscribed
        code, result, logs = self.watch()
        self.assertEqual(code, 0, result)
        self.assertTrue(any(r["kind"] == "subscribe_error" and r["code"] == "transport_error" for r in logs))
        self.assertEqual(result["result"]["stats"]["subscriptions"], 1)

    def test_null_nested_pane_is_a_bounded_transport_death_not_a_traceback(self):
        # External review A3: data.pane = null raised AttributeError out of the watch.
        def subscribed(connection, request, number):
            if number == 1:
                self.peer.later(0.05, lambda: self.peer.send(connection, {
                    "event": "pane_created", "data": {"type": "pane_created", "pane": None}}))
        self.peer.on_subscribe = subscribed
        started = time.monotonic()
        code, result, logs = self.watch(floor_seconds=5)
        self.assertEqual(code, 0, result)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(result["result"]["stats"]["deaths"], 1)
        self.assertTrue(any(r["kind"] == "death" and r["reason"] == "transport_error" for r in logs))

    def assert_malformed_id_is_a_bounded_transport_death(self, pane):
        def subscribed(connection, request, number):
            if number == 1:
                self.peer.later(0.05, lambda: self.peer.send(connection, {
                    "event": "pane_created", "data": {"pane": pane}}))
        self.peer.on_subscribe = subscribed
        started = time.monotonic()
        code, result, logs = self.watch(floor_seconds=5)
        self.assertEqual(code, 0, result)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(result["result"]["stats"]["deaths"], 1)
        self.assertTrue(any(r["kind"] == "death" and r["reason"] == "transport_error" for r in logs))
        self.assertGreaterEqual(self.peer.subscriptions, 2)

    def test_unhashable_nested_pane_id_is_a_bounded_transport_death(self):
        # CP1 Spec4: pane_id [] passed the dict guard and raised TypeError at scope membership.
        self.assert_malformed_id_is_a_bounded_transport_death({"pane_id": []})

    def test_non_string_nested_workspace_id_is_a_bounded_transport_death(self):
        self.assert_malformed_id_is_a_bounded_transport_death({"workspace_id": 7, "pane_id": "scratch:p1"})

    def test_lifecycle_events_with_missing_ids_are_still_valid(self):
        def subscribed(connection, request, number):
            if number == 1:
                for data in ({"type": "pane_created"}, {"pane": {"pane_id": "scratch:p1"}},
                             {"pane": {"workspace_id": "scratch"}}):
                    self.peer.later(0.05, lambda data=data: self.peer.send(
                        connection, {"event": "pane_created", "data": data}))
        self.peer.on_subscribe = subscribed
        code, result, logs = self.watch(floor_seconds=5)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["result"]["stats"]["deaths"], 0)
        self.assertEqual(result["result"]["stats"]["events"], 2)

    def test_trickling_snapshot_peer_is_abandoned_within_bounded_time(self):
        # Ticket 13: a snapshot reply sent one byte at a time defeats per-read
        # timeouts, so the watch must fall back to its total deadline and exit
        # bounded instead of draining forever.
        class TrickleEventPeer(EventPeer):
            def __init__(self, directory, delay):
                super().__init__(directory)
                self.delay = delay

            def send(self, connection, frame):
                line = (json.dumps(frame) + "\n").encode()
                if isinstance(frame.get("result"), dict) and "snapshot" in frame["result"]:
                    for byte in line:
                        connection.sendall(bytes([byte]))
                        time.sleep(self.delay)
                else:
                    EventPeer.send(connection, frame)

        with tempfile.TemporaryDirectory(prefix="trickle-", dir="/tmp") as directory:
            peer = TrickleEventPeer(directory, delay=0.05)
            try:
                command = {"command": "watch", "params": {
                    "workspace_id": "scratch", "duration_seconds": 0.65,
                    "floor_seconds": 0.15, "ping_seconds": 0.1,
                    "expected_event_seconds": 0.1, "silence_periods": 20,
                    "retry_seconds": 0.05, "request_timeout_seconds": 0.2}}
                started = time.monotonic()
                process = subprocess.run(
                    [sys.executable, str(CLI), "--socket", peer.path],
                    input=json.dumps(command), capture_output=True, text=True, timeout=8)
                elapsed = time.monotonic() - started
                self.assertLess(elapsed, 4.0)
                self.assertGreaterEqual(peer.snapshots, 1)
                response = json.loads(process.stdout)
                self.assertEqual(process.returncode, 1, response)
                self.assertEqual(response["error"]["code"], "observation_unavailable")
            finally:
                peer.close()


class StalledWorkerAbandonmentTest(unittest.TestCase):
    """Round 3 (R-1): abandonment must end the wait, not just log it."""

    def test_stalled_snapshot_worker_is_abandoned_not_joined(self):
        # Old code: executor context exit joined the running worker, so
        # snapshot_abandoned logged while run() kept blocking until the worker
        # finished. A direct Loop with an injected stall keeps the bound honest.
        root = str(Path(__file__).resolve().parents[1])
        if root not in sys.path:
            sys.path.insert(0, root)
        import event_loop
        from adapter import Refusal

        release = threading.Event()
        original = event_loop.observe

        def stalled(client, scope):
            release.wait(10)  # a worker that never finishes within any grace
            return original(client, scope)

        class Client:
            timeout = 0.3

            def request(self, method, params):
                raise Refusal("transport_error", "unreachable")

            def subscribe(self, params):
                raise Refusal("transport_error", "unreachable")

        config = {**event_loop.DEFAULTS, "duration_seconds": 0.2, "floor_seconds": 5,
                  "ping_seconds": 60, "expected_event_seconds": 2, "silence_periods": 60,
                  "retry_seconds": 0.05, "request_timeout_seconds": 0.3}
        event_loop.observe = stalled
        # Old code could only exit because this timer released the worker at 4s.
        timer = threading.Timer(4.0, release.set)
        timer.start()
        try:
            loop = event_loop.Loop(Client(), {"workspace_id": "scratch"}, config)
            started = time.monotonic()
            with self.assertRaises(Refusal) as caught:
                loop.run()
            elapsed = time.monotonic() - started
            self.assertEqual(caught.exception.code, "observation_unavailable")
            # grace = 2 * 0.3 + 1 = 1.6s; run() must return well before the 4s release.
            self.assertLess(elapsed, 3.0)
        finally:
            timer.cancel()
            release.set()
            event_loop.observe = original

if __name__ == "__main__":
    unittest.main()
