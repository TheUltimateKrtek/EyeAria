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
    detections: List[Detection] = field(default_factory=list)

    def copy(self) -> 'PipelinePayload':
        """
        Creates a deep copy of the payload. 
        Crucial for branching outputs so nodes don't mutate each other's data.
        """
        return copy.deepcopy(self)

    def to_json(self) -> str:
        """Serializes the strictly-typed object back into a JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, json_str: str) -> 'PipelinePayload':
        """Parses a JSON string into strictly-typed objects."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_dict(cls, data: dict) -> 'PipelinePayload':
        """Helper to map a dictionary to the dataclass hierarchy."""
        # Convert the raw list of dictionaries into a list of Detection objects
        detections_list = [Detection(**det) for det in data.get("detections", [])]
        
        return cls(
            timestamp=data.get("timestamp", 0.0),
            config=data.get("config", {}),
            count=data.get("count", len(detections_list)),
            detections=detections_list
        )