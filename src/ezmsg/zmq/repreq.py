import asyncio
import typing

import zmq
import zmq.asyncio
import ezmsg.core as ez
from zmq.utils.monitor import parse_monitor_message

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
    monitor: zmq.asyncio.Socket


class ZMQReq(ez.Unit):
    INPUT = ez.InputStream(ZMQMessage)
    OUTPUT = ez.OutputStream(ZMQMessage)

    SETTINGS = ZMQReqSettings
    STATE = ZMQReqState

    def initialize(self) -> None:
        self.STATE.context = zmq.asyncio.Context()
        self.STATE.socket = self.STATE.context.socket(zmq.REQ)
        self.STATE.monitor = self.STATE.socket.get_monitor_socket()
        ez.logger.debug(f"{self}:connecting to {self.SETTINGS.addr}")
        self.STATE.socket.connect(self.SETTINGS.addr)
        self._has_server = False

    def shutdown(self) -> None:
        self.STATE.monitor.close()
        self.STATE.socket.close()
        self.STATE.context.term()

    @ez.task
    async def _socket_monitor(self) -> None:
        while True:
            monitor_result = await self.STATE.monitor.poll(100, zmq.POLLIN)
            if monitor_result:
                data = await self.STATE.monitor.recv_multipart()
                evt = parse_monitor_message(data)
                event = evt["event"]
                if event == zmq.EVENT_CONNECTED:
                    self._has_server = True
                elif event == zmq.EVENT_DISCONNECTED:
                    self._has_server = False

    @ez.subscriber(INPUT, zero_copy=True)
    @ez.publisher(OUTPUT)
    async def send_req(self, msg: ZMQMessage) -> None:
        if self._has_server:
            await self.STATE.socket.send(msg.data)
            response = await self.STATE.socket.recv()
            yield self.OUTPUT, ZMQMessage(response)
