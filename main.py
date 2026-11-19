from pathlib import Path
import argparse
import json
from datetime import datetime, timezone

from pipeline.checkpoints import update_checkpoint


# Pipeline execution order

STAGES = [
    "geometry",
    "meshing",
    "setup",
    "solve",
    "postprocess"
]

# files required to start each stage

REQUIRED_INPUTS = {
    "geometry": [("input.stl",)],
    "meshing": [("geometry.stp", "geometry.step")],
    "setup": [("mesh.msh.h5",)],
    "solve": [("configured.cas.h5",)],
    "postprocess": [("solution.cas.h5",), ("solution.dat.h5",)]
}


def check_inputs(case_dir, stage):
    """Check required inputs, including alternate extensions."""
    
    missing = []
    
    for alternatives in REQUIRED_INPUTS[stage]:
        if not any((case_dir / filename).is_file() for filename in alternatives):
            missing.append(" or ".join(alternatives))
            
    return missing


def main():
    parser = argparse.ArgumentParser(description="Coronary CFD automation pipeline")
    
    parser.add_argument("--case", required=True, help="Case name, e.g. Case_01")
    
    parser.add_argument("--from", dest="start_stage", choices=STAGES, required=True, help="Pipeline starting stage")
    
    args = parser.parse_args()
    
    case_dir = Path(__file__).resolve().parent / "cases" / args.case
    case_dir.mkdir(parents=True, exist_ok=True)
    
    stage = args.start_stage
    
    print(f"\nCase: {args.case}")
    print(f"Starting Stage: {args.start_stage}")
    
    
    print(f"Looking for geometry in: {case_dir.resolve()}")
    print(f"Folder exists in: {case_dir.exists()}")
    
    print(f"\nFiles in Case Folder:")
    for file in case_dir.iterdir():
        print(f" - {file.name}")
        
    missing = check_inputs(case_dir, stage)
    
    if missing:
        message = f"Missing input: {', '.join(missing)}"
        
        update_checkpoint(case_dir, stage, "BLOCKED", message)
        print(f"ERROR: {message}")
        raise SystemExit(1)
        
        
    update_checkpoint(case_dir, stage, "READY", "Input validation successful")
    
    print("\nAll required files found.")
    print("Ready for stage execution.")
    print("ANSYS automation is not implemented yet.")
    
    return


if __name__ == "__main__":
    main()