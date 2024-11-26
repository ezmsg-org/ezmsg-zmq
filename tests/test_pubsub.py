import json
import threading
import time

import zmq
import numpy as np
import ezmsg.core as ez
from ezmsg.util.debuglog import DebugLog
from ezmsg.util.messages.axisarray import AxisArray
from ezmsg.util.messages.chunker import ArrayChunker
from ezmsg.util.terminate import TerminateOnTotal, TerminateOnTimeout
from ezmsg.util.messagecodec import MessageDecoder

from ezmsg.zmq.pubsub import ZMQPollerUnit, ZMQSenderUnit
from ezmsg.zmq.util import ZMQMessage, SerializeMessage


def test_poller():
    port = 5557
    topic = "test_poller"
    state = {"running": True, "count": 0}

    comps = {
        "POLLER": ZMQPollerUnit(read_addr="tcp://127.0.0.1:" + str(port), zmq_topic=topic),
        "LOGGER": DebugLog(),
        "TERM": TerminateOnTotal(total=10)
    }
    conns = (
        (comps["POLLER"].OUTPUT, comps["LOGGER"].INPUT),
        (comps["LOGGER"].OUTPUT, comps["TERM"].INPUT_MESSAGE)
    )

    def pub_thread():
        ctx = zmq.Context()
        sock = ctx.socket(zmq.PUB)
        sock.bind("tcp://*:" + str(port))
        while state["running"]:
            sock.send(
                b"".join((
                    bytes(topic, "UTF-8"),
                    bytes(json.dumps(state), "UTF-8")
                )),
                flags=zmq.NOBLOCK,
            )
            state["count"] += 1
            time.sleep(0.05)
        sock.close()
    _thread = threading.Thread(target=pub_thread)
    _thread.daemon = True
    _thread.start()

    ez.run(components=comps, connections=conns)

    state["running"] = False
    _thread.join()


def test_sender():
    port = 5555
    topic = "test_sender"
    state = {"running": True, "count": 0}
    ntimes = 100
    nch = 8
    nfeats = 3
    data = np.arange(np.prod((ntimes, nch, nfeats))).reshape((ntimes, nch, nfeats))

    comps = {
        "SRC": ArrayChunker(data=data, chunk_len=10, axis=0, fs=100.0),
        "ENCODE": SerializeMessage(),  # From Any to ZMQMessage
        "PUB": ZMQSenderUnit(write_addr="tcp://*:" + str(port), zmq_topic=topic, wait_for_sub=True),
        "TERM": TerminateOnTimeout(time=1.0)
    }
    conns = (
        (comps["SRC"].OUTPUT_SIGNAL, comps["ENCODE"].INPUT),
        (comps["ENCODE"].OUTPUT, comps["PUB"].INPUT),
        (comps["SRC"].OUTPUT_SIGNAL, comps["TERM"].INPUT)
    )

    def sub_thread(res):
        ctx = zmq.Context()
        sock = ctx.socket(zmq.SUB)
        sock.connect("tcp://127.0.0.1:" + str(port))
        # sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, 500)
        sock.setsockopt(zmq.SUBSCRIBE, bytes(topic, "UTF-8"))
        while state["running"]:
            try:
                msg = sock.recv()
            except zmq.Again:
                continue
            payload = msg[len(topic):].decode("utf-8")
            axarr = json.loads(payload, cls=MessageDecoder)["obj"]
            res.append(axarr)
        sock.close()

    result = []
    _thread = threading.Thread(target=sub_thread, args=(result,))
    _thread.daemon = True
    _thread.start()
    time.sleep(0.1)

    ez.run(components=comps, connections=conns)

    state["running"] = False
    _thread.join()

    assert len(result) == 10
    cat = AxisArray.concatenate(*result, dim="time")
    assert np.array_equal(cat.data, data)
