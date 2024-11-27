import asyncio
from pathlib import Path
import tempfile
import threading

import zmq
import ezmsg.core as ez
from ezmsg.util.messagelogger import MessageLogger
from ezmsg.util.messagecodec import message_log
from ezmsg.util.terminate import TerminateOnTotal
from zmq.utils.monitor import parse_monitor_message

from ezmsg.zmq.repreq import ZMQRep, ZMQReq
from ezmsg.zmq.util import ZMQMessage


def test_rep():
    port = 5557
    state = {"running": True, "count": 0, "connected": False}
    file_path = Path(tempfile.gettempdir())
    file_path = file_path / Path("test_rep.txt")

    comps = {
        "ZREP": ZMQRep(addr="tcp://*:" + str(port)),
        "LOGGER": MessageLogger(output=file_path),
        "TERM": TerminateOnTotal(total=10),
    }
    conns = (
        (comps["ZREP"].OUTPUT, comps["LOGGER"].INPUT_MESSAGE),
        (comps["LOGGER"].OUTPUT_MESSAGE, comps["TERM"].INPUT_MESSAGE),
    )

    def req_thread():
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.SNDTIMEO, 500)
        sock.setsockopt(zmq.RCVTIMEO, 500)
        sock.connect("tcp://localhost:" + str(port))

        monitor = sock.get_monitor_socket()
        # It would be better to wait for a connection.
        while state["running"]:
            if not state["connected"]:
                monitor_result = monitor.poll(100)
                if monitor_result:
                    data = monitor.recv_multipart()
                    evt = parse_monitor_message(data)
                    if evt["event"] == zmq.EVENT_CONNECTED:
                        state["connected"] = True
            if state["connected"]:
                try:
                    sock.send(b"Hello")
                    msg = sock.recv()
                    assert msg == b"Hello"
                except zmq.error.Again:
                    # Remote has disconnected. Try again.
                    # If this happened during `send`, then we
                    #  might be in a bad state because we can't
                    #  send twice without a successful recv in between.
                    continue
        sock.close()

    _thread = threading.Thread(target=req_thread)
    _thread.daemon = True
    _thread.start()

    ez.run(components=comps, connections=conns)

    state["running"] = False
    _thread.join()

    result = list(message_log(file_path))
    for msg in result:
        assert msg.data == b"Hello"

    file_path.unlink(missing_ok=True)


def test_req():
    port = 5557
    state = {"running": True, "count": 0}
    file_path = Path(tempfile.gettempdir())
    file_path = file_path / Path("test_req.txt")

    class DummyReqSource(ez.Unit):
        OUTPUT = ez.OutputStream(ZMQMessage)

        @ez.publisher(OUTPUT)
        async def send_reqs(self):
            while True:
                yield self.OUTPUT, ZMQMessage(b"Hello")
                await asyncio.sleep(0.1)

    comps = {
        "SRC": DummyReqSource(),
        "ZREQ": ZMQReq(addr="tcp://localhost:" + str(port)),
        "LOGGER": MessageLogger(output=file_path),
        "TERM": TerminateOnTotal(total=10),
    }
    conns = (
        (comps["SRC"].OUTPUT, comps["ZREQ"].INPUT),
        (comps["ZREQ"].OUTPUT, comps["LOGGER"].INPUT_MESSAGE),
        (comps["LOGGER"].OUTPUT_MESSAGE, comps["TERM"].INPUT_MESSAGE),
    )

    def rep_thread():
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REP)
        sock.setsockopt(zmq.RCVTIMEO, 500)
        sock.setsockopt(zmq.SNDTIMEO, 500)
        sock.bind("tcp://*:" + str(port))
        while state["running"]:
            try:
                msg = sock.recv()
                assert msg == b"Hello"
                sock.send(msg)
            except zmq.error.Again:
                # Remote has disconnected. Try again.
                continue
        sock.close()

    _thread = threading.Thread(target=rep_thread)
    _thread.daemon = True
    _thread.start()

    ez.run(components=comps, connections=conns)

    state["running"] = False
    _thread.join()

    for msg in message_log(file_path):
        assert msg.data == b"Hello"

    file_path.unlink(missing_ok=True)
