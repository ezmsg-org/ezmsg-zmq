import json
from pathlib import Path
import tempfile

import numpy as np
import ezmsg.core as ez
from ezmsg.util.messages.axisarray import AxisArray
from ezmsg.util.messagelogger import log_object, MessageLogger
from ezmsg.util.messagecodec import MessageDecoder, message_log
from ezmsg.util.messages.chunker import ArrayChunker
from ezmsg.util.terminate import TerminateOnTotal

from ezmsg.zmq.util import SerializeMessage, DeserializeBytes


def test_encdec():
    msg = AxisArray(
        data=np.arange(np.prod((3, 4, 5))).reshape(3, 4, 5),
        dims=["time", "ch", "feat"],
        axes={
            "time": AxisArray.TimeAxis(fs=1000.0, offset=0.0),
            "ch": AxisArray.CoordinateAxis(np.array(["a", "b", "c", "d"]), dims=["ch"]),
            "feat": AxisArray.CoordinateAxis(
                data=np.array(["f1", "f2", "f3", "f4", "f5"]), dims=["feat"]
            ),
        },
        key="test_log_object",
    )
    encoded_msg = log_object(msg)
    decoded_msg = json.loads(encoded_msg, cls=MessageDecoder)["obj"]
    assert np.array_equal(decoded_msg.data, msg.data)
    assert np.array_equal(decoded_msg.axes["ch"].data, msg.axes["ch"].data)
    assert np.array_equal(decoded_msg.axes["feat"].data, msg.axes["feat"].data)
    assert decoded_msg.key == msg.key


def test_encdec_system():
    ntimes = 100
    nch = 8
    nfeats = 3
    data = np.arange(np.prod((ntimes, nch, nfeats))).reshape((ntimes, nch, nfeats))
    file_path = Path(tempfile.gettempdir())
    file_path = file_path / Path("test_serialize_message.txt")

    comps = {
        "SRC": ArrayChunker(data=data, chunk_len=10, axis=0, fs=100.0),
        "SERIALIZE": SerializeMessage(),
        "DESERIALIZE": DeserializeBytes(),
        "LOG": MessageLogger(output=file_path),
        "TERM": TerminateOnTotal(total=10),
    }
    conns = (
        (comps["SRC"].OUTPUT_SIGNAL, comps["SERIALIZE"].INPUT),
        (comps["SERIALIZE"].OUTPUT, comps["DESERIALIZE"].INPUT),
        (comps["DESERIALIZE"].OUTPUT_SIGNAL, comps["LOG"].INPUT_MESSAGE),
        (comps["LOG"].OUTPUT_MESSAGE, comps["TERM"].INPUT_MESSAGE),
    )
    ez.run(components=comps, connections=conns)

    result = list(message_log(file_path))
    assert len(result) == 10
    cat = AxisArray.concatenate(*result, dim="time")
    assert np.array_equal(cat.data, data)

    file_path.unlink(missing_ok=True)
