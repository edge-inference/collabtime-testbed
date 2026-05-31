"""
ROS 2 to Lingua Franca Bridge

This node acts as a bridge between ROS 2 agents and the LF Coordinator federates.
It translates ROS 2 service calls into messages that the LF federate can process.
"""

import rclpy
from rclpy.node import Node
from interfaces.srv import ClaimTask, CompleteTask, GetAvailableTasks, CreateTask
from interfaces.msg import TaskInfo, TaskEvent
import socket
import json
import threading
import time
import os
import csv


class LFBridgeNode(Node):
    """
    Bridge between ROS 2 and Lingua Franca Coordinator
    
    This node:
    1. Provides ROS 2 services (same API as coord_node.py)
    2. Forwards requests to local LF federate via socket
    3. Returns responses to ROS 2 agents
    """
    
    def __init__(self):
        super().__init__('lf_bridge_node')
        
        self.declare_parameter('device_id', 1)
        self.declare_parameter('lf_port', 9000)
        
        self.device_id = self.get_parameter('device_id').value
        self.lf_port = self.get_parameter('lf_port').value
        
        # Socket connection to LF federate
        self.lf_socket = None
        self.connect_to_lf()
        
        # ROS 2 Services (same interface as ZooKeeper-style coordinator)
        # Use relative paths so they are namespaced (e.g. /robot_1/coord/...)
        self.create_service(CreateTask, 'coord/create_task', self.handle_create_task)
        self.create_service(ClaimTask, 'coord/claim_task', self.handle_claim_task)
        self.create_service(CompleteTask, 'coord/complete_task', self.handle_complete_task)
        self.create_service(GetAvailableTasks, 'coord/get_available_tasks', self.handle_get_available_tasks)
        
        # Publish Task Events for Metrics Dashboard
        self.task_event_pub = self.create_publisher(TaskEvent, 'task_events', 10)

        # Per-robot coordination-overhead log: round-trip time of each request
        # through the LF socket + RTI (this is the measured T_claim etc.).
        # One file per bridge process avoids cross-process write contention.
        self._overhead = None
        try:
            logs_dir = os.environ.get("TESTBED_LOGS_DIR", "/ros2_ws/logs")
            os.makedirs(logs_dir, exist_ok=True)
            self._overhead_file = open(
                os.path.join(logs_dir, f"claim_robot{self.device_id}.csv"), "a", newline="")
            self._overhead = csv.writer(self._overhead_file)
        except Exception as e:
            self.get_logger().warn(f"overhead log disabled: {e}")

        self.get_logger().info(f"LF Bridge started (device_id={self.device_id}, lf_port={self.lf_port})")

    def _record_overhead(self, kind: str, ms: float):
        """Append one coordination round-trip latency sample (ms)."""
        if self._overhead is None:
            return
        try:
            self._overhead.writerow([kind, round(ms, 3), int(time.time() * 1000)])
            self._overhead_file.flush()
        except Exception:
            pass
    
    def connect_to_lf(self):
        """Connect to local LF federate via TCP socket"""
        # Generous retry budget: with large federations the federate's socket
        # can take a while to open (it binds only once the federation assembles).
        max_retries = 60
        for attempt in range(max_retries):
            try:
                self.lf_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # Host of this robot's federate: same container on host-net
                # (localhost), or the federate's service name on a bridge net
                # (e.g. federate__f1), set via LF_FED_HOST.
                fed_host = os.environ.get('LF_FED_HOST', 'localhost')
                self.lf_socket.connect((fed_host, self.lf_port))
                self.get_logger().info(f"Connected to LF federate at {fed_host}:{self.lf_port}")
                return
            except ConnectionRefusedError:
                if attempt < max_retries - 1:
                    self.get_logger().warn(f"LF federate not ready, retrying... ({attempt+1}/{max_retries})")
                    time.sleep(1)
                else:
                    self.get_logger().error(f"Cannot connect to LF federate socket on port {self.lf_port}")
                    self.get_logger().error(f"The LF federate process failed to start or crashed during initialization.")
                    self.get_logger().error(f"Check the LF federate logs above for the actual error.")
                    self.get_logger().error(f"Container will restart automatically...")
                    import sys
                    sys.exit(1)
    
    def send_to_lf(self, message: dict) -> dict:
        """Send message to LF federate and wait for response (round-trip timed)."""
        t0 = time.perf_counter()
        try:
            # Send request
            msg_str = json.dumps(message) + '\n'
            self.lf_socket.sendall(msg_str.encode('utf-8'))

            # Receive response
            response_str = self.lf_socket.recv(4096).decode('utf-8')
            return json.loads(response_str)
        except Exception as e:
            self.get_logger().error(f"LF communication error: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            self._record_overhead(message.get('type', '?'), (time.perf_counter() - t0) * 1000.0)

    def publish_event(self, task_id, agent_id, event_type):
        """Publish task lifecycle event"""
        msg = TaskEvent()
        msg.task_id = int(task_id)
        msg.agent_id = int(agent_id)
        msg.event_type = event_type
        msg.timestamp_ms = self.get_clock().now().nanoseconds // 1000000
        self.task_event_pub.publish(msg)

    def handle_create_task(self, request, response):
        """Forward create task request to LF"""
        lf_request = {
            'type': 'create',
            'location': request.location,
            'task_type': request.task_type,
            'priority': request.priority
        }
        
        lf_response = self.send_to_lf(lf_request)
        
        response.success = lf_response.get('success', False)
        response.task_id = lf_response.get('task_id', 0)
        
        if response.success:
            self.publish_event(response.task_id, 0, "CREATED")
        
        return response
    
    def handle_claim_task(self, request, response):
        """Forward claim request to LF"""
        lf_request = {
            'type': 'claim',
            'task_id': request.task_id,
            'agent_id': request.agent_id,
            'ttl_ms': request.ttl_ms if request.ttl_ms > 0 else 300000
        }
        
        lf_response = self.send_to_lf(lf_request)
        
        response.success = lf_response.get('success', False)
        response.message = f"Task {request.task_id} claim: {lf_response.get('success', False)}"
        
        if response.success:
            self.get_logger().info(f"Agent {request.agent_id} claimed task {request.task_id} (LF deterministic)")
            self.publish_event(request.task_id, request.agent_id, "CLAIMED")
        
        return response
    
    def handle_complete_task(self, request, response):
        """Forward completion to LF"""
        lf_request = {
            'type': 'complete',
            'task_id': request.task_id,
            'agent_id': request.agent_id
        }
        
        lf_response = self.send_to_lf(lf_request)
        
        response.success = lf_response.get('success', False)
        response.message = f"Task {request.task_id} completed"
        
        if response.success:
            self.get_logger().info(f"Agent {request.agent_id} completed task {request.task_id}")
            self.publish_event(request.task_id, request.agent_id, "COMPLETED")
        else:
            self.get_logger().warn(f"Agent {request.agent_id} failed to complete task {request.task_id}")
            self.publish_event(request.task_id, request.agent_id, "FAILED")
        
        return response
    
    def handle_get_available_tasks(self, request, response):
        """Forward query to LF"""
        lf_request = {
            'type': 'get_tasks',
            'agent_id': request.agent_id
        }
        
        lf_response = self.send_to_lf(lf_request)
        
        response.success = lf_response.get('success', False)
        response.available_tasks = []
        
        for task_dict in lf_response.get('tasks', []):
            task_info = TaskInfo()
            task_info.task_id = task_dict['task_id']
            task_info.location = task_dict['location']
            task_info.task_type = task_dict['task_type']
            task_info.priority = task_dict['priority']
            task_info.status = task_dict['status']
            response.available_tasks.append(task_info)
        
        return response
    
    def destroy_node(self):
        """Cleanup socket connection"""
        if self.lf_socket:
            self.lf_socket.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = LFBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

