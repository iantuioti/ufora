#   Copyright 2016 Ufora Inc.
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import time
import os
import socket
import sys
import logging
import traceback

import pyfora.worker.worker as worker
import pyfora.worker.Common as Common
import pyfora.worker.Messages as Messages
import pyfora.worker.SubprocessRunner as SubprocessRunner


class WorkerConnection:
    def __init__(self, proc, socket_name, socket_dir):
        self.proc = proc
        self.socket_name = socket_name
        self.socket_dir = socket_dir

    def answers_self_test(self):
        sock = None
        try:
            logging.info("Starting self-test on %s", self.socket_name)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(os.path.join(self.socket_dir, self.socket_name))

            Common.writeAllToFd(sock.fileno(), Messages.MSG_TEST)
            Common.writeString(sock.fileno(), "msg")
            return Common.readString(sock.fileno()) == "msg"
        except:
            logging.error("Couldn't communicate with %s:\n%s", self.socket_name, traceback.format_exc())
            return False
        finally:
            logging.info("Done with self-test on %s", self.socket_name)
            try:
                sock.close()
            except:
                pass

    def teardown(self):
        logging.error("Worker %s appears dead. Removing it.", self.socket_name)
        self.proc.terminate()
        self.proc.wait()
        logging.error("Terminated %s successfully.", self.socket_name)

        self.remove_socket()

    def remove_socket(self):
        try:
            os.unlink(os.path.join(self.socket_dir, self.socket_name))
        except OSError:
            pass




class Spawner:
    def __init__(self, socket_dir, selector_name, max_processes):
        self.selector_name = selector_name
        self.socket_dir = socket_dir
        self.max_processes = max_processes

        self.selector_socket_path = os.path.join(socket_dir, selector_name)

        self.busy_workers = []
        self.waiting_workers = []

        self.waiting_sockets = []

        self.index = 0

    def clearPath(self):
        # Make sure the socket does not already exist
        try:
            os.unlink(self.selector_socket_path)
        except OSError:
            if os.path.exists(self.selector_socket_path):
                raise UserWarning("Couldn't clear named socket at %s", self.selector_socket_path)

    def teardown(self):
        self.clearPath()

    def start_worker(self):
        index = self.index
        self.index += 1

        worker_name = "worker_%s" % index
        worker_socket_path = os.path.join(self.socket_dir, worker_name)

        def onStdout(msg):
            logging.info("%s out> %s", worker_name, msg)

        def onStderr(msg):
            logging.info("%s err> %s", worker_name, msg)

        childSubprocess = SubprocessRunner.SubprocessRunner(
            [sys.executable, worker.__file__, worker_socket_path],
            onStdout,
            onStderr
            )

        self.waiting_workers.append(WorkerConnection(childSubprocess, worker_name, self.socket_dir))

        childSubprocess.start()

        t0 = time.time()
        TIMEOUT = 10
        while not os.path.exists(worker_socket_path) and time.time() - t0 < TIMEOUT:
            time.sleep(0.001)

        if not os.path.exists(worker_socket_path):
            raise UserWarning("Couldn't start another worker.")
        else:
            logging.info("Started worker %s with %s busy and %s idle", worker_name, len(self.busy_workers), len(self.waiting_workers))


    def terminate_workers(self):
        for w in self.busy_workers + self.waiting_workers:
            w.proc.terminate()
            w.proc.wait()
            os.unlink(os.path.join(self.socket_dir, w.socket_name))

    def can_start_worker(self):
        return self.max_processes is None or len(self.busy_workers) < self.max_processes

    def get_valid_worker(self):
        while True:
            if not self.waiting_workers and self.can_start_worker():
                self.start_worker()
            elif self.waiting_workers:
                #if we have one, use it
                worker = self.waiting_workers.pop(0)

                #make sure the worker is happy
                if not worker.answers_self_test():
                    worker.teardown()
                else:
                    return worker
            else:
                if not self.check_all_busy_workers():
                    return None

    def check_all_busy_workers(self):
        new_busy = []

        for worker in self.busy_workers:
            if worker.proc.poll() is not None:
                #this worker is dead!
                logging.info("worker %s was busy but looks dead to us", worker.socket_name)
                worker.proc.wait()
                worker.remove_socket()
            else:
                new_busy.append(worker)

        if len(new_busy) != len(self.busy_workers):
            self.busy_workers = new_busy

            logging.info("Now, we have %s busy and %s idle workers", len(self.busy_workers), len(self.waiting_workers))
            return True
        return False

    def apply_worker_to_waiting_socket(self, worker):
        self.busy_workers.append(worker)
        waiting_connection = self.waiting_sockets.pop(0)

        Common.writeString(waiting_connection.fileno(), worker.socket_name)

    def start_workers_if_necessary(self):
        self.check_all_busy_workers()
        
        while self.waiting_sockets and self.can_start_worker():
            worker = self.get_valid_worker()
            assert worker is not None
            self.apply_worker_to_waiting_socket(worker)

    def listen(self):
        logging.info("Setting up listening on %s with max_processes=%s", self.selector_socket_path, self.max_processes)
        
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(self.selector_socket_path)
        sock.listen(30)

        try:
            while True:
                sock.settimeout(.1)
                connection = None

                try:
                    connection, _ = sock.accept()
                except socket.timeout as e:
                    pass

                if connection is not None:
                    if self.handleConnection(connection):
                        return
                    self.start_workers_if_necessary()


        except KeyboardInterrupt:
            logging.info("shutting down due to keyboard interrupt")
            self.terminate_workers()
        finally:
            sock.close()

    def handleConnection(self, connection):
        first_byte = Common.readAtLeast(connection.fileno(), 1)

        if first_byte == Messages.MSG_SHUTDOWN:
            logging.info("Received termination message with %s workers remaining", len(self.busy_workers + self.waiting_workers))
            self.terminate_workers()
            logging.info("workers terminating. Shutting down.")
            connection.close()

            return True
        elif first_byte == Messages.MSG_GET_WORKER:
            #try to start a worker
            worker = self.get_valid_worker()

            if worker is not None:
                self.busy_workers.append(worker)

                Common.writeString(connection.fileno(), worker.socket_name)
                connection.close()
            else:
                #otherwise wait for one to come available
                self.waiting_sockets.append(connection)

            self.start_workers_if_necessary()

        elif first_byte == Messages.MSG_RELEASE_WORKER:
            worker_name = Common.readString(connection.fileno())
            worker_ix = [ix for ix,w in enumerate(self.busy_workers) if w.socket_name == worker_name][0]

            worker = self.busy_workers[worker_ix]
            self.busy_workers.pop(worker_ix)

            connection.close()

            if worker.answers_self_test():
                #see if anybody wants to use this worker
                if self.waiting_sockets:
                    self.apply_worker_to_waiting_socket(worker)
                else:
                    self.waiting_workers.append(worker)
            else:
                worker.teardown()

        else:
            assert False, "unknown byte: " + first_byte
            


