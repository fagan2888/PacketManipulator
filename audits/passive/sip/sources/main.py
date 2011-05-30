#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2008 Adriano Monteiro Marques
#
# Author: Francesco Piccinno <stack.box@gmail.com>
# Author: Guilherme Rezende <guilhermebr@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA

"""
SIP protocol dissector (Passive audit)
"""

from umit.pm.core.logger import log
from umit.pm.gui.plugins.engine import Plugin
from umit.pm.manager.auditmanager import *
from umit.pm.manager.sessionmanager import SessionManager

SIP_NAME = 'dissector.sip'
SIP_PORTS = (5060, 5061)

SIP_REQUEST  = 0
SIP_RESPONSE = 1

sip_fields = None

class SipSession(object):
     
     def __init__(self, mpkt, manager, sessions, sip_type):
          self.manager = manager
          self.payload = mpkt.data
           
          self.sess = sessions.lookup_session(mpkt, SIP_PORTS, SIP_NAME)
          
          if not self.sess:
               self.sess = sessions.lookup_session(mpkt, SIP_PORTS, SIP_NAME, True)
               self.sess.data = dict(
                    map(lambda x: (x, 'None'), sip_fields.split(','))
               )
               
          print self.sess.data
          
          if sip_type == SIP_REQUEST:
               return self.sip_request(mpkt)
          else: 
               return self.sip_response(mpkt)
            
     def sip_request(self, mpkt):
                        
          if self.payload.startswith('REGISTER'):
               print 'REGISTER'
                              
          elif self.payload.startswith('INVITE'):
               print 'INVITE'
               
          end = self.payload.find('\n')
          while end is not -1:
               print "DATA: %s" % self.payload[:end]
               self.payload = self.payload[end + 1:]
               end = self.payload.find('\n')


               
          self.manager.user_msg('SIP REQUEST: %s:%d' % \
                           (mpkt.l3_src, mpkt.l4_src), 6, SIP_NAME)

     def sip_response(self, mpkt):
       
          self.manager.user_msg('SIP RESPONSE: %s:%d'  % \
                           (mpkt.l3_src, mpkt.l4_src),
                           6, SIP_NAME)
   
    
class SIPMonitor(Plugin, PassiveAudit):
     def start(self, reader):
          self.manager = AuditManager()
          self.sessions = SessionManager()
       
          conf = self.manager.get_configuration(SIP_NAME)
          
          global sip_fields
                         
          sip_fields = conf['sip_fields']
          

     def register_decoders(self):

          self.manager.register_hook_point('sip')

          for port in SIP_PORTS:
               self.manager.add_dissector(APP_LAYER_UDP, port,
                                          self.__sip_dissector)
        

     def stop(self):
          for port in SIP_PORTS:
               self.manager.remove_dissector(APP_LAYER_UDP, port,
                                             self.__sip_dissector)
               
               self.manager.deregister_hook_point('sip')
               
     def __sip_dissector(self, mpkt):
          
          payload = mpkt.data

          
          if not payload:
               return None
          
          #print payload

          if payload.startswith('SIP/'):
               sip_type = SIP_RESPONSE
          elif payload.find('SIP/'):
               sip_type = SIP_REQUEST
          else:
               return None

               
          obj = SipSession(mpkt, self.manager, self.sessions, sip_type)

          
               
               
__plugins__ = [SIPMonitor]
__plugins_deps__ = [('SIPDissector', ['UDPDecoder'], ['SIPDissector-1.0'], []),]
__author__ = ['Guilherme Rezende']
__audit_type__ = 0
__protocols__ = (('udp', 5060), ('udp', 5061), ('sip', None))
__configurations__ = ((SIP_NAME, {
    'sip_fields' : ["contact,to,via,from,user-agent,server,authorization,www-authenticate",

                    'A coma separated string of sip fields'],
    }),
)
__vulnerabilities__ = (('SIP dissector', {
    'description' : 'SIP Monitor plugin'
        'The Session Initiation Protocol (SIP) is an IETF-defined signaling protocol,'
        'widely used for controlling multimedia communication sessions'
        'such as voice and video calls over' 
        'Internet Protocol (IP). The protocol can be used for creating,'
        'modifying and terminating two-party (unicast) or multiparty (multicast)'
        'sessions consisting of one or several media streams.'
        'The modification can involve changing addresses or ports, inviting more' 
        'participants, and adding or deleting media streams. Other feasible'
        'application examples include video conferencing, streaming multimedia distribution,'
        'instant messaging, presence information, file transfer and online games.'
        'SIP was originally designed by Henning Schulzrinne and Mark Handley starting in 1996.'
        'The latest version of the specification is RFC 3261 from the IETF Network Working'
        'Group. In November 2000, SIP was accepted as a 3GPP signaling protocol and permanent'
        'element of the IP Multimedia Subsystem (IMS) architecture for IP-based streaming'
        'multimedia services in cellular systems.',
    'references' : ((None, 'http://en.wikipedia.org/wiki/'
                            'Session_Initiation_Protocol'), )
    }),
)