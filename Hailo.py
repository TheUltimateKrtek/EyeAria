import threading
import queue
import json
import time
from nicegui import ui
from Node import Node, NodeRegistry

# Import updated components from HailoPipeline
try:
    from HailoPipeline import (
        HailoPipeline, HailoListener, AppSink,
        FileSource, RTSPSource, CameraSource,  # <--- Added here
        HailoTracker, LetterboxAdapter, HailoInference
    )
except ImportError:
    print("Warning: HailoPipeline dependencies not found. Using mocks.")
    class HailoListener: pass
    class HailoPipeline: 
        def __init__(self, *args, **kwargs): pass
        def add_listener(self, listener): pass
        def run(self): pass
        def stop(self): pass
        def get_raw_frame(self): return None

@NodeRegistry.register("Hailo")
class HailoNode(Node, HailoListener): # Inherit from Listener
    node_color = "blue-900"
    has_input = False  
    has_output = True

    def __init__(self):
        super().__init__()
        # Basic Configuration
        self.source_path = "detection0.mp4"
        self.hef_path = "yolov8s_h8l.hef"
        self.so_path = "libyolo_hailortpp_post.so"
        
        # Tracking Configuration (Object Permanence)
        self.tracking_enabled = False
        self.keep_tracked_frames = 30
        self.keep_lost_frames = 10
        
        # Runtime internals
        self.pipeline = None
        self.pipeline_thread = None
        self.data_queue = queue.Queue()
        self.poll_timer = None

    def on_data_received(self, frame, detections):
        """
        Implements HailoListener. 
        Note: 'detections' is now a list of DICTS from AppSink.
        """
        payload = {
            "timestamp": time.time(),
            "config": {
                "source": self.source_path,
                "hef": self.hef_path,
                "tracking": self.tracking_enabled
            },
            "count": len(detections),
            "detections": detections # Already JSON-ready from AppSink
        }
        self.data_queue.put(json.dumps(payload))

    def get_frame(self):
        """Retrieves the raw camera frame directly from the pipeline tap."""
        if self.pipeline:
            return self.pipeline.get_raw_frame()
        return None

    def _start(self):
        # 1. Setup Source based on input type
        if self.source_path.isdigit():
            # Treat as hardware camera index (e.g., "0")
            source = CameraSource(device_index=int(self.source_path))
        else:
            # Treat as RTSP URL or Local File
            is_rtsp = any(self.source_path.startswith(prefix) for prefix in ["rtsp://", "rtmp://", "http://"])
            source = RTSPSource(self.source_path) if is_rtsp else FileSource(self.source_path)

        # 2. Setup Inference Components
        adapter = LetterboxAdapter() 
        inference = HailoInference(self.hef_path, self.so_path)
        
        # 3. Setup Optional Tracker
        tracker = None
        if self.tracking_enabled:
            tracker = HailoTracker(
                keep_tracked_frames=self.keep_tracked_frames,
                keep_lost_frames=self.keep_lost_frames
            )

        # 4. Initialize Modular Sink and Pipeline
        sink = AppSink(include_frame=True)
        self.pipeline = HailoPipeline(source, adapter, inference, sink, tracker)
        self.pipeline.add_listener(self) # The node listens to its own pipeline

        # 5. Launch
        self.pipeline_thread = threading.Thread(target=self.pipeline.run, daemon=True)
        self.pipeline_thread.start()
        self.poll_timer = ui.timer(0.1, self.check_queue)

    def check_queue(self):
        try:
            while not self.data_queue.empty():
                data_json = self.data_queue.get_nowait()
                data = json.loads(data_json)
                
                # Update the UI status label regardless of detection count
                if hasattr(self, 'status_label'):
                    self.status_label.set_text(
                        f"Detections: {data['count']} (Tracked: {self.tracking_enabled})"
                    )
                
                # FIX: Remove "if data['count'] > 0:"
                # We MUST notify subscribers even if count is 0 so they can 
                # refresh their views and purge old tracks.
                self.notify(data_json) 
                
        except queue.Empty:
            pass
        
    def _stop(self):
        if self.poll_timer: self.poll_timer.cancel()
        
        if self.pipeline:
            # Use the new stop method to ensure State.NULL is set
            self.pipeline.stop()
            
            # Wait briefly for the thread to finish cleanly
            if self.pipeline_thread and self.pipeline_thread.is_alive():
                self.pipeline_thread.join(timeout=1.0)
                
            self.pipeline = None

    def create_content(self):
        # 1. Hardware Config Panel (Removed 'rounded')
        with ui.column().classes('bg-slate-50 border border-slate-200 border-l-4 border-l-slate-500 w-full p-2 mb-2 shadow-sm gap-1'):
            ui.label("HARDWARE CONFIG").classes('text-[10px] font-bold text-slate-700')
            ui.input(label="Source URL/Path").bind_value(self, 'source_path').classes('w-full text-xs').props('dense')
            ui.input(label="HEF File").bind_value(self, 'hef_path').classes('w-full text-xs').props('dense')
            ui.input(label="Post-Proc (.so)").bind_value(self, 'so_path').classes('w-full text-xs').props('dense')
            
        # 2. Object Permanence Panel (Removed 'rounded')
        with ui.column().classes('bg-blue-50 border border-slate-200 border-l-4 border-l-blue-500 w-full p-2 mb-2 shadow-sm gap-1'):
            ui.label("OBJECT PERMANENCE").classes('text-[10px] font-bold text-blue-700')
            
            ui.checkbox("Enable Tracker").bind_value(self, 'tracking_enabled').classes('text-[10px] font-bold text-slate-700').props('dense size=sm')
            
            with ui.column().bind_visibility_from(self, 'tracking_enabled').classes('w-full gap-1 mt-1'):
                ui.number(label="Keep Tracked", format="%d").bind_value(self, 'keep_tracked_frames').classes('w-full text-xs').props('dense')
                ui.number(label="Keep Lost", format="%d").bind_value(self, 'keep_lost_frames').classes('w-full text-xs').props('dense')
                ui.label("Higher values keep IDs longer.").classes('text-[9px] text-slate-500 italic leading-tight')
            
        # 3. Status Display
        with ui.row().classes('w-full items-center justify-between px-2'):
            self.status_label = ui.label("Status: Idle").classes("text-[10px] text-slate-500 font-mono")

    def save(self) -> dict:
        base = super().save()
        base.update({
            "source_path": self.source_path,
            "hef_path": self.hef_path,
            "so_path": self.so_path,
            "tracking_enabled": self.tracking_enabled,
            "keep_tracked_frames": self.keep_tracked_frames,
            "keep_lost_frames": self.keep_lost_frames
        })
        return base

    def _load_config(self, data: dict):
        self.source_path = data.get("source_path", "")
        self.hef_path = data.get("hef_path", "")
        self.so_path = data.get("so_path", "")
        self.tracking_enabled = data.get("tracking_enabled", False)
        self.keep_tracked_frames = data.get("keep_tracked_frames", 30)
        self.keep_lost_frames = data.get("keep_lost_frames", 10)

    def _input(self, data_json): return None 
