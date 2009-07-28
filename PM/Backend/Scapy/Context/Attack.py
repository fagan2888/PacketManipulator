#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2008 Adriano Monteiro Marques
#
# Author: Francesco Piccinno <stack.box@gmail.com>
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

import time
import socket

from threading import Thread

from PM.Core.I18N import _
from PM.Core.Logger import log
from PM.Core.Atoms import ThreadPool, defaultdict
from PM.Manager.AttackManager import AttackDispatcher, IL_TYPE_ETH

from PM.Backend.Scapy import *

# These should be moved outside.

ERR_TIMEOUT   = 0
ERR_EXCEPTION = 1

class SendWorker(object):
    def __init__(self, sck, mpkts, repeat=1, delay=None, oncomplete=None, \
                 onerror=None, timeout=None, onrecv=None, onreply=None, \
                 udata=None):

        if isinstance(mpkts, MetaPacket):
            mpkts = [mpkts]

        # Core attributes
        self.socket = sck
        self.mpkts = mpkts

        # Timeouts and repeat
        self.repeat = repeat
        self.delay = delay
        self.timeout = timeout
        self.lastrecv = None

        # Callables
        self.oncomplete = oncomplete
        self.onerror = onerror
        self.onrecv = onrecv
        self.onreply = onreply
        self.udata = udata

        # Num of answers excepted
        self.ans_left = len(mpkts)

def register_attack_context(BaseAttackContext):
    class AttackContext(BaseAttackContext):
        """
        Here we have 3 different function types:
         - s_l{2,3,b} (mpkts = A single MetaPacket or a list,
                       repeat = how many time send the mpkts (-1 for infinite),
                       delay = time between two send,
                       oncomplete = callable or None,
                       onerror = callable or None)
         - sr_l{2,3,b} (**same arguments of s_l***,
                        timeout = if no reply between ts than stop send
                        onrecv = callable,
                        onreply = callable)
         - si_l{2,3,b} (mpkt) -> immediate send a single packet

        NB: timeout parameter is in seconds, while delay in msecs

        Prototypes for callbacks:
         - onerror(send, status, udata)
         - onreply(send, orig, ans, udata)
         - onrecv(send, mpkt, udata)
        """

        def __init__(self, dev1, dev2=None, bpf_filter=None, capmethod=0):
            BaseAttackContext.__init__(self, dev1, dev2, bpf_filter, capmethod)

            self.internal = False
            self.thread1 = None
            self.thread2 = None

            self.thread_pool = ThreadPool()
            self.attack_dispatcher = None

            self.ans_dict = defaultdict(list)
            self.receivers = [] # A list of callable

            if dev2:
                self.title = self.summary = _('Attack on %s:%s' % (dev1, dev2))
            else:
                self.title = self.summary = _('Attack on %s' % dev1)

            log.debug('Creating send sockets')

            try:
                # Here we create L2 and L3 sockets used to send packets
                self._l2_socket = conf.L2socket(iface=dev1)
                self._l3_socket = conf.L3socket(iface=dev1)

                if dev2:
                    self._lb_socket = conf.L2socket(iface=dev2)

                if capmethod == 0:
                    log.debug('Creating listen sockets')

                    self._listen_dev1 = conf.L2listen(iface=dev1,
                                                      filter=bpf_filter)

                    if dev2:
                        self._listen_dev2 = conf.L2listen(iface=dev2,
                                                          filter=bpf_filter)

                    # Get datalink
                    try:
                        if self._listen_dev1.LL in conf.l2types.layer2num:
                            linktype = \
                                conf.l2types.layer2num[self._listen_dev1.LL]
                        elif self._listen_dev1.LL in conf.l3types.layer2num:
                            linktype = \
                                conf.l3types.layer2num[self._listen_dev1.LL]
                        else:
                            log.debug('Falling back to IL_TYPE_ETH as DL')
                            linktype = IL_TYPE_ETH
                    except:
                        try:
                            linktype = self._listen_dev1.ins.datalink()
                        except:
                            log.debug('It seems that we\'re using PF_PACKET'
                                      ' socket. Using IL_TYPE_ETH as DL')
                            linktype = IL_TYPE_ETH

                    self.attack_dispatcher = AttackDispatcher(linktype)
                else:
                    log.debug('Creating helper processes')

                    self._listen_dev1 = run_helper(self.capmethod - 1, dev1,
                                                   bpf_filter)

                    if dev2:
                        self._listen_dev2 = run_helper(self.capmethod - 1, dev2,
                                                       bpf_filter)

            except socket.error, (errno, err):
                self.summary = str(err)
                return

            except Exception, err:
                self.summary = str(err)

        ########################################################################
        # Threads callbacks
        ########################################################################

        def _stop(self):
            if self.internal:
                log.error('Attack is already stopped')
                return False

            self.internal = False

            log.debug('Joining threads')

            if self.thread1:
                self.thread1.join()

            if self.thread2:
                self.thread2.join()

            log.debug('AttackContext succesfully stopped')

        def _start(self):
            if self.internal:
                log.error('Attack is already running')
                return False

            if not self._listen_dev1:
                log.error('We\'ve got an error in __init__. No listen socket')
                return False

            self.internal = True

            log.debug('Spawning capture threads')

            func = (self.capmethod == 0 and \
                    self.__sniff_thread or \
                    self.__helper_thread)

            self.thread1 = Thread(None, func, 'ATK1', (self._listen_dev1, ))
            self.thread1.setDaemon(True)
            self.thread1.start()

            if self._listen_dev2:
                self.thread2 = Thread(None, func, 'ATK2', (self._listen_dev2, ))
                self.thread2.setDaemon(True)
                self.thread2.start()

            log.debug('Spawning thread pool for sending')
            self.thread_pool.start()

            return True

        def __helper_thread(self, obj):
            errstr = _('Attack finished')

            try:
                for reader in bind_reader(obj[0], obj[1]):
                    if not self.internal:
                        break

                    if reader:
                        reader, outfile_size, position = reader
            except OSError, err:
                errstr = err.strerror
                self.internal = False
            except Exception, err:
                errstr = str(err)
                self.internal = False

            self.attack_dispatcher = AttackDispatcher(reader.linktype)

            log.debug('Entering in the helper mainloop')

            reported_packets = 0

            while self.internal:
                report_idx = get_n_packets(obj[0])

                if report_idx < reported_packets:
                    continue

                while reported_packets < report_idx:
                    r = reader.read_packet()

                    if not r:
                        break

                    self.__manage_mpkt(obj, MetaPacket(r))

                    reported_packets += 1

                report_idx = reported_packets

            self.summary = errstr

        def __sniff_thread(self, obj):
            errstr = _('Attack finished')

            log.debug('Entering in the native mainloop')

            while self.internal:
                r = None

                try:
                    if WINDOWS:
                        try:
                            r = obj.recv(MTU)
                        except PcapTimeoutElapsed:
                            continue
                    else:
                        inmask = [obj]
                        inp, out, err = select(inmask, inmask, inmask, None)

                        if obj in inp:
                            r = obj.recv(MTU)

                    if r is None:
                        continue

                    self.__manage_mpkt(obj, MetaPacket(r))

                except Exception, err:
                    if self.internal:
                        errstr = str(err)

                    self.internal = False
                    break

            self.summary = errstr

        def __manage_mpkt(self, obj, mpkt):
            found = False
            layer = 2

            while not found and layer <= 3:
                if layer == 2:
                    cpkt = mpkt.root
                elif is_proto(mpkt.root.payload):
                    cpkt = mpkt.root.payload
                else:
                    break

                idx = 0
                hashret = cpkt.hashret()
                lst = self.ans_dict[hashret]

                if hashret in self.ans_dict:
                    for ans, send, cnt in lst:
                        if cpkt.answers(ans.root):
                            send.ans_left -= 1
                            lst[idx][2] -= 1

                            if lst[idx][2] < 1:
                                del lst[idx]

                                if not lst:
                                    del self.ans_dict[hashret]

                            send.onreply(send, mpkt, ans, send.udata)

                            if send.ans_left == 0 and not send.timeout:
                                log.debug('Stopping SendWorker')
                                self.cancel_send(send)

                            found = True
                            break

                        idx += 1
                layer += 1


            if not found:
                for rcv in self.receivers:
                    if isinstance(rcv, SendWorker):
                        if callable(rcv.onrecv):
                            rcv.onrecv(rcv, mpkt, rcv.udata)
                    elif callable(rcv):
                        rcv((obj is self._listen_dev1 and \
                             self.socket1 or self.socket2), mpkt)

            self.attack_dispatcher.feed(mpkt)

        ########################################################################
        # Worker functions
        ########################################################################

        def __worker_thread(self, send):
            while send.repeat > 0:
                send.ans_left = len(send.mpkts)

                for mpkt in send.mpkts:

                    if callable(send.onreply):
                        idx = 0
                        found = False
                        lst = self.ans_dict[mpkt.hashret()]

                        for pmpkt, psend, pcnt in lst:
                            if psend is send and pmpkt is mpkt:
                                found = True
                                break
                            idx += 1

                        if found:
                            lst[idx][2] += 1
                            print lst[idx]
                        else:
                            lst.append([mpkt, send, 1])

                    send.socket.send(mpkt.root)

                    if send.delay:
                        time.sleep(send.delay / 1000.0)

                send.repeat -= 1
                log.debug('%d left' % send.repeat)

            # Now we have sent all the packets. We have to wait for the replies
            # but between timeout.

            if not callable(send.onrecv) and not callable(send.onreply):
                log.debug('Pure send process complete')

                if callable(send.oncomplete):
                    send.oncomplete()

                return

            if send.timeout > 0:
                # If timeout is not setted we've to leave it
                log.debug('Send complete for %s. Waiting for timeout' % send)

                if send.ans_left > 0:
                    time_left = send.timeout * 1000
                    delay = max(100, send.delay)

                    while time_left > send.delay:
                        if send.ans_left == 0:
                            break

                        time_left -= delay
                        time.sleep(delay / 1000.0)

                if send.ans_left == 0:
                    log.debug('Send process complete')

                    if callable(send.oncomplete):
                        send.oncomplete()
                else:
                    log.debug('Send process complete with %d pending replies' \
                              % send.ans_left)

                    if callable(send.onerror):
                        send.onerror(send, ERR_TIMEOUT, send.udata)

                self.cancel_send(send)
            else:
                log.debug('No timeout setted. Exiting after completion')

        ########################################################################
        # Public functions
        ########################################################################

        def cancel_send(self, send):
            assert isinstance(send, SendWorker)

            log.debug('Removing %s SendWorker' % send)

            if callable(send.onrecv):
                try:
                    self.receivers.remove(send)
                except ValueError:
                    log.warning('The callback was already removed.')

            if not callable(send.onreply):
                return

            removed = 0

            for mpkt in send.mpkts:
                try:
                    idx = 0
                    lst = self.ans_dict[mpkt.hashret()]
                    for pmpkt, psend, pcnt in lst:
                        if pmpkt is mpkt and psend is send:
                            del lst[idx]
                            break
                        idx = 0
                    removed += 1
                except ValueError:
                    continue

            if removed == len(send.mpkts):
                log.debug('SendWorker object succesfully removed')
            else:
                log.error('It seems that we\'ve leaved it dirty')

            del send

        ########################################################################
        # Pure send functions
        ########################################################################

        def s_l2(self, mpkts, repeat=1, delay=None, oncomplete=None, \
                 onerror=None, udata=None):
            """Send packets at Layer 2"""
            return self.__sendrcv(self.l2_socket, mpkts, repeat, delay, \
                                   oncomplete, onerror, udata)

        def s_l3(self, mpkts, repeat=1, delay=None, oncomplete=None, \
                 onerror=None, udata=None):
            """Send packets at Layer 3"""
            return self.__sendrcv(self.l3_socket, mpkts, repeat, delay, \
                                   oncomplete, onerror, udata)

        def s_lb(self, mpkts, repeat=1, delay=None, oncomplete=None, \
                 onerror=None, udata=None):
            """Send packets to the bridge interface at Layer 2"""
            return self.__sendrcv(self.lb_socket, mpkts, repeat, delay, \
                                   oncomplete, onerror, udata)

        ########################################################################
        # Send and receive functions
        ########################################################################

        def sr_l2(self, mpkts, repeat=1, delay=None, timeout=None, \
                 oncomplete=None, onerror=None, onreply=None, onrecv=None, \
                 udata=None):
            """Send and receive packets at Layer 2"""
            return self.__sendrcv(self.l2_socket, mpkts, repeat, delay, \
                                  oncomplete, onerror, timeout, onrecv, \
                                  onreply, udata)

        def sr_l3(self, mpkts, repeat=1, delay=None, timeout=None, \
                 oncomplete=None, onerror=None, onreply=None, onrecv=None, \
                 udata=None):
            """Send and receive packets at Layer 3"""
            return self.__sendrcv(self.l3_socket, mpkts, repeat, delay, \
                                  oncomplete, onerror, timeout, onrecv, \
                                  onreply, udata)

        def sr_lb(self, mpkts, repeat=1, delay=None, timeout=None, \
                 oncomplete=None, onerror=None, onreply=None, onrecv=None, \
                 udata=None):
            """Send and receive packets at Layer 3"""
            return self.__sendrcv(self.lb_socket, mpkts, repeat, delay, \
                                  oncomplete, onerror, timeout, onrecv, \
                                  onreply, udata)

        def si_l2(self, mpkt):
            """Send immediate at Layer 2"""
            self.l2_socket.send(mpkt.root)
        def si_l3(self, mpkt):
            """Send immediate at Layer 3"""
            self.l3_socket.send(mpkt.root)
        def si_lb(self, mpkt):
            """Send immediate to the bridge Layer 2"""
            self.lb_socket.send(mpkt.root)

        def __sendrcv(self, sck, mpkts, repeat=1, delay=None, \
                      oncomplete=None, onerror=None, timeout=None, \
                      onrecv=None, onreply=None, udata=None):
            """
            General function used by the various s_l{2,3,b} and sr_l{2,3,b}
            public methods.
            """

            assert sck, 'Socket cannot be null'

            timeout = max(0, timeout)
            delay = max(0, delay)
            repeat = max(1, repeat)

            send = SendWorker(sck, mpkts, repeat, delay, oncomplete, onerror, \
                              timeout, onrecv, onreply, udata)

            if callable(onrecv):
                log.debug('Appending to the list of receivers')
                self.receivers.append(send)

            # Than put directly on the queue
            self.thread_pool.queue_work(None, None, self.__worker_thread, send)

            return send

    return AttackContext
