import abc
import json
import uuid
from typing import List, Dict, Type, Optional
from nicegui import ui, app
from Node import Node, NodeRegistry
import importlib
import os
import sys

# ==========================================
# CONCRETE NODE IMPLEMENTATIONS
# ==========================================

def auto_import_nodes():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.append(current_dir)
    excluded = {"Node.py", "Tree.py", "__init__.py"}
    print(f"Scanning {current_dir} for plugin nodes...")
    
    for filename in os.listdir(current_dir):
        if filename.endswith(".py") and filename not in excluded:
            module_name = filename[:-3] 
            try:
                importlib.import_module(module_name)
                print(f"  [+] Loaded module: {module_name}")
            except Exception as e:
                print(f"  [!] Failed to load {module_name}: {e}")

# ==========================================
# UI LAYOUT & APPLICATION LOGIC
# ==========================================

class PipelineApp:
    def __init__(self):
        self.root_node: Optional[Node] = None
        self.container = None
        self.svg_container = None

        self.is_running = False

        # --- CANVAS STATE ---
        self.pan_x = 0
        self.pan_y = 0
        self.zoom = 1.0
        self.is_panning = False
        
        self.active_node = None
        self.view_box = None

    def add_node_dialog(self, parent_node: Optional[Node] = None):
        with ui.dialog() as dialog, ui.card().classes('w-80 p-4'):
            ui.label("Select Node Type").classes('text-lg font-bold mb-4')
            
            for name, cls in NodeRegistry.get_all().items():
                is_source = not cls.has_input
                show = False
                
                # Filter logic: Root must be a source. Children must accept inputs.
                if parent_node is None and is_source:
                    show = True
                elif parent_node is not None and not is_source:
                    show = True
                
                if show:
                    ui.button(name, on_click=lambda n=name: self.create_node(n, parent_node, dialog))\
                        .props('outline').classes('w-full mb-2')
            
            ui.button('Close', on_click=dialog.close).props('flat').classes('w-full mt-2')
        dialog.open()

    def create_node(self, name, parent, dialog):
        node = NodeRegistry.get(name)()
        
        if parent:
            # Spawn slightly to the right of the parent
            node.x = parent.x + getattr(parent, 'width', 280) + 50
            node.y = parent.y
            parent.add_subscriber(node)
        else:
            self.root_node = node
            
        dialog.close()
        self.refresh_ui()

    def delete_node(self, node):
        if node.parent: node.parent.remove_subscriber(node)
        elif node == self.root_node: self.root_node = None
        node.stop()
        self.refresh_ui()

    def toggle_pipeline(self, button):
        """Toggles the pipeline state and updates the button UI."""
        if self.is_running:
            # STOP THE PIPELINE
            if self.root_node:
                self.root_node.stop()
            self.is_running = False
            
            # Update button to show "START" state
            button.set_text('START PIPELINE')
            button.props('icon=play_arrow color=emerald')
        else:
            # START THE PIPELINE
            if self.root_node:
                self.root_node.start()
            self.is_running = True
            
            # Update button to show "STOP" state
            button.set_text('STOP PIPELINE')
            button.props('icon=stop color=red')
            
    # ==========================================
    # THE CANVAS RENDERING ENGINE
    # ==========================================
    def refresh_ui(self):
        if not self.container: return
        self.container.clear()
        
        with self.container:
            # Add a grid background to the outer container
            grid_style = (
                'background-size: 40px 40px; '
                'background-image: radial-gradient(circle, #cbd5e1 1px, transparent 1px);'
            )
            outer = ui.element('div').classes('relative w-full h-[85vh] bg-slate-200 overflow-hidden select-none border-2') \
                .style(grid_style)
            with outer:
                self.viewport = ui.element('div').classes('absolute w-full h-full').style(
                    f'transform-origin: 0 0; transform: translate({self.pan_x}px, {self.pan_y}px) scale({self.zoom});'
                )
                with self.viewport:
                    self.svg_container = ui.html('<svg width="100%" height="100%"></svg>', sanitize=False).classes('absolute top-0 left-0 w-full h-full pointer-events-none z-0')
                    if not self.root_node:
                        ui.button('ADD SOURCE NODE', on_click=lambda: self.add_node_dialog(None)).classes('absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 shadow-lg').props('icon=add color=green')
                    else:
                        self._render_nodes(self.root_node, is_mini=False)
                        ui.timer(0.05, self.redraw_wires, once=True)
                
                if self.root_node: self._render_minimap()

                # Reset View Button
                with ui.button(on_click=self.reset_view).props('flat round size=lg').classes('absolute bottom-4 right-4 bg-white/30 backdrop-blur-md shadow-sm border border-white/20 z-50'):
                    ui.icon('center_focus_strong').classes('text-slate-800/50')
                    ui.tooltip('Reset View')
            
            def get_coords(e):
                if 'touches' in e.args and len(e.args['touches']) > 0:
                    return e.args['touches'][0]['clientX'], e.args['touches'][0]['clientY']
                return e.args.get('clientX', 0), e.args.get('clientY', 0)

            # --- CENTRALIZED EVENT MANAGEMENT ---
            def handle_move(e):
                mx = e.args['touches'][0]['clientX'] if 'touches' in e.args else e.args['clientX']
                my = e.args['touches'][0]['clientY'] if 'touches' in e.args else e.args['clientY']
                
                if self.active_node:
                    # Calculate new coordinates
                    self.active_node.x = (mx - self.pan_x) / self.zoom - self.active_node.offset_x
                    self.active_node.y = (my - self.pan_y) / self.zoom - self.active_node.offset_y
                    # 1. Update main node
                    self.active_node.card.style(f'left: {self.active_node.x}px; top: {self.active_node.y}px;')
                    # 2. THE FIX: Update minimap node in real-time
                    if self.active_node.mini_card:
                        self.active_node.mini_card.style(f'left: {self.active_node.x}px; top: {self.active_node.y}px; width: {self.active_node.width}px; height: {self.active_node.height}px;')
                    self.redraw_wires()
                elif self.is_panning:
                    self.pan_x += (mx - self.last_mouse_x)
                    self.pan_y += (my - self.last_mouse_y)
                    self.last_mouse_x, self.last_mouse_y = mx, my
                    self._update_viewport()

            def handle_bg_mousedown(e):
                self.is_panning = True
                self.last_mouse_x, self.last_mouse_y = get_coords(e)

            def handle_stop():
                self.is_panning = False
                if self.active_node:
                    self.active_node.card.style('z-index: 10;')
                    self.active_node = None
            
            def handle_wheel(e):
                self.zoom = max(0.2, min(3.0, self.zoom + (0.05 if e.args.get('deltaY', 0) < 0 else -0.05)))
                self._update_viewport()
                self._update_view_box()

            outer.on('mousedown', handle_bg_mousedown)
            outer.on('touchstart', handle_bg_mousedown)
            
            ui.on('mousemove', handle_move)
            ui.on('touchmove', handle_move)
            ui.on('mouseup', handle_stop)
            ui.on('touchend', handle_stop)
            outer.on('wheel', handle_wheel, throttle=0.01)

    def _update_viewport(self):
        """Applies the current pan and zoom to the UI."""
        self.viewport.style(f'transform: translate({self.pan_x}px, {self.pan_y}px) scale({self.zoom});')

    def _render_nodes(self, node: Node, is_mini: bool = False):
        """Recursively instantiate the node UI components on the canvas."""
        node.build_node_ui(is_mini=is_mini)
        for sub in node.subscribers:
            self._render_nodes(sub, is_mini=is_mini)

    def redraw_wires(self):
        """Calculates Bezier curves connecting all parent/child nodes."""
        if not self.root_node or not self.svg_container:
            return
            
        svg_content = '<svg width="100%" height="100%">'
        
        def draw_branch(node):
            nonlocal svg_content
            
            parent_w = getattr(node, 'width', 280)
            parent_h = getattr(node, 'height', 100)
            
            # Start at the Middle-Right of the parent
            start_x = node.x + parent_w
            start_y = node.y + (parent_h / 2)

            for child in node.subscribers:
                child_h = getattr(child, 'height', 100)
                # End at the Middle-Left of the child
                end_x = child.x
                end_y = child.y + (child_h / 2)

                # Bezier Control Points (Creates the S-Curve)
                ctrl_1_x = start_x + max(50, (end_x - start_x) / 2)
                ctrl_1_y = start_y
                ctrl_2_x = end_x - max(50, (end_x - start_x) / 2)
                ctrl_2_y = end_y

                path = f'<path d="M {start_x} {start_y} C {ctrl_1_x} {ctrl_1_y}, {ctrl_2_x} {ctrl_2_y}, {end_x} {end_y}" fill="none" stroke="#94a3b8" stroke-width="3" />'
                svg_content += path
                
                draw_branch(child)
                
        draw_branch(self.root_node)
        svg_content += '</svg>'
        self.svg_container.set_content(svg_content)
    
    def reset_view(self):
        """Snaps the canvas back to origin."""
        self.pan_x = 0
        self.pan_y = 0
        self.zoom = 1.0
        self._update_viewport()
        ui.notify("View Reset")

    def _render_minimap(self):
        """Creates a birds-eye view that tracks movements."""
        with ui.card().classes('absolute top-4 right-4 w-40 h-40 p-0 overflow-hidden bg-slate-800/90 border border-slate-600 shadow-xl z-50'):
            # The minimap dot scale (0.1) should match the scale of the world
            # We add a small offset so (0,0) isn't hugged against the top-left corner
            with ui.element('div').classes('relative w-full h-full').style('transform: scale(0.05) translate(100px, 100px); transform-origin: 0 0;'):
                self._render_nodes(self.root_node, is_mini=True)

    # ==========================================
    # PERSISTENCE (Export / Import)
    # ==========================================

    def export_pipeline(self):
        if not self.root_node:
            ui.notify("Nothing to export!", color='warning')
            return
        
        # Wrap the node tree and viewport state together
        full_config = {
            "viewport": {
                "pan_x": self.pan_x,
                "pan_y": self.pan_y,
                "zoom": self.zoom
            },
            "root": self.root_node.save()
        }
        content = json.dumps(full_config, indent=2)
        ui.download(content.encode(), "full_pipeline_config.json")
        ui.notify("Entire pipeline exported.")

    async def apply_pipeline_config(self, event, dialog):
        try:
            binary_data = await event.file.read()
            data = json.loads(binary_data.decode('utf-8'))
            
            # Handle legacy files (no 'root' key) vs new files
            pipeline_data = data.get("root", data)
            viewport_data = data.get("viewport", {})

            if self.root_node: self.root_node.stop()
            self.root_node = Node.load(pipeline_data)
            
            # Restore Viewport
            self.pan_x = viewport_data.get("pan_x", 0)
            self.pan_y = viewport_data.get("pan_y", 0)
            self.zoom = viewport_data.get("zoom", 1.0)

            dialog.close()
            self.refresh_ui()
            ui.notify("Pipeline and Viewport restored!", color='green')
        except Exception as e:
            ui.notify(f"Failed to import pipeline: {e}", color='red')

    def import_pipeline(self):
        with ui.dialog() as dialog, ui.card().classes('p-4'):
            ui.label('Import Full Pipeline').classes('text-lg font-bold')
            ui.upload(on_upload=lambda e: self.apply_pipeline_config(e, dialog), 
                    auto_upload=True, label="Select Pipeline JSON").classes('w-full')
        dialog.open()

@ui.page('/')
def main():
    if not hasattr(app, 'logic'):
        auto_import_nodes()
        app.logic = PipelineApp()

    ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">')
    
    with ui.header().classes('bg-slate-900 shadow-md flex justify-between items-center px-4'):
        ui.label('EyeAria').classes('font-mono text-xl font-bold')
        
        with ui.row().classes('items-center gap-2'):
            ui.button('EXPORT', icon='file_download', on_click=app.logic.export_pipeline)\
                .props('flat color=white size=sm')
            ui.button('IMPORT', icon='file_upload', on_click=app.logic.import_pipeline)\
                .props('flat color=white size=sm')
            
            ui.separator().props('vertical').classes('mx-2 bg-slate-700 h-6')
            
            btn = ui.button('START PIPELINE', icon='play_arrow', on_click=lambda e: app.logic.toggle_pipeline(e.sender)) \
                .props('color=emerald unelevated').classes('font-bold shadow-sm')
    
    # Render the Canvas Container
    with ui.column().classes('p-0 w-full h-full m-0') as container:
        app.logic.container = container
        app.logic.refresh_ui()

ui.run(port=8082, title="EyeAria")