
#
# PyGoWave Server - The Python Google Wave Server
# Copyright 2009 Patrick Schneider <patrick.p2k.schneider@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from twisted.internet.protocol import Protocol, ReconnectingClientFactory
from twisted.internet.task import LoopingCall

import stomper, simplejson

from c2s_mp import PyGoWaveClientMessageProcessor

from django.conf import settings

__all__ = ["StompClientFactory"]

class StompMessageProcessor(stomper.Engine):
	def __init__(self):
		super(StompMessageProcessor, self).__init__()
		self.username = getattr(settings, "RPC_USER", "pygowave_server")
		self.password = getattr(settings, "RPC_PASSWORD", "pygowave_server")
		self.pygo_mp = PyGoWaveClientMessageProcessor()
	
	def connect(self):
		"""Generate the STOMP connect command to get a session."""
		self.pygo_mp.logger.info("=> PyGoWave RPC Server starting <=")
		return stomper.connect(self.username, self.password)
	
	def connected(self, msg):
		"""Once I've connected I want to subscribe to my the message queue."""
		super(StompMessageProcessor, self).connected(msg)
		
		self.pygo_mp.logger.info("=> PyGoWave RPC Server ready <=")
		
		f = stomper.Frame()
		f.unpack(stomper.subscribe("wavelet_rpc_singlethread"))
		f.headers["exchange"] = "wavelet.topic"
		f.headers["routing_key"] = "#.#.clientop"
		f.headers["exchange_type"] = "topic"
		return f.pack()
	
	def ack(self, message):
		rkey = message["headers"]["destination"]
		message_data = simplejson.loads(message["body"].decode("utf-8"))
		
		msg_dict = self.pygo_mp.process(rkey, message_data)
		
		out_frames = ""
		for out_rkey, messages in msg_dict.iteritems():
			out_frames += self.send(out_rkey, messages)
		
		return super(StompMessageProcessor, self).ack(message) + out_frames

	def send(self, routing_key, message_data):
		"""Convert a routing_key and data dictionary into a STOMP message."""
		f = stomper.Frame()
		f.unpack(stomper.send(routing_key, simplejson.dumps(message_data)))
		f.headers["exchange"] = "wavelet.direct"
		f.headers["content-type"] = "application/json"
		return f.pack().encode("utf-8")
	
	def purge_connections(self):
		"""Forwards to PyGoWaveClientMessageProcessor"""
		self.pygo_mp.purge_connections()

class StompClientProtocol(Protocol):
	def __init__(self):
		self.mp = StompMessageProcessor()
		self.stompBuffer = stomper.stompbuffer.StompBuffer()
	
	def connectionMade(self):
		"""Register with the stomp server."""
		self.factory.connection = self
		self.transport.write(self.mp.connect())
		self.lc = LoopingCall(self.mp.pygo_mp.purge_connections)
		self.lc.start(10 * 60) # Purge every 10 minutes
		self.lc2 = LoopingCall(self.mp.pygo_mp.log_stats)
		self.lc2.start(60 * 60, now=False) # Stats every 60 minutes
	
	def connectionLost(self, reason):
		if self.lc.running:
			self.lc.stop()
	
	def dataReceived(self, data):
		"""Data received, react to it and respond."""
		self.stompBuffer.appendData(data.replace('\0', '\0\n'))
		
		while True:
			msg = self.stompBuffer.getOneMessage()
			
			if self.stompBuffer.buffer.startswith('\n'):
				self.stompBuffer.buffer = self.stompBuffer.buffer[1:]
			
			if msg is None:
				break
			
			returned = self.mp.react(msg)
			if returned:
				self.transport.write(returned)

class StompClientFactory(ReconnectingClientFactory):
	protocol = StompClientProtocol
	
	def startedConnecting(self, connector):
		"""Started to connect."""
	
	def clientConnectionLost(self, connector, reason):
		"""Lost connection."""
	
	#def clientConnectionFailed(self, connector, reason):
	#	"""Connection failed."""
	#	super(StompClientFactory, self).clientConnectionFailed(connector, reason)
	
	def __repr__(self):
		return "StompClientFactory"
