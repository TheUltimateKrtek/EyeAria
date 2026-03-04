import abc
import json
import uuid
from typing import List, Dict, Type, Optional
from nicegui import ui, app

from Schema import PipelinePayload

class NodeRegistry:
    _nodes: Dict[str, Type['Node']] = {}

    @classmethod
    def register(cls, name: str):
        def decorator(subclass):
            cls._nodes[name] = subclass
            subclass._node_type_name = name
            return subclass
        return decorator

    @classmethod
    def get_all(cls):
        return cls._nodes

    @classmethod
    def get(cls, name):
        return cls._nodes.get(name)

class Node(abc.ABC):
    _node_type_name: str = "BaseNode"
    has_input: bool = True
    has_output: bool = True
    node_color: str = "slate-800" # Default color

    _spawn_offset = 0 

    def __init__(self):
        self.id = str(uuid.uuid4())
        
        Node._spawn_offset = (Node._spawn_offset + 30) % 300
        self.x = 50 + Node._spawn_offset
        self.y = 50 + Node._spawn_offset
        self.width = 280  
        self.height = 100 

        self.subscribers: List['Node'] = []
        self.parent: Optional['Node'] = None
        self.running = False
        self.collapsed = False
        
        self.card = None
        self.mini_card = None

    def start(self):
        self.running = True
        self._start()
        for sub in self.subscribers: sub.start()

    def stop(self):
        self.running = False
        self._stop()
        for sub in self.subscribers: sub.stop()

    def input(self, payload: PipelinePayload):
        if not self.running: return
        
        # Pass the object directly
        result_payload = self._input(payload)
        
        # If the node returns a modified payload, notify subscribers
        if self.has_output and result_payload is not None:
            self.notify(result_payload)

    def notify(self, payload: PipelinePayload):
        for sub in self.subscribers: 
            # Use your custom copy method to branch the data safely!
            sub.input(payload.copy())
            
    def add_subscriber(self, node: 'Node'):
        node.parent = self
        self.subscribers.append(node)

    def remove_subscriber(self, node: 'Node'):
        if node in self.subscribers:
            self.subscribers.remove(node)
            node.parent = None

    def build_node_ui(self, is_mini: bool = False):
        """Builds either a full draggable node or a tiny minimap dot."""
        if is_mini:
            # Store the reference to the minimap dot
            self.mini_card = ui.element('div').classes(f'absolute bg-{self.node_color} rounded-sm') \
                .style(f'left: {self.x}px; top: {self.y}px; width: {self.width}px; height: {self.height}px;')
            return

        # The main card remains absolutely positioned
        self.card = ui.card().classes('absolute w-72 shadow-lg p-0 border border-slate-300 bg-white select-none touch-none') \
            .style(f'left: {self.x}px; top: {self.y}px; z-index: 10;')
        
        self.card.on('mousedown.stop', lambda: None)
        self.card.on('touchstart.stop', lambda: None)

        with self.card:
            ui.element('q-resize-observer').on('resize', self._handle_resize)

            # The Header (Drag Handle)
            handle = ui.row().classes(f'w-full bg-{self.node_color} text-white p-1 cursor-move items-center justify-between no-wrap')
            handle.style('touch-action: none; user-select: none;')

            with handle:
                icon = 'expand_more' if self.collapsed else 'expand_less'
                ui.button(icon=icon, on_click=self.toggle_collapse).props('flat round dense text-white size=sm')
                ui.label(self._node_type_name).classes('font-bold text-[11px] grow cursor-move')
                
                if self.has_output:
                    ui.button(icon='add', on_click=lambda: app.logic.add_node_dialog(self)).props('flat round dense text-green-400 size=sm')
                
                with ui.button(icon='more_vert').props('flat round dense text-gray-400 size=sm'):
                    with ui.menu().classes('text-sm'):
                        ui.menu_item('Delete', on_click=lambda: app.logic.delete_node(self))

            if not self.collapsed:
                with ui.column().classes('p-2 w-full'):
                    self.create_content()

        # --- REFINED DRAG LOGIC ---
        self.dragging = False
        self.offset_x = 0
        self.offset_y = 0
    
        def get_coords(e):
            if 'touches' in e.args and len(e.args['touches']) > 0:
                return e.args['touches'][0]['clientX'], e.args['touches'][0]['clientY']
            return e.args.get('clientX', 0), e.args.get('clientY', 0)

        def start_drag(e):
            if hasattr(app, 'logic'):
                app.logic.active_node = self # Tell the canvas WE are moving
                # Calculate initial grab offset in Canvas Space
                zoom, px, py = app.logic.zoom, app.logic.pan_x, app.logic.pan_y
                mx, my = (e.args['touches'][0]['clientX'] if 'touches' in e.args else e.args['clientX']), \
                         (e.args['touches'][0]['clientY'] if 'touches' in e.args else e.args['clientY'])
                self.offset_x = (mx - px) / zoom - self.x
                self.offset_y = (my - py) / zoom - self.y
                self.card.style('z-index: 100;')

        def stop_drag(e):
            self.dragging = False # Reset for this instance
            self.card.style('z-index: 10;')

        def move_node(e):
            # THE FIX: This global event fires for ALL nodes, 
            # but only the one with self.dragging == True will execute the move.
            if self.dragging:
                zoom = getattr(app.logic, 'zoom', 1.0)
                pan_x = getattr(app.logic, 'pan_x', 0)
                pan_y = getattr(app.logic, 'pan_y', 0)
                
                cur_x, cur_y = get_coords(e)
                
                self.x = (cur_x - pan_x) / zoom - self.offset_x
                self.y = (cur_y - pan_y) / zoom - self.offset_y
                
                self.card.style(f'left: {self.x}px; top: {self.y}px;')
                if hasattr(app, 'logic'):
                    app.logic.redraw_wires()

        # Wire up the events
        handle.on('mousedown.stop', start_drag)
        handle.on('touchstart.stop', start_drag)
        # Using the canvas level or app level for movement ensures the drag doesn't "break"
        ui.on('mousemove', move_node)
        ui.on('touchmove', move_node) # Add this!
        ui.on('mouseup', stop_drag)
        ui.on('touchend', stop_drag)   # Add this!

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        if hasattr(app, 'logic'):
            app.logic.refresh_ui()

    def _handle_resize(self, e):
        try:
            size = e.args if 'width' in e.args else e.args.get('size', {})
            self.width, self.height = size.get('width', self.width), size.get('height', self.height)
            if hasattr(app, 'logic'): 
                app.logic.redraw_wires()
                # Keep minimap synchronized with collapse/expand size changes
                if self.mini_card:
                    self.mini_card.style(f'width: {self.width}px; height: {self.height}px;')
        except Exception: pass

    @abc.abstractmethod
    def _start(self): pass
    @abc.abstractmethod
    def _stop(self): pass
    @abc.abstractmethod
    def _input(self, payload: PipelinePayload) -> Optional[PipelinePayload]: pass
    @abc.abstractmethod
    def create_content(self): pass

    def save(self) -> dict:
        return {
            "type": self._node_type_name,
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "width": self.width,   # Added persistence for dimensions
            "height": self.height, # Added persistence for dimensions
            "collapsed": self.collapsed,
            "subscribers": [sub.save() for sub in self.subscribers]
        }

    @classmethod
    def load(cls, data: dict) -> 'Node':
        node_type = data.get("type")
        node_class = NodeRegistry.get(node_type)
        if not node_class:
            raise ValueError(f"Node type '{node_type}' not found.")
            
        instance = node_class()
        instance.id = data.get("id", str(uuid.uuid4()))
        instance.x = data.get("x", instance.x)
        instance.y = data.get("y", instance.y)
        # Restore dimensions
        instance.width = data.get("width", instance.width)
        instance.height = data.get("height", instance.height)
        instance.collapsed = data.get("collapsed", False)
        
        instance._load_config(data)
        
        for sub_data in data.get("subscribers", []):
            child = Node.load(sub_data)
            if child: instance.add_subscriber(child)
        return instance
    @abc.abstractmethod
    def _load_config(self, data: dict): pass