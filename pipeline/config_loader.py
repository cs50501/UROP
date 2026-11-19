from pathlib import Path
import copy
import yaml


def read_yaml(path):
    """read a yaml configuration file"""
    path = Path(path)
    
    if not path.is_file():
        raise FileNotFoundError(f"Configuration not found: {path}")
    
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML dictionary: {path}")
    
    return data


def deep_merge(base, override):
    """Recursively merge case settings into default"""
    result = copy.deepcopy(base)
    
    for key, value in override.items():
        if (key in result and isinstance(result[key], dict) and isinstance(value, dict)):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
            
    return result


def load_config(case_name):
    root = Path(__file__).resolve().parents[1]
    
    default = read_yaml(root / "config" / "default.yaml")
    
    presets = read_yaml(root / "config" / "mesh_presets.yaml")
    
    case_file = root / "cases" / case_name / "case.yaml"
    
    case_settings = (read_yaml(case_file) if case_file.is_file() else {})
    
    config = deep_merge(default, case_settings)
    
    selected = config["mesh"]["selected"]
    
    if selected not in presets["presets"]:
        raise ValueError(f"Unknown mesh preset: {selected}")
    
    config["mesh"]["parameters"] = (presets["presets"][selected])
    
    return config