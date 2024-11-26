from dataclasses import dataclass
# from dataclasses import asdict
import json
from pickle import PickleBuffer
import typing

import ezmsg.core as ez
from ezmsg.util.messages.axisarray import AxisArray
from ezmsg.util.messagelogger import log_object
from ezmsg.util.messagecodec import MessageDecoder


class ZeroCopyBytes(bytes):
    def __reduce_ex__(self, protocol):
        if protocol >= 5:
            return type(self)._reconstruct, (PickleBuffer(self),), None
        else:
            # PickleBuffer is forbidden with pickle protocols <= 4.
            return type(self)._reconstruct, (bytes(self),)

    @classmethod
    def _reconstruct(cls, obj):
        with memoryview(obj) as m:
            # Get a handle over the original buffer object
            obj = m.obj
            if isinstance(obj, cls):
                # Original buffer object is a ZeroCopyBytes, return it
                # as-is.
                return obj
            else:
                return cls(obj)


@dataclass
class ZMQMessage:
    data: bytes


def serialize_msg(msg: typing.Any) -> bytes:
    return log_object(msg).encode("utf-8")


"""
The following alternative to serialize_msg might be faster because it doesn't convert numpy arrays to ascii.

class NumpyArrayEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "tolist"):
            # Likely numpy array to list
            return obj.tolist()
        else:
            return json.JSONEncoder.default(self, obj)


def serialize_msg(msg: typing.Any) -> bytes:
    return json.dumps(asdict(msg), cls=NumpyArrayEncoder).encode("utf-8")
"""


class SerializeMessageSettings(ez.Settings):
    fun: typing.Callable = serialize_msg
    """
    Function to serialize the message. Must take a single argument and return a bytes object.
    """


class SerializeMessage(ez.Unit):
    SETTINGS: SerializeMessageSettings

    INPUT = ez.InputStream(typing.Any)
    OUTPUT = ez.OutputStream(ZMQMessage)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def on_message(self, message: typing.Any) -> typing.AsyncGenerator:
        encoded = self.SETTINGS.fun(message)
        yield self.OUTPUT, ZMQMessage(data=encoded)


class DeserializeBytes(ez.Unit):
    INPUT = ez.InputStream(bytes)
    OUTPUT_SIGNAL = ez.OutputStream(AxisArray)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT_SIGNAL)
    async def deserialize(self, msg: ZMQMessage) -> typing.AsyncGenerator:
        decoded_msg = json.loads(msg.data, cls=MessageDecoder)["obj"]
        yield self.OUTPUT_SIGNAL, decoded_msg
