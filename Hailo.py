import os
import threading
import queue
import json
import time
from nicegui import ui
from Node import Node, NodeRegistry
from Schema import PipelinePayload

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

    _scan_cache = {'hef': [], 'so': []}
    _is_scanning = False
    _scan_complete = False

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
    
    def trigger_system_scan(self, force=False):
        if self.__class__._is_scanning: return
        if self.__class__._scan_complete and not force: return
            
        self.__class__._is_scanning = True
        
        if force:
            self.__class__._scan_cache = {'hef': [], 'so': []}
            self.__class__._scan_complete = False
        
        # Launch thread without touching the UI
        threading.Thread(target=self._run_scan_worker, daemon=True).start()

    def _run_scan_worker(self):
        exclude_dirs = {'proc', 'sys', 'dev', 'run', 'tmp', 'boot', 'snap', 'var'}
        try:
            for root, dirs, files in os.walk('/'):
                dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]
                
                for f in files:
                    if f.endswith('.hef'): 
                        self.__class__._scan_cache['hef'].append(os.path.join(root, f))
                    elif f.endswith('.so'): 
                        self.__class__._scan_cache['so'].append(os.path.join(root, f))
        except Exception as e:
            print(f"File scan interrupted: {e}")
            
        # Purely update state. The dialog's timer will pick this up automatically.
        self.__class__._is_scanning = False
        self.__class__._scan_complete = True

    def _update_scan_ui(self):
        if hasattr(self, 'scan_spinner'): self.scan_spinner.set_visibility(False)
        if hasattr(self, 'scan_btn'): self.scan_btn.props('disable=false')

    def on_data_received(self, frame, raw_detections):
        # raw_detections are dicts from AppSink, map them to the Schema
        schema_detections = [Detection(**d) for d in raw_detections]
        
        payload = PipelinePayload(
            timestamp=time.time(),
            config={"source": self.source_path, "hef": self.hef_path, "tracking": self.tracking_enabled},
            count=len(schema_detections),
            detections=schema_detections
        )
        # Notify pushes it straight into the graph
        self.notify(payload)
        
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
        # 1. Hardware Config Panel
        with ui.column().classes('bg-slate-50 border border-slate-200 border-l-4 border-l-slate-500 w-full p-2 mb-2 shadow-sm gap-1'):
            
            ui.label("HARDWARE CONFIG").classes('text-[10px] font-bold text-slate-700')
            ui.input(label="Source URL/Path").bind_value(self, 'source_path').classes('w-full text-xs').props('dense')
            
            # HEF Search Row
            with ui.row().classes('w-full items-center gap-1 no-wrap'):
                ui.input(label="HEF File").bind_value(self, 'hef_path').classes('grow text-xs').props('dense')
                ui.button(icon='search', on_click=lambda: self.show_search_dialog('hef_path', 'hef')) \
                    .props('flat round dense color=blue size=sm')

            # SO Search Row
            with ui.row().classes('w-full items-center gap-1 no-wrap'):
                ui.input(label="Post-Proc (.so)").bind_value(self, 'so_path').classes('grow text-xs').props('dense')
                ui.button(icon='search', on_click=lambda: self.show_search_dialog('so_path', 'so')) \
                    .props('flat round dense color=blue size=sm')
            
            # Start the background scan silently on boot
            self.trigger_system_scan()
            
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

    def show_search_dialog(self, target_attr, file_type):
        """Displays a live, searchable dialog for cached files."""
        with ui.dialog() as dialog, ui.card().classes('w-[32rem] h-[32rem] p-4'):
            # Force a strict vertical column for the whole card
            with ui.column().classes('w-full h-full gap-2 no-wrap'):
                with ui.row().classes('w-full items-center justify-between'):
                    with ui.row().classes('items-center gap-2'):
                        ui.label(f"SEARCH {file_type.upper()} FILES").classes('text-[12px] font-bold text-slate-700')
                        # Refresh button moved here
                        ui.button(icon='refresh', on_click=lambda: (self.trigger_system_scan(force=True), update_results())) \
                            .props('flat round dense size=xs color=slate').tooltip('Force Re-scan')
                            
                    status_label = ui.label().classes('text-[10px] text-blue-500 italic font-bold')
                
                search_input = ui.input('Type to filter by filename or path...', 
                                        on_change=lambda e: update_results(e.value)) \
                    .classes('w-full text-xs').props('clearable dense autofocus')
                
                results_container = ui.column().classes('w-full grow overflow-y-auto gap-0 border border-slate-200 p-1 shadow-inner bg-slate-50')
                
                def update_results(query=None):
                    if query is None: query = search_input.value
                    results_container.clear()
                    query = query.lower() if query else ""
                    
                    # Copy the list to prevent thread-mutation errors while looping
                    all_files = list(self.__class__._scan_cache[file_type])
                    filtered = [f for f in all_files if query in f.lower()]
                    display_files = filtered[:100]
                    
                    with results_container:
                        if not display_files:
                            msg = "Scanning drive..." if self.__class__._is_scanning else "No matches found."
                            ui.label(msg).classes('text-[10px] text-slate-500 italic p-2')
                        
                        for f in display_files:
                            filename = os.path.basename(f)
                            dir_path = os.path.dirname(f)
                            
                            with ui.button(on_click=lambda f=f: select_file(f)) \
                                .props('flat align=left size=sm color=slate no-caps') \
                                .classes('w-full py-1 border-b border-slate-200'):
                                # FIX: The internal column forces the text to stack vertically
                                with ui.column().classes('w-full gap-0 items-start'):
                                    ui.label(filename).classes('font-bold text-blue-600 text-[11px] leading-tight')
                                    ui.label(dir_path).classes('text-[9px] text-slate-400 break-all leading-tight')
                                
                        if len(filtered) > 100:
                            ui.label(f"... and {len(filtered) - 100} more unseen files. Keep typing to refine search.") \
                                .classes('text-[10px] text-orange-500 italic p-2 text-center w-full')

                    # Update top right status text
                    if self.__class__._is_scanning:
                        status_label.set_text(f"Scanning... ({len(all_files)} found)")
                    else:
                        status_label.set_text(f"Scan Complete ({len(all_files)} total)")

                def select_file(f):
                    setattr(self, target_attr, f)
                    dialog.close()

                update_results()
                ui.button('CANCEL', on_click=dialog.close).props('flat color=grey size=xs').classes('w-full mt-auto')

                # Automatically refresh the results if the background scan is still running
                def auto_refresh():
                    if self.__class__._is_scanning:
                        update_results()
                    else:
                        update_results() # Final update
                        refresh_timer.deactivate()
                        
                refresh_timer = ui.timer(1.0, auto_refresh)
                
        dialog.open()

    def show_file_picker(self, target_attr, extensions):
        """Displays a dialog to select files with specific extensions from the current directory."""
        # Scan current directory for matching files
        try:
            available_files = [f for f in os.listdir('.') if os.path.isfile(f) and any(f.endswith(ext) for ext in extensions)]
        except Exception as e:
            available_files = []
            print(f"Error reading directory: {e}")

        with ui.dialog() as dialog, ui.card().classes('p-4 w-72'):
            ui.label(f"SELECT {' / '.join(extensions).upper()}").classes('text-[12px] font-bold text-slate-700 mb-2')
            
            with ui.column().classes('w-full gap-2 max-h-48 overflow-y-auto'):
                if not available_files:
                    ui.label("No matching files found.").classes('text-[10px] text-red-400 italic text-center w-full')
                else:
                    for f in available_files:
                        # Use default argument n=f to capture the loop variable properly
                        ui.button(f, on_click=lambda n=f: (setattr(self, target_attr, n), dialog.close())) \
                            .props('outline color=blue size=sm').classes('w-full text-[10px] truncate')
            
            ui.button('CANCEL', on_click=dialog.close).props('flat color=grey size=xs').classes('w-full mt-2')
            
        dialog.open()

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
