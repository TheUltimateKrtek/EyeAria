import json
import time
import base64
import cv2
import numpy as np
from typing import List, Dict, Optional
from nicegui import ui
from Node import Node, NodeRegistry
from Schema import PipelinePayload, Detection

@NodeRegistry.register("Logger")
class LoggerNode(Node):
    has_input = True
    has_output = False 

    def __init__(self):
        super().__init__()
        # --- Configuration ---
        self.max_path_points = 50 
        self.max_rects_per_obj = 5
        self.show_labels = True
        self.show_background = True
        self.bg_source_path = "" # Supports "0", "1", or "rtsp://..."
        
        # --- State ---
        self.last_json = ""
        self.paths: Dict[int, List[list]] = {}
        self.object_labels: Dict[int, str] = {}
        self.last_seen: Dict[int, float] = {}
        self.bg_image_data: Optional[str] = None
        self.last_update = 0
        self.current_detections = []
        
        # Background capture internals
        self.cap = None
        self._current_bg_path = None

        # Timers
        ui.timer(1.0, self.prune_tracks)
        ui.timer(0.1, self.update_background) # 10 FPS BG Refresh

    def _start(self):
        self.paths.clear()
        self.object_labels.clear()
        self.last_seen.clear()
        self.bg_image_data = None
        self.current_detections = []

    def _stop(self):
        if self.cap:
            self.cap.release()
            self.cap = None
            self._current_bg_path = None

    def update_background(self):
        """Captures a frame from the specified background camera source."""
        if not self.show_background or not self.bg_source_path:
            if self.cap:
                self.cap.release()
                self.cap = None
                self._current_bg_path = None
            return

        # Smart source switching: handles integer IDs or URL strings
        if self.bg_source_path != self._current_bg_path:
            if self.cap: self.cap.release()
            try:
                # Convert to int if it's a digit (local cam), else keep as string (URL)
                src = int(self.bg_source_path) if self.bg_source_path.strip().isdigit() else self.bg_source_path
                self.cap = cv2.VideoCapture(src)
                self._current_bg_path = self.bg_source_path
            except Exception as e:
                print(f"BG Capture Error: {e}")
                self.cap = None

        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                # Resize and compress for UI performance
                frame = cv2.resize(frame, (640, 480))
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                self.bg_image_data = f"data:image/jpeg;base64,{base64.b64encode(buffer).decode()}"

    def prune_tracks(self):
        """
        No longer strictly necessary for immediate removal, 
        but kept as a safety fallback for static objects.
        """
        now = time.time()
        to_delete = [tid for tid, last in self.last_seen.items() if now - last > 5.0]
        for tid in to_delete:
            self.paths.pop(tid, None)
            self.object_labels.pop(tid, None)
            self.last_seen.pop(tid, None)

    def _input(self, payload: PipelinePayload) -> Optional[PipelinePayload]:
        try:
            # Use the schema's built-in serializer for the UI display
            self.last_json = payload.to_json()
            self.current_detections = payload.detections
            
            active_tids = {det.track_id for det in self.current_detections if det.track_id != -1}

            all_known_tids = list(self.paths.keys())
            for tid in all_known_tids:
                if tid not in active_tids:
                    self.paths.pop(tid, None)
                    self.object_labels.pop(tid, None)
                    self.last_seen.pop(tid, None)

            for det in self.current_detections:
                tid = det.track_id
                if tid == -1: continue 

                self.last_seen[tid] = time.time()
                self.object_labels[tid] = det.label
                
                if tid not in self.paths:
                    self.paths[tid] = []
                
                self.paths[tid].append(det.bbox)
                
                limit = int(self.max_path_points)
                if len(self.paths[tid]) > limit:
                    self.paths[tid] = self.paths[tid][-limit:]

        except Exception as e:
            print(f"Logger Error: {e}")

        if time.time() - self.last_update > 0.05: 
            self.refresh_view()
            self.last_update = time.time()
            
        return payload
    
    def get_color(self, tid, label):
        """Generates deterministic HSL colors for IDs or Labels."""
        if tid != -1:
            return f"hsl({(tid * 137) % 360}, 70%, 50%)"
        hue = (sum(ord(c) for c in label) * 47) % 360
        return f"hsl({hue}, 70%, 50%)"

    def refresh_view(self):
        if not hasattr(self, 'path_map'): return

        # Update JSON Code Block
        if hasattr(self, 'json_display'):
            self.json_display.content = f"```json\n{self.last_json}\n```"
        
        svg_inner = ""
        
        # 1. Background Layer
        if self.show_background and self.bg_image_data:
            svg_inner += f'<image href="{self.bg_image_data}" x="0" y="0" width="100" height="100" preserveAspectRatio="none" />'

        tail_len = int(self.max_rects_per_obj)

        # 2. Draw Tracked Paths (The "Tails")
        for tid, history in self.paths.items():
            label = self.object_labels.get(tid, "unknown")
            color = self.get_color(tid, label)
            
            draw_history = history[-tail_len:]
            for i, bbox in enumerate(draw_history):
                # Fade out: oldest rectangles are more transparent
                alpha = 0.2 + 0.8 * (i / max(1, len(draw_history) - 1))
                xmin, ymin, xmax, ymax = bbox
                svg_inner += (f'<rect x="{xmin*100}" y="{ymin*100}" width="{(xmax-xmin)*100}" height="{(ymax-ymin)*100}" '
                             f'fill="none" stroke="{color}" stroke-width="0.5" stroke-opacity="{alpha}" />')

            if self.show_labels and history:
                lx, ly = history[-1][0]*100, history[-1][1]*100
                svg_inner += f'<text x="{lx}" y="{ly-1}" font-size="3.5" fill="{color}" font-weight="bold" style="text-shadow: 1px 1px 2px black;">{label} #{tid}</text>'

        # 3. Draw Untracked Objects (ID -1: Color + Label, No Tail)
        for det in self.current_detections:
            if det.get("track_id", -1) == -1:
                label = det.get("label", "unknown")
                color = self.get_color(-1, label)
                xmin, ymin, xmax, ymax = det["bbox"]
                
                svg_inner += (f'<rect x="{xmin*100}" y="{ymin*100}" width="{(xmax-xmin)*100}" height="{(ymax-ymin)*100}" '
                             f'fill="none" stroke="{color}" stroke-width="0.5" />')
                if self.show_labels:
                    svg_inner += f'<text x="{xmin*100}" y="{ymin*100-1}" font-size="3.5" fill="{color}" font-weight="bold" style="text-shadow: 1px 1px 2px black;">{label}</text>'

        # Push to NiceGUI HTML component
        self.path_map.set_content(f'<svg viewBox="0 0 100 100" class="path-svg" style="background-color: #000;">{svg_inner}</svg>')

    def create_content(self):
        with ui.column().classes('w-full gap-2'):
            # 1. SVG Display (Removed 'rounded')
            with ui.column().classes('w-full p-0 bg-black overflow-hidden border-2 border-slate-800 relative'):
                self.path_map = ui.html('', sanitize=False).classes('w-full aspect-square')
                ui.add_head_html('<style>.path-svg { width: 100%; height: 100%; }</style>')

            # 2. Settings Panel (Removed 'rounded')
            with ui.column().classes('bg-slate-50 border border-slate-200 border-l-4 border-l-slate-500 w-full p-2 shadow-sm gap-1'):
                ui.label("DISPLAY SETTINGS").classes('text-[10px] font-bold text-slate-700')
                
                with ui.row().classes('w-full items-center gap-2'):
                    ui.checkbox("Labels").bind_value(self, 'show_labels').classes('text-[10px] font-bold text-slate-700').props('dense size=sm')
                    ui.checkbox("BG Cam").bind_value(self, 'show_background').classes('text-[10px] font-bold text-slate-700').props('dense size=sm')
                
                ui.input(label="Source (0, 1, or URL)").bind_value(self, 'bg_source_path').classes('w-full text-xs mt-1').props('dense')
                
                with ui.row().classes('w-full gap-2 mt-1'):
                    ui.number("Tail", format="%d").bind_value(self, 'max_rects_per_obj').classes('w-16 text-xs').props('dense')
                    ui.number("History", format="%d").bind_value(self, 'max_path_points').classes('w-16 text-xs').props('dense')

            # 3. JSON Monitor (Removed 'rounded')
            with ui.column().classes('w-full p-0 bg-slate-900 overflow-hidden shadow-sm gap-0'):
                with ui.row().classes('w-full bg-slate-800 p-1 px-2 border-b border-slate-700'):
                    ui.label("LIVE PAYLOAD").classes('text-[9px] font-bold text-slate-400')
                with ui.scroll_area().classes('h-48 w-full'):
                    self.json_display = ui.markdown('').classes('text-white p-2 text-[11px]')

    def save(self) -> dict:
        base = super().save()
        base.update({
            "max_path_points": self.max_path_points,
            "max_rects_per_obj": self.max_rects_per_obj,
            "show_labels": self.show_labels,
            "show_background": self.show_background,
            "bg_source_path": self.bg_source_path
        })
        return base

    def _load_config(self, data: dict):
        self.max_path_points = data.get("max_path_points", 50)
        self.max_rects_per_obj = data.get("max_rects_per_obj", 5)
        self.show_labels = data.get("show_labels", True)
        self.show_background = data.get("show_background", True)
        self.bg_source_path = data.get("bg_source_path", "")