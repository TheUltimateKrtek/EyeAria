import json
import copy
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any

@dataclass
class Detection:
    """1:1 mapping for the objects inside the 'detections' list."""
    label: str
    confidence: float
    bbox: List[float]  # [xmin, ymin, xmax, ymax]
    track_id: int = -1

@dataclass
class PipelinePayload:
    """1:1 mapping for the root JSON payload."""
    timestamp: float
    config: Dict[str, Any]
    count: int
    model_name: str = ""
    pi_uuid: str = ""
    camera_url: str = ""
    detections: List[Detection] = field(default_factory=list)

    def copy(self) -> 'PipelinePayload':
        return copy.deepcopy(self)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, json_str: str) -> 'PipelinePayload':
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_dict(cls, data: dict) -> 'PipelinePayload':
        detections_list = [Detection(**det) for det in data.get("detections", [])]
        config_data = data.get("config", {})
        
        return cls(
            timestamp=data.get("timestamp", 0.0),
            config=config_data,
            count=data.get("count", len(detections_list)),
            # Load explicitly from root dict, or fallback to config dictionary
            model_name=data.get("model_name", config_data.get("model_name", "")),
            pi_uuid=data.get("pi_uuid", config_data.get("pi_uuid", "")),
            camera_url=data.get("camera_url", config_data.get("camera_url", "")),
            detections=detections_list
        )