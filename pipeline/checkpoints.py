import json
from pathlib import Path
from datetime import datetime, timezone


def load_checkpoint(case_dir):
    """
    load the existing checkpoint, or create a new one
    """
    
    checkpoint_file = Path(case_dir) / "status.json"
    
    if checkpoint_file.exists():
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # Support simple status.json
        if "stages" in data:
            return data
        
    return {
        "case": Path(case_dir).name,
        "stages": {}
    }
    
    
def update_checkpoint(case_dir, stage, status, message):
    """
    Update one stage without overwriting other stages
    """   
    
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    
    data = load_checkpoint(case_dir)
    
    now = datetime.now(timezone.utc).isoformat()
    
    data["stages"][stage] = {
        "status": status,
        "message": message,
        "updated_at": now
    }
    
    checkpoint_file = case_dir / "status.json"
    temporary_file = case_dir / "status.json.tmp"
    
    temporary_file.write_text(json.dumps(data, indent=4), encoding="utf-8")
    
    temporary_file.replace(checkpoint_file)
    
    print(f"Checkpoint saved: {stage} -> {status}")