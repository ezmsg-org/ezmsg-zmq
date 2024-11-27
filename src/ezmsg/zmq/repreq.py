import asyncio
import typing

import zmq
import zmq.asyncio
import ezmsg.core as ez

from .util import ZMQMessage


class ZMQRepSettings(ez.Settings):
    addr: str


class ZMQRepState(ez.State):
    context: zmq.asyncio.Context
    socket: zmq.asyncio.Socket
    queue: asyncio.Queue


class ZMQRep(ez.Unit):
    OUTPUT = ez.OutputStream(ZMQMessage)

    SETTINGS = ZMQRepSettings
    STATE = ZMQRepState

    def initialize(self) -> None:
        self.STATE.context = zmq.asyncio.Context()
        self.STATE.socket = self.STATE.context.socket(zmq.REP)
        ez.logger.debug(f"{self}:binding to {self.SETTINGS.addr}")
        self.STATE.socket.bind(self.SETTINGS.addr)
        self.STATE.queue = asyncio.Queue()

    def shutdown(self) -> None:
        self.STATE.socket.close()
        self.STATE.context.term()

    def _handle_req(self, data: bytes) -> bytes:
        return data

    @ez.task
    async def zmq_rep(self) -> None:
        while True:
            data = await self.STATE.socket.recv()
            response = self._handle_req(data)
            await self.STATE.socket.send(response)
            self.STATE.queue.put_nowait(data)

    @ez.publisher(OUTPUT)
    async def send_reqs(self) -> typing.AsyncGenerator:
        while True:
            data = await self.STATE.queue.get()
            yield self.OUTPUT, ZMQMessage(data)


class ZMQReqSettings(ez.Settings):
    addr: str


class ZMQReqState(ez.State):
    context: zmq.asyncio.Context
    socket: zmq.asyncio.Socket


class ZMQReq(ez.Unit):
    INPUT = ez.InputStream(ZMQMessage)
    OUTPUT = ez.OutputStream(ZMQMessage)

    SETTINGS = ZMQReqSettings
    STATE = ZMQReqState

    def initialize(self) -> None:
        self.STATE.context = zmq.asyncio.Context()
        self.STATE.socket = self.STATE.context.socket(zmq.REQ)
        ez.logger.debug(f"{self}:connecting to {self.SETTINGS.addr}")
        self.STATE.socket.connect(self.SETTINGS.addr)

    def shutdown(self) -> None:
        self.STATE.socket.close()
        self.STATE.context.term()

    @ez.subscriber(INPUT, zero_copy=True)
    @ez.publisher(OUTPUT)
    async def send_req(self, msg: ZMQMessage) -> None:
        await self.STATE.socket.send(msg.data)
        response = await self.STATE.socket.recv()
        yield self.OUTPUT, ZMQMessage(response)
