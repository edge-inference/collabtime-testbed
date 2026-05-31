import rclpy
from rclpy.node import Node
from interfaces.msg import DSMUpdate, AgentState
import time
import os
import csv

class DSMNode(Node):
    """
    Manages Distributed Shared Memory (DSM) for this device.
    Tracks flow traces, computes jam signals, handles gossip.
    """
    def __init__(self):
        super().__init__('dsm_node')
        
        # Parameters
        self.declare_parameter('device_id', 1)
        self.device_id = self.get_parameter('device_id').value
        
        # Local Cache (CRDTs)
        # flow_traces: {node_id: {agent_id: {'timestamp': ms, 'count': int}}}
        self.flow_traces = {}
        
        # jam_signals: {node_id: jam_value (0.0-1.0)}
        self.jam_signals = {}

        # path_intents: {agent_id: {'path': [node_ids], 'timestamp': ms}}
        self.path_intents = {}
        
        # agent_locations: {agent_id: {'node': node_id, 'timestamp': ms}}
        self.agent_locations = {}
        
        # Decay parameters
        self.flow_decay_ms = 5000  # Flow trace decays over 5 seconds
        self.jam_threshold = 3     # 3+ agents passing = jam
        
        # Subscribers
        self.create_subscription(AgentState, 'agent_state', self.handle_agent_state, 10)
        self.create_subscription(DSMUpdate, 'dsm_gossip', self.handle_gossip, 10)
        
        # Publishers
        self.gossip_pub = self.create_publisher(DSMUpdate, 'dsm_gossip', 10)
        
        # Timers
        self.create_timer(0.3, self.send_gossip)       # Gossip every 300ms
        self.create_timer(1.0, self.compute_jam_signals)  # Update jams every 1s

        # Per-robot Age-of-Information log: staleness of accepted peer gossip.
        self._aoi = None
        try:
            logs_dir = os.environ.get("TESTBED_LOGS_DIR", "/ros2_ws/logs")
            os.makedirs(logs_dir, exist_ok=True)
            self._aoi_file = open(
                os.path.join(logs_dir, f"aoi_robot{self.device_id}.csv"), "a", newline="")
            self._aoi = csv.writer(self._aoi_file)
        except Exception:
            self._aoi = None

        self.get_logger().info(f"DSM Node started (device_id={self.device_id})")

    def handle_agent_state(self, msg):
        """
        Update flow traces when agent moves.
        Called every time an agent publishes its state.
        """
        agent_id = msg.agent_id
        node_id = msg.current_node
        timestamp_ms = msg.timestamp_ms
        
        # Initialize node in flow_traces if needed
        if node_id not in self.flow_traces:
            self.flow_traces[node_id] = {}
        
        # Update local agent location
        self.agent_locations[agent_id] = {
            'node': node_id,
            'timestamp': timestamp_ms
        }
        
        # Update or create entry for this agent
        if agent_id in self.flow_traces[node_id]:
            # Agent passed through this node again
            self.flow_traces[node_id][agent_id]['count'] += 1
            self.flow_traces[node_id][agent_id]['timestamp'] = timestamp_ms
        else:
            # First time this agent visited this node (in recent history)
            self.flow_traces[node_id][agent_id] = {
                'timestamp': timestamp_ms,
                'count': 1
            }

    def handle_gossip(self, msg):
        """Merge incoming gossip data (CRDT merge)."""
        if msg.source_agent_id == self.device_id:
            return  # Ignore self

        # Record Age-of-Information: staleness of received gossip relative to the
        # 300 ms gossip period (bounded-staleness / AoI evidence for the data plane).
        if self._aoi is not None and msg.timestamps:
            now_ms = int(time.time() * 1000)
            age = now_ms - max(msg.timestamps)
            if age >= 0:
                try:
                    self._aoi.writerow([msg.layer_name, age, now_ms])
                    self._aoi_file.flush()
                except Exception:
                    pass
        
        # Merge flow traces (Last-Write-Wins based on timestamp)
        if msg.layer_name == "flow_trace":
            for i, node_id in enumerate(msg.node_ids):
                agent_id = msg.source_agent_id  # Assuming single-agent update
                timestamp = msg.timestamps[i] if i < len(msg.timestamps) else 0
                count = int(msg.values[i]) if i < len(msg.values) else 0
                
                if node_id not in self.flow_traces:
                    self.flow_traces[node_id] = {}
                
                # LWW merge
                if agent_id not in self.flow_traces[node_id]:
                    self.flow_traces[node_id][agent_id] = {
                        'timestamp': timestamp,
                        'count': count
                    }
                else:
                    existing_ts = self.flow_traces[node_id][agent_id]['timestamp']
                    if timestamp > existing_ts:
                        self.flow_traces[node_id][agent_id] = {
                            'timestamp': timestamp,
                            'count': count
                        }
        
        elif msg.layer_name == "path_intent":
            # Path intent is: AgentID -> List[NodeID]
            agent_id = msg.source_agent_id
            timestamp = msg.timestamps[0] if msg.timestamps else 0
            path = list(msg.node_ids)
            
            # LWW merge
            if agent_id not in self.path_intents:
                self.path_intents[agent_id] = {
                    'path': path,
                    'timestamp': timestamp
                }
            else:
                existing_ts = self.path_intents[agent_id]['timestamp']
                if timestamp > existing_ts:
                    self.path_intents[agent_id] = {
                        'path': path,
                        'timestamp': timestamp
                    }
        
        elif msg.layer_name == "agent_location":
            # Agent location is: AgentID -> NodeID
            agent_id = msg.source_agent_id
            timestamp = msg.timestamps[0] if msg.timestamps else 0
            node_id = msg.node_ids[0] if msg.node_ids else 0
            
            # LWW merge
            if agent_id not in self.agent_locations:
                self.agent_locations[agent_id] = {
                    'node': node_id,
                    'timestamp': timestamp
                }
            else:
                existing_ts = self.agent_locations[agent_id]['timestamp']
                if timestamp > existing_ts:
                    self.agent_locations[agent_id] = {
                        'node': node_id,
                        'timestamp': timestamp
                    }

        self.get_logger().debug(f"Merged gossip from device {msg.source_agent_id}")

    def compute_jam_signals(self):
        """
        Compute jam signals from flow traces.
        Jam = high recent traffic through a node.
        """
        current_time_ms = int(time.time() * 1000)
        
        for node_id, agents in self.flow_traces.items():
            # Count recent agents (within decay window)
            recent_count = 0
            
            for agent_id, data in list(agents.items()):
                age_ms = current_time_ms - data['timestamp']
                
                if age_ms > self.flow_decay_ms:
                    # Expired, remove
                    del agents[agent_id]
                else:
                    recent_count += 1
            
            # Compute jam signal (0.0 = free, 1.0 = max congestion)
            jam_value = min(1.0, recent_count / self.jam_threshold)
            self.jam_signals[node_id] = jam_value

    def send_gossip(self):
        """Broadcast local flow trace updates."""
        current_time_ms = int(time.time() * 1000)
        
        # 1. Gossip Flow Traces
        msg = DSMUpdate()
        msg.source_agent_id = self.device_id
        msg.layer_name = "flow_trace"
        msg.gossip_round = 0
        
        node_ids = []
        values = []
        timestamps = []
        
        for node_id, agents in self.flow_traces.items():
            for agent_id, data in agents.items():
                age_ms = current_time_ms - data['timestamp']
                if age_ms < 1000:
                    node_ids.append(node_id)
                    values.append(float(data['count']))
                    timestamps.append(data['timestamp'])
        
        if node_ids:
            msg.node_ids = node_ids
            msg.values = values
            msg.timestamps = timestamps
            self.gossip_pub.publish(msg)

        # 2. Gossip Path Intents
        if self.device_id in self.path_intents:
            my_intent = self.path_intents[self.device_id]
            # Only gossip if recent (e.g. within last 2 seconds)
            if current_time_ms - my_intent['timestamp'] < 2000:
                intent_msg = DSMUpdate()
                intent_msg.source_agent_id = self.device_id
                intent_msg.layer_name = "path_intent"
                intent_msg.node_ids = [int(n) for n in my_intent['path']]
                intent_msg.timestamps = [my_intent['timestamp']]
                # values unused
                self.gossip_pub.publish(intent_msg)

        # 3. Gossip Agent Location
        if self.device_id in self.agent_locations:
            my_loc = self.agent_locations[self.device_id]
            # Only gossip if recent (e.g. within last 5 seconds)
            if current_time_ms - my_loc['timestamp'] < 5000:
                loc_msg = DSMUpdate()
                loc_msg.source_agent_id = self.device_id
                loc_msg.layer_name = "agent_location"
                loc_msg.node_ids = [my_loc['node']]
                loc_msg.timestamps = [my_loc['timestamp']]
                # values unused
                self.gossip_pub.publish(loc_msg)
    
    def get_jam_signal(self, node_id):
        """Get current jam signal for a node (for agents to query)."""
        return self.jam_signals.get(node_id, 0.0)
    
    def get_flow_count(self, node_id):
        """Get number of recent agents at a node."""
        if node_id not in self.flow_traces:
            return 0
        return len(self.flow_traces[node_id])

def main(args=None):
    rclpy.init(args=args)
    node = DSMNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
