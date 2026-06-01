import rclpy
from rclpy.node import Node
from interfaces.msg import AgentState, TaskAssignment, DSMUpdate
from interfaces.srv import ClaimTask, GetAvailableTasks, CompleteTask
from common.graph import WarehouseGraph
import os

class AgentNode(Node):
    def __init__(self):
        super().__init__('agent_node')
        
        # Parameters
        self.declare_parameter('agent_id', 1)
        self.declare_parameter('device_id', 1)
        self.declare_parameter('start_node', 0)
        self.declare_parameter('tick_rate_ms', 100)
        self.declare_parameter('step_time_s', 2.0)  # ~16s for 8-step path (simulation)
        self.declare_parameter('work_time_s', 30.0)  # 30s work at destination (simulation)
        self.declare_parameter('graph_config', '/ros2_ws/config/warehouse_graph.yaml')
        
        self.agent_id = self.get_parameter('agent_id').value
        self.device_id = self.get_parameter('device_id').value
        self.current_node = self.get_parameter('start_node').value
        self.tick_rate_ms = self.get_parameter('tick_rate_ms').value
        self.step_time_s = self.get_parameter('step_time_s').value
        self.work_time_s = self.get_parameter('work_time_s').value
        
        # Load warehouse graph
        graph_path = self.get_parameter('graph_config').value
        try:
            self.graph = WarehouseGraph.from_yaml(graph_path)
            self.get_logger().info(f"Loaded graph: {self.graph.num_nodes()} nodes, {self.graph.num_edges()} edges")
        except Exception as e:
            self.get_logger().error(f"Failed to load graph: {e}")
            self.graph = None
        
        # State machine
        self.state = "IDLE"  # IDLE, CLAIMING, NAVIGATING, WORKING, COMPLETING
        self.path = []
        self.current_task = None
        self.task_target_node = None
        self.move_timer = 0.0  # Countdown for next movement
        self.work_timer = 0.0  # Countdown for work completion
        self.lease_ttl_ms = 300000  # 5 minute lease (covers navigation + work)
        self.lease_renewal_timer = 0.0  # Renew lease every 30 seconds
        self.resource_wait_timer = 0  # Wait counter when node is occupied
        self.resource_wait_max = 50  # Max ticks to wait (~5 seconds at 100ms)
        self.clearing_from_work_node = False  # Flag for post-work clearing
        
        # Gossip (DSM path-intent sharing) is the distributed data plane; the
        # centralized baseline (thesis Ch.3) runs with NO inter-robot gossip.
        self.declare_parameter('use_gossip', True)
        self.use_gossip = self.get_parameter('use_gossip').value

        # Publishers
        self.state_pub = self.create_publisher(AgentState, 'agent_state', 10)
        self.dsm_pub = self.create_publisher(DSMUpdate, 'dsm_gossip', 10) if self.use_gossip else None

        # Subscribers
        if self.use_gossip:
            self.dsm_sub = self.create_subscription(DSMUpdate, 'dsm_gossip', self.handle_dsm_update, 10)
        self.other_agent_intents = {}  # stays empty when gossip off -> independent path planning
        
        # Service clients (LF Coordinator) - use relative paths for namespacing
        self.claim_client = self.create_client(ClaimTask, 'coord/claim_task')
        self.get_tasks_client = self.create_client(GetAvailableTasks, 'coord/get_available_tasks')
        self.complete_client = self.create_client(CompleteTask, 'coord/complete_task')
        
        # Timer (Heartbeat / Movement / State Machine)
        period_s = self.tick_rate_ms / 1000.0
        self.timer = self.create_timer(period_s, self.tick)
        
        # Counters for task loop
        self.idle_ticks = 0
        self.tasks_completed = 0
        
        self.get_logger().info(f"Agent {self.agent_id} started at node {self.current_node}")

    def tick(self):
        """Main loop: State Machine + Movement."""
        tick_duration_s = self.tick_rate_ms / 1000.0
        
        if self.state == "IDLE":
            # If just finished work, clear the work node first
            if self.clearing_from_work_node:
                self.move_timer -= tick_duration_s
                if self.move_timer <= 0:
                    self.move_one_step()
                    self.move_timer = self.step_time_s
            else:
                self.idle_ticks += 1
                # Every 30 ticks (~3 seconds), try to get a task
                if self.idle_ticks >= 30:
                    self.idle_ticks = 0
                    self.try_get_task()
        
        elif self.state == "NAVIGATING":
            # Decrement move timer
            self.move_timer -= tick_duration_s
            if self.move_timer <= 0:
                self.move_one_step()
                # Reset timer for next step
                self.move_timer = self.step_time_s
            
            # Renew lease periodically
            self.lease_renewal_timer -= tick_duration_s
            if self.lease_renewal_timer <= 0:
                self.renew_task_lease()
                self.lease_renewal_timer = 120.0
        
        elif self.state == "WORKING":
            # Decrement work timer
            self.work_timer -= tick_duration_s
            if self.work_timer <= 0:
                self.state = "COMPLETING"
                self.get_logger().info(f"Task {self.current_task} work finished, releasing...")
                self.try_complete_task()
            
            # Renew lease periodically
            self.lease_renewal_timer -= tick_duration_s
            if self.lease_renewal_timer <= 0:
                self.renew_task_lease()
                self.lease_renewal_timer = 120.0
        
        # Publish state at ~3 Hz (every 3rd tick). Enough for 2 s/step virtual
        # motion, and cuts the DDS chatter that every DSM + metrics node processes.
        self._pub_div = (getattr(self, "_pub_div", 0) + 1) % 3
        if self._pub_div == 0:
            self.publish_state()

    def try_get_task(self):
        """Query available tasks and claim one."""
        if not self.get_tasks_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn("GetAvailableTasks service not available")
            return
        
        # Request available tasks
        req = GetAvailableTasks.Request()
        req.agent_id = self.agent_id
        
        future = self.get_tasks_client.call_async(req)
        future.add_done_callback(self.on_tasks_received)

    def on_tasks_received(self, future):
        """Callback when available tasks are received."""
        try:
            response = future.result()
            if response.success and response.available_tasks:
                # Pick the nearest available task (matches the simulation's
                # distributed pull heuristic). Concurrent agents may target the
                # same task; the LF control plane resolves the claim race.
                task = self._select_nearest_task(response.available_tasks)
                self.get_logger().info(f"Found task {task.task_id} at location {task.location}")
                self.try_claim_task(task.task_id, task.location)
            else:
                self.get_logger().debug("No available tasks")
        except Exception as e:
            self.get_logger().error(f"Failed to get tasks: {e}")

    def _select_nearest_task(self, tasks):
        """Return the task whose location node is closest (Manhattan) to us."""
        if self.graph is None:
            return tasks[0]
        cx, cy = self.graph.get_node_position(self.current_node)
        best, best_dist = None, None
        for task in tasks:
            tx, ty = self.graph.get_node_position(task.location)
            dist = abs(tx - cx) + abs(ty - cy)
            if best_dist is None or dist < best_dist:
                best, best_dist = task, dist
        return best if best is not None else tasks[0]

    def try_claim_task(self, task_id, location):
        """Attempt to claim a task."""
        if self.state != "IDLE":
             return

        if not self.claim_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn("ClaimTask service not available")
            return
        
        # Set state to CLAIMING to prevent duplicate requests
        self.state = "CLAIMING"
        self.get_logger().info(f"Attempting to claim task {task_id}...")

        req = ClaimTask.Request()
        req.task_id = task_id
        req.agent_id = self.agent_id
        req.ttl_ms = self.lease_ttl_ms
        
        future = self.claim_client.call_async(req)
        future.add_done_callback(lambda f: self.on_task_claimed(f, task_id, location))

    def renew_task_lease(self):
        """Renew the lease on the current task to prevent expiration."""
        if self.current_task is None:
            return
            
        if not self.claim_client.wait_for_service(timeout_sec=0.1):
            return
        
        req = ClaimTask.Request()
        req.task_id = self.current_task
        req.agent_id = self.agent_id
        req.ttl_ms = self.lease_ttl_ms
        
        self.claim_client.call_async(req)
        self.get_logger().debug(f"Renewed lease for task {self.current_task}")

    def on_task_claimed(self, future, task_id, location):
        """Callback when task claim response is received."""
        try:
            response = future.result()
            self.get_logger().info(f"Claim response for Task {task_id}: success={response.success}, message='{response.message}'")
            
            if response.success:
                self.get_logger().info(f"Claimed task {task_id}!")
                self.current_task = task_id
                self.task_target_node = location
                self.lease_renewal_timer = 120.0
                self.compute_path_to_target()
            else:
                self.get_logger().warn(f"Failed to claim task {task_id}: {response.message}")
                self.state = "IDLE" # Revert to IDLE to try again
        except Exception as e:
            self.get_logger().error(f"Task claim error: {e}")
            self.state = "IDLE" # Revert on error

    def compute_path_to_target(self):
        """Compute path to task location using A*."""
        if self.graph is None:
            self.get_logger().error("No graph loaded, cannot navigate")
            return
        
        if self.current_node == self.task_target_node:
            self.get_logger().info("Already at target!")
            self.state = "WORKING"
            return
        
        # TODO: Get DSM jam signals for dynamic routing
        # Build conflict set from recent path intents
        conflict_nodes = set()
        current_time = self.get_clock().now().nanoseconds // 1000000
        for agent_id, data in self.other_agent_intents.items():
            # Only consider fresh intents (e.g. < 5s old)
            if current_time - data['timestamp'] < 5000:
                conflict_nodes.update(data['path'])

        path = self.graph.astar_path(
            self.current_node,
            self.task_target_node,
            jam_costs={},  # Empty for now
            flow_costs={},
            conflict_nodes=conflict_nodes,
            conflict_weight=100.0
        )
        
        if path:
            self.path = path[1:]  # Exclude current node
            self.state = "NAVIGATING"
            self.move_timer = self.step_time_s  # Initialize movement timer
            total_time_s = len(self.path) * self.step_time_s
            self.get_logger().info(f"Path computed: {len(self.path)} steps (~{total_time_s:.0f}s navigation)")
            self.publish_path_intent()
        else:
            self.get_logger().error(f"No path from {self.current_node} to {self.task_target_node}")
            self.state = "IDLE"

    def publish_path_intent(self):
        """Publish current future path to DSM (no-op when gossip is disabled)."""
        if not self.use_gossip:
            return
        msg = DSMUpdate()
        msg.source_agent_id = self.agent_id
        msg.layer_name = "path_intent"
        msg.node_ids = [int(n) for n in self.path]
        msg.timestamps = [self.get_clock().now().nanoseconds // 1000000]
        # values unused
        self.dsm_pub.publish(msg)

    def handle_dsm_update(self, msg):
        """Update local view of other agents' plans."""
        if msg.source_agent_id == self.agent_id:
            return
            
        if msg.layer_name == 'path_intent':
            # Store intent
            self.other_agent_intents[msg.source_agent_id] = {
                'path': list(msg.node_ids),
                'timestamp': msg.timestamps[0] if msg.timestamps else 0
            }

    def move_one_step(self):
        """Virtual movement: Advance to next node in path."""
        if not self.path:
            # Reached destination - try to acquire node lock (JIT)
            if self.try_acquire_node_lock():
                self.state = "WORKING"
                self.work_timer = self.work_time_s
                self.resource_wait_timer = 0
                self.get_logger().info(f"Arrived at node {self.current_node}, acquired lock, starting work ({self.work_time_s}s)...")
                self.publish_path_intent()
            else:
                # Node is occupied - wait
                self.resource_wait_timer += 1
                if self.resource_wait_timer >= self.resource_wait_max:
                    self.get_logger().warn(f"Node {self.current_node} lock timeout, failing task {self.current_task}")
                    self.fail_current_task()
                else:
                    self.get_logger().debug(f"Node {self.current_node} occupied, waiting... ({self.resource_wait_timer}/{self.resource_wait_max})")
            return
        
        # Move to next node
        next_node = self.path.pop(0)
        self.current_node = next_node
        
        if self.clearing_from_work_node:
            self.get_logger().debug(f"Clearing: {self.current_node} (remaining: {len(self.path)} steps)")
            if not self.path:
                self.clearing_from_work_node = False
                self.get_logger().info(f"Cleared work area, now at node {self.current_node}")
        else:
            self.get_logger().info(f"Moving: {self.current_node} -> next (remaining: {len(self.path)} steps)")
        
        # Update path intent (shorter path)
        self.publish_path_intent()
        
        # Note: AgentState publisher will update DSM automatically
        # (DSM subscribes to 'agent_state' topic)

    def try_acquire_node_lock(self) -> bool:
        """Try to acquire JIT lock on current node resource."""
        if self.current_node is None:
            return False
        
        try:
            import socket
            import json
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            fed_host = os.environ.get('LF_FED_HOST', 'localhost')
            # LF_FED_PORT lets all robots target ONE shared federate (centralized
            # baseline); unset -> per-robot federate (distributed, unchanged).
            fed_port = int(os.environ.get('LF_FED_PORT', 9000 + self.device_id))
            sock.connect((fed_host, fed_port))

            request = {
                'type': 'acquire_node_lock',
                'node_id': self.current_node,
                'agent_id': self.agent_id,
                'ttl_ms': 30000
            }
            
            sock.sendall((json.dumps(request) + '\n').encode('utf-8'))
            response_str = sock.recv(4096).decode('utf-8')
            sock.close()
            
            response = json.loads(response_str)
            return response.get('success', False)
        except Exception as e:
            self.get_logger().error(f"Failed to acquire node lock: {e}")
            return False
    
    def release_node_lock(self):
        """Release JIT lock on current node resource."""
        if self.current_node is None:
            return
        
        try:
            import socket
            import json
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            fed_host = os.environ.get('LF_FED_HOST', 'localhost')
            fed_port = int(os.environ.get('LF_FED_PORT', 9000 + self.device_id))
            sock.connect((fed_host, fed_port))

            request = {
                'type': 'release_node_lock',
                'node_id': self.current_node,
                'agent_id': self.agent_id
            }
            
            sock.sendall((json.dumps(request) + '\n').encode('utf-8'))
            response_str = sock.recv(4096).decode('utf-8')
            sock.close()
        except Exception as e:
            self.get_logger().error(f"Failed to release node lock: {e}")
    
    def plan_clearing_path(self):
        """Plan a short path to clear the work node (move to staging or nearby node)."""
        if self.graph is None:
            return
        
        # Try to find staging nodes
        staging_nodes = [n for n in self.graph.node_metadata.keys() 
                        if self.graph.node_metadata.get(n, {}).get('type') == 'staging']
        
        target = None
        if staging_nodes:
            # Find nearest staging node
            min_dist = float('inf')
            for staging in staging_nodes:
                if staging != self.current_node:
                    path = self.graph.astar_path(self.current_node, staging, {}, {}, set(), 0)
                    if path and len(path) < min_dist:
                        min_dist = len(path)
                        target = staging
        
        if not target:
            # No staging nodes or all occupied - just move to any neighbor
            neighbors = self.graph.get_neighbors(self.current_node)
            if neighbors:
                target = neighbors[0]
        
        if target and target != self.current_node:
            path = self.graph.astar_path(self.current_node, target, {}, {}, set(), 0)
            if path:
                self.path = path[1:]  # Exclude current node
                # Limit to 3 steps to just clear the area
                self.path = self.path[:3]
                self.clearing_from_work_node = True
                self.move_timer = self.step_time_s
                self.get_logger().info(f"Clearing work node, moving {len(self.path)} steps")
    
    def fail_current_task(self):
        """Fail the current task and release resources."""
        if self.current_task is not None:
            self.get_logger().warn(f"Failing task {self.current_task}")
            self.release_node_lock()
            self.current_task = None
            self.task_target_node = None
        
        self.path = []
        self.resource_wait_timer = 0
        self.clearing_from_work_node = False
        self.state = "IDLE"
    
    def try_complete_task(self):
        """Mark task as complete and release lease."""
        if not self.complete_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn("CompleteTask service not available")
            self.release_node_lock()
            self.state = "IDLE"
            return
        
        req = CompleteTask.Request()
        req.task_id = self.current_task
        req.agent_id = self.agent_id
        
        future = self.complete_client.call_async(req)
        future.add_done_callback(self.on_task_completed)

    def on_task_completed(self, future):
        """Callback when task completion response is received."""
        try:
            response = future.result()
            if response.success:
                self.tasks_completed += 1
                self.get_logger().info(f"Task {self.current_task} completed! (Total: {self.tasks_completed})")
                # Plan path to clear work area
                self.plan_clearing_path()
            else:
                self.get_logger().warn(f"Failed to complete task {self.current_task}")
        except Exception as e:
            self.get_logger().error(f"Task completion error: {e}")
        finally:
            self.release_node_lock()
            self.current_task = None
            self.task_target_node = None
            self.resource_wait_timer = 0
            self.state = "IDLE"

    def publish_state(self):
        """Publish current agent state (position, state)."""
        msg = AgentState()
        msg.agent_id = self.agent_id
        msg.current_node = self.current_node
        msg.state = self.state
        if self.current_task is not None:
            msg.active_task_id = int(self.current_task)
        else:
            msg.active_task_id = 0 # Default/None
        msg.timestamp_ms = self.get_clock().now().nanoseconds // 1000000
        self.state_pub.publish(msg)

def main(args=None):
    rclpy.init(args=args)
    node = AgentNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
