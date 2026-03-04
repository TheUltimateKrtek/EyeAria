import json
from abc import ABC, abstractmethod
from nicegui import ui
from Node import Node, NodeRegistry

# ==========================================
# MODULAR CONDITION CLASSES
# ==========================================

class FilterCondition(ABC):
    """Base class for all filter strategies."""
    def __init__(self):
        self.type_name = "Base"
        self.ui_container = None

    @abstractmethod
    def check(self, detection: dict) -> bool:
        """Returns True if the detection passes this condition."""
        pass

    @abstractmethod
    def create_ui(self):
        """Renders the NiceGUI settings for this specific condition."""
        pass
    
    @abstractmethod
    def to_dict(self) -> dict:
        """Serializes configuration."""
        pass

    @abstractmethod
    def from_dict(self, data: dict):
        """Loads configuration."""
        pass

class LabelCondition(FilterCondition):
    def __init__(self):
        super().__init__()
        self.type_name = "Label"
        self.target_label = "person"
        self.exact_match = False

    def check(self, detection: dict) -> bool:
        label = detection.get("label", "")
        if self.exact_match:
            return label == self.target_label
        return self.target_label.lower() in label.lower()

    def create_ui(self):
        with ui.row().classes('w-full items-center gap-2'):
            ui.input("Label").bind_value(self, 'target_label').classes('w-32 text-xs')
            ui.checkbox("Exact").bind_value(self, 'exact_match').classes('text-xs')

    def to_dict(self):
        return {"target_label": self.target_label, "exact_match": self.exact_match}

    def from_dict(self, data):
        self.target_label = data.get("target_label", "person")
        self.exact_match = data.get("exact_match", False)

class ConfidenceCondition(FilterCondition):
    def __init__(self):
        super().__init__()
        self.type_name = "Confidence"
        self.min_conf = 0.5
        self.max_conf = 1.0

    def check(self, detection: dict) -> bool:
        conf = detection.get("confidence", 0.0)
        return self.min_conf <= conf <= self.max_conf

    def create_ui(self):
        with ui.column().classes('w-full gap-0'):
            with ui.row().classes('w-full justify-between'):
                ui.label("Min").bind_text_from(self, 'min_conf', lambda v: f"{v:.2f}").classes('text-[10px]')
                ui.label("Max").bind_text_from(self, 'max_conf', lambda v: f"{v:.2f}").classes('text-[10px]')
            
            ui.range(min=0.0, max=1.0, step=0.05, value={'min': 0.5, 'max': 1.0})\
                .bind_value_to(self, 'min_conf', forward=lambda x: x['min'])\
                .bind_value_to(self, 'max_conf', forward=lambda x: x['max'])\
                .bind_value_from(self, 'min_conf', backward=lambda x: {'min': self.min_conf, 'max': self.max_conf})\
                .classes('w-full')

    def to_dict(self):
        return {"min_conf": self.min_conf, "max_conf": self.max_conf}

    def from_dict(self, data):
        self.min_conf = data.get("min_conf", 0.5)
        self.max_conf = data.get("max_conf", 1.0)

class DimensionsCondition(FilterCondition):
    def __init__(self):
        super().__init__()
        self.type_name = "Dimensions"
        # Normalized coords (0.0 - 1.0)
        self.w_range = {'min': 0.0, 'max': 1.0}
        self.h_range = {'min': 0.0, 'max': 1.0}

    def check(self, detection: dict) -> bool:
        bbox = detection.get("bbox", [0,0,0,0]) # [xmin, ymin, xmax, ymax]
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        
        valid_w = self.w_range['min'] <= w <= self.w_range['max']
        valid_h = self.h_range['min'] <= h <= self.h_range['max']
        return valid_w and valid_h

    def create_ui(self):
        with ui.column().classes('w-full gap-0'):
            ui.label("Width Range").classes('text-[10px] text-gray-500')
            ui.range(min=0.0, max=1.0, step=0.05).bind_value(self, 'w_range').classes('w-full -mt-1')
            
            ui.label("Height Range").classes('text-[10px] text-gray-500 mt-1')
            ui.range(min=0.0, max=1.0, step=0.05).bind_value(self, 'h_range').classes('w-full -mt-1')

    def to_dict(self):
        return {"w_range": self.w_range, "h_range": self.h_range}

    def from_dict(self, data):
        self.w_range = data.get("w_range", {'min': 0.0, 'max': 1.0})
        self.h_range = data.get("h_range", {'min': 0.0, 'max': 1.0})

class PositionCondition(FilterCondition):
    def __init__(self):
        super().__init__()
        self.type_name = "Position"
        # Area of Interest (Normalized 0-1)
        self.x = 0.0
        self.y = 0.0
        self.w = 0.5
        self.h = 0.5
        self.require_contained = False # True = Whole object must be inside. False = Intersection.

    def check(self, detection: dict) -> bool:
        # Object Box
        o_xmin, o_ymin, o_xmax, o_ymax = detection.get("bbox", [0,0,0,0])
        
        # Filter Area Box
        f_xmin = self.x
        f_ymin = self.y
        f_xmax = self.x + self.w
        f_ymax = self.y + self.h

        if self.require_contained:
            # Check if Object is FULLY inside Filter Area
            return (o_xmin >= f_xmin and o_xmax <= f_xmax and 
                    o_ymin >= f_ymin and o_ymax <= f_ymax)
        else:
            # Check for INTERSECTION (AABB collision)
            return (o_xmin < f_xmax and o_xmax > f_xmin and
                    o_ymin < f_ymax and o_ymax > f_ymin)

    def create_ui(self):
        with ui.column().classes('w-full gap-1'):
            with ui.row().classes('w-full gap-1'):
                ui.number(label="X", format="%.2f", step=0.1).bind_value(self, 'x').classes('w-1/4 text-xs')
                ui.number(label="Y", format="%.2f", step=0.1).bind_value(self, 'y').classes('w-1/4 text-xs')
                ui.number(label="W", format="%.2f", step=0.1).bind_value(self, 'w').classes('w-1/4 text-xs')
                ui.number(label="H", format="%.2f", step=0.1).bind_value(self, 'h').classes('w-1/4 text-xs')
            
            with ui.row().classes('w-full items-center justify-between'):
                ui.label("Strict (Fully Inside)").classes('text-[10px]')
                ui.switch().bind_value(self, 'require_contained').props('dense')

    def to_dict(self):
        return {
            "x": self.x, "y": self.y, "w": self.w, "h": self.h, 
            "require_contained": self.require_contained
        }

    def from_dict(self, data):
        self.x = data.get("x", 0.0)
        self.y = data.get("y", 0.0)
        self.w = data.get("w", 0.5)
        self.h = data.get("h", 0.5)
        self.require_contained = data.get("require_contained", False)

# Factory for loading
CONDITION_MAP = {
    "Label": LabelCondition,
    "Confidence": ConfidenceCondition,
    "Dimensions": DimensionsCondition,
    "Position": PositionCondition
}

# ==========================================
# FILTER NODE
# ==========================================

@NodeRegistry.register("Filter")
class FilterNode(Node):
    node_color = "emerald-800"
    has_input = True
    has_output = True

    def __init__(self):
        super().__init__()
        self.conditions = []
        self.logic_mode = "AND" 
        self.conditions_container = None

    def _start(self):
        pass

    def _stop(self):
        pass

    def _input(self, data_json: str):
        try:
            data = json.loads(data_json)
            raw_detections = data.get("detections", [])
            
            if not self.conditions:
                return data_json

            filtered_detections = []
            for det in raw_detections:
                results = [cond.check(det) for cond in self.conditions]
                
                is_valid = all(results) if self.logic_mode == "AND" else any(results)
                if is_valid:
                    filtered_detections.append(det)

            data["detections"] = filtered_detections
            data["count"] = len(filtered_detections)
            return json.dumps(data)
            
        except Exception as e:
            print(f"Filter Node Error: {e}")
            return None

    def create_content(self):
        with ui.column().classes('w-full gap-2'):
            
            # 1. Logic Panel (Removed 'rounded')
            with ui.column().classes('bg-emerald-50 border border-slate-200 border-l-4 border-l-emerald-500 w-full p-2 shadow-sm gap-0'):
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label("LOGIC MODE").classes('text-[10px] font-bold text-emerald-700')
                    ui.toggle(["AND", "OR"]).bind_value(self, 'logic_mode') \
                        .props('dense unelevated toggle-color=emerald color=white text-color=slate-700') \
                        .classes('border border-slate-300 shadow-sm')

            # 2. Conditions List
            self.conditions_container = ui.column().classes('w-full gap-2')
            self._render_conditions()

            # 3. Add Button (Removed 'rounded')
            ui.button('ADD CONDITION', icon='add', color='emerald', on_click=self.show_add_dialog)\
                .classes('w-full h-8 text-[10px] font-bold shadow-sm')

    def _render_conditions(self):
        self.conditions_container.clear()
        with self.conditions_container:
            if not self.conditions:
                ui.label("No active filters.").classes('text-[10px] text-slate-400 italic text-center w-full mt-1')
            
            for index, cond in enumerate(self.conditions):
                # Inner Condition Panel (Removed 'rounded')
                with ui.column().classes('bg-white w-full p-2 border border-slate-200 border-l-4 border-l-slate-400 shadow-sm gap-1'):
                    with ui.row().classes('w-full justify-between items-center mb-1'):
                        ui.label(cond.type_name).classes('font-bold text-[10px] uppercase text-slate-600')
                        ui.button(icon='close', on_click=lambda i=index: self.remove_condition(i))\
                            .props('flat round dense color=red size=xs')
                    
                    cond.create_ui()

    def show_add_dialog(self):
        """Displays a popup dialog to select which condition to add."""
        with ui.dialog() as dialog, ui.card().classes('p-4 w-64'):
            ui.label("SELECT FILTER TYPE").classes('text-[12px] font-bold text-slate-700 mb-2')
            
            with ui.column().classes('w-full gap-2'):
                for name in CONDITION_MAP.keys():
                    # We use n=name in the lambda to capture the current loop value
                    ui.button(name, on_click=lambda n=name: (self.add_condition(n), dialog.close()))\
                        .props('outline color=primary size=sm').classes('w-full text-xs')
            
            ui.button('CANCEL', on_click=dialog.close).props('flat color=grey size=xs').classes('w-full mt-2')
        
        dialog.open()

    def add_condition(self, type_name):
        cls = CONDITION_MAP.get(type_name)
        if cls:
            self.conditions.append(cls())
            self._render_conditions()

    def remove_condition(self, index):
        if 0 <= index < len(self.conditions):
            self.conditions.pop(index)
            self._render_conditions()

    def save(self) -> dict:
        base = super().save()
        base.update({
            "logic_mode": self.logic_mode,
            "conditions": [{"type": c.type_name, "config": c.to_dict()} for c in self.conditions]
        })
        return base

    def _load_config(self, data: dict):
        self.logic_mode = data.get("logic_mode", "AND")
        self.conditions = []
        for item in data.get("conditions", []):
            cls = CONDITION_MAP.get(item.get("type"))
            if cls:
                instance = cls()
                instance.from_dict(item.get("config"))
                self.conditions.append(instance)