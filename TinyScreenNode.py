import cv2
import requests
import threading
import time
import base64
import io
from PIL import Image, ImageDraw
from nicegui import ui
from Node import Node, NodeRegistry
from Schema import PipelinePayload

@NodeRegistry.register("Tiny OLED Screen")
class OLEDNode(Node):
    node_color = "slate-700"
    has_input = True
    has_output = True 

    def __init__(self):
        super().__init__()
        self.width = 300
        self.height = 230 # Slightly taller to fit the new checkbox
        
        self.target_ip = "127.0.0.1"
        self.target_port = 8080
        self.app_id = "eye_aria_feed"
        self.fps_limit = 10 
        self.mirror_x = False # <--- NEW: Mirror toggle state
        self.last_sent = 0

    def _start(self):
        self.last_sent = 0

    def _stop(self):
        pass

    def _send_frame(self, b64_str):
        """Runs in a background thread to prevent pipeline blocking."""
        try:
            url = f"http://{self.target_ip}:{self.target_port}/tinyscreen/update"
            payload = {
                "app_id": self.app_id,
                "image_b64": b64_str,
                "timeout": 2.0,  
                "force_top": True
            }
            requests.post(url, json=payload, timeout=1.0)
        except Exception:
            pass 

    def _input(self, payload: PipelinePayload):
        current_time = time.time()
        if current_time - self.last_sent < (1.0 / self.fps_limit):
            return payload

        # 1. Create a blank 1-bit image
        img = Image.new('1', (128, 64), color=0)
        draw = ImageDraw.Draw(img)
        
        # 2. Extract Detections
        found_detections = False
        for mod_name, mod in payload.modules.items():
            detections = None
            if isinstance(mod.data, dict):
                detections = mod.data.get('detections', [])
            elif hasattr(mod.data, 'detections'):
                detections = getattr(mod.data, 'detections')
            
            if detections:
                for det in detections:
                    bbox = det.get('bbox') if isinstance(det, dict) else getattr(det, 'bbox', None)
                    if bbox and len(bbox) == 4:
                        found_detections = True
                        
                        x1, y1, x2, y2 = bbox
                        
                        px1, py1 = int(x1 * 128), int(y1 * 64)
                        px2, py2 = int(x2 * 128), int(y2 * 64)
                        
                        # --- NEW: Horizontal Mirror Logic ---
                        if self.mirror_x:
                            # Swap and invert the X coordinates
                            px1, px2 = 128 - px2, 128 - px1
                            
                        draw.rectangle([px1, py1, px2, py2], outline=1)

        if found_detections:
            # 3. Encode directly to base64
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            b64_str = base64.b64encode(buf.getvalue()).decode('utf-8')
            
            self.last_sent = current_time
            threading.Thread(target=self._send_frame, args=(b64_str,), daemon=True).start()

        return payload

    def create_content(self):
        with ui.column().classes('w-full h-full gap-2 p-2 bg-slate-50 border border-slate-200 border-l-4 border-l-slate-700 shadow-sm'):
            ui.label("I2C OLED BBOX STREAM").classes('text-[10px] font-bold text-slate-800')
            
            ui.input("RemoteUtils IP", value=self.target_ip).bind_value(self, 'target_ip').classes('w-full text-xs').props('dense')
            
            with ui.row().classes('w-full gap-2 no-wrap'):
                ui.number("Port", value=self.target_port).bind_value(self, 'target_port').classes('w-1/2 text-xs').props('dense')
                ui.number("Max FPS", value=self.fps_limit).bind_value(self, 'fps_limit').classes('w-1/2 text-xs').props('dense')
                
            # --- NEW: Checkbox in the UI ---
            ui.checkbox("Mirror Display (Selfie Mode)").bind_value(self, 'mirror_x').classes('text-[10px] font-bold text-slate-700').props('dense size=sm')

    def save(self) -> dict:
        base = super().save()
        base.update({
            "target_ip": self.target_ip,
            "target_port": self.target_port,
            "fps_limit": self.fps_limit,
            "mirror_x": self.mirror_x # Save state
        })
        return base

    def _load_config(self, data: dict):
        self.target_ip = data.get("target_ip", "127.0.0.1")
        self.target_port = data.get("target_port", 8080)
        self.fps_limit = data.get("fps_limit", 10)
        self.mirror_x = data.get("mirror_x", False) # Load state