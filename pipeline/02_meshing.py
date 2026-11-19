from pathlib import Path
import argparse
import json

from pipeline.checkpoints import update_checkpoint


def inspect_geometry_zones(session, case_dir):
    """inspect imported fluent zones without modifying them"""
    
    print("\n" + "=" * 50)
    print("GEOMETRY BOUNDARY INSPECTION")
    print("=" * 50)

    report = {
        "face_zone_ids": [],
        "face_zone_names": [],
        "face_zone_areas": {},
        "warnings": [],
        "inspection_complete": False
    }

    # Try the PyFluent meshing utilities first.
    # Availability may differ in PyFluent 0.37.2.
    try:
        utilities = session.meshing_utilities

        zone_ids = utilities.get_face_zones(filter="*")
        report["face_zone_ids"] = list(zone_ids)

        print(f"Face zones detected: {len(zone_ids)}")
        print(f"Zone IDs: {zone_ids}")

        if zone_ids:
            try:
                zone_names = (
                    utilities.convert_zone_ids_to_name_strings(
                        zone_id_list=list(zone_ids)
                    )
                )

                report["face_zone_names"] = list(zone_names)

                for zone_id, name in zip(zone_ids, zone_names):
                    print(f"  Zone {zone_id}: {name}")

                    try:
                        area = utilities.get_face_zone_area(
                            face_zone_id_list=[zone_id]
                        )
                        report["face_zone_areas"][str(name)] = area
                        print(f"    Area: {area}")
                    except Exception as error:
                        print(f"    Area unavailable: {error}")

            except Exception as error:
                report["warnings"].append(
                    f"Could not retrieve zone names: {error}"
                )

        report["inspection_complete"] = True

    except Exception as error:
        print(f"Meshing utilities unavailable: {error}")
        report["warnings"].append(
            f"Meshing utilities inspection failed: {error}"
        )

    # Try Fluent's traditional zone listing as a fallback.
    # The output may appear in the Fluent console.
    print("\nFluent boundary-zone listing:")

    try:
        session.tui.boundary.manage.list()
    except TypeError:
        try:
            session.tui.boundary.manage.list("*")
        except Exception as error:
            print(f"TUI listing unavailable: {error}")
    except Exception as error:
        print(f"TUI listing unavailable: {error}")

    # Assess whether automated boundary assignment is safe.
    zone_count = len(report["face_zone_ids"])

    if report["inspection_complete"] and zone_count < 3:
        report["warnings"].append(
            "Fewer than three face zones detected. "
            "Inlets, outlets and walls may not be separated."
        )

    if not report["inspection_complete"]:
        report["warnings"].append(
            "Automatic zone count unavailable. "
            "Review the Fluent zone listing manually."
        )

    report["requires_manual_review"] = (
        bool(report["warnings"])
        or not report["face_zone_names"]
        or not any(
            "inlet" in name.lower()
            for name in report["face_zone_names"]
        )
        or not any(
            "outlet" in name.lower()
            for name in report["face_zone_names"]
        )
        or not any(
            "wall" in name.lower()
            for name in report["face_zone_names"]
        )
    )

    output_file = case_dir / "geometry_inspection.json"

    output_file.write_text(
        json.dumps(report, indent=4),
        encoding="utf-8"
    )

    print(f"\nInspection saved: {output_file}")

    if report["requires_manual_review"]:
        print("STATUS: NEEDS MANUAL REVIEW")
    else:
        print("STATUS: BOUNDARY NAMES DETECTED")
        print("Visual verification is still required.")

    return report



def import_geometry(case_name):
    root = Path(__file__).resolve().parents[1]
    case_dir = root / "cases" / case_name
    
    geometry = [
        case_dir / "geometry.scdoc",
        case_dir / "geometry.stp",
        case_dir / "geometry.step"
    ]
    
    geometry = next((file for file in geometry_candidates if file.is_file()), None)
    
    if geometry is None:
        update_checkpoint(case_dir, "meshing", "BLOCKED", "No supported geometry file found")
        raise FileNotFoundError("Expected geometry.scdoc, .stp or .step file")
    
    print(f"Selected geometry: {geometry}")
    
    session = None
    
    try:
        import ansys.fluent.core as pyfluent
        
        update_checkpoint(case_dir, "meshing", "RUNNING", "Starting Fluent Meshing")
        
        print("Launching Fluent Meshing...")
        
        run_dir = case_dir / "_fluent_work"
        run_dir.mkdir(parents=True, exist_ok=True)
        
        session = pyfluent.launch_fluent(
            product_version="24.1",
            mode="meshing",
            precision="double",
            processor_count=4,
            ui_mode="no_gui_or_graphics",
            cwd=str(run_dir.resolve())
        )
        
        print("Fluent version: ", session.get_fluent_version())
        
        # initialize meshing workflow
        workflow = session.workflow
        
        workflow.InitializeWorkflow(WorkflowType="Watertight Geometry")
        
        # Import STEP geometry
        task = workflow.TaskObject["Import Geometry"]
        
        task.Arguments.set_state({"FileName": str(geometry.resolve())})
        
        print("Importing: ", geometry.name)
        task.Execute()
        
        update_checkpoint(case_dir, "meshing", "IMPORTED", "Geometry successfully imported")
        
        print("Geometry imported successfully!")

        report = inspect_geometry_zones(
            session,
            case_dir
        )

        if report["requires_manual_review"]:
            update_checkpoint(
                case_dir,
                "meshing",
                "NEEDS_MANUAL_REVIEW",
                "Geometry imported, but boundary zones need review."
            )
        else:
            update_checkpoint(
                case_dir,
                "meshing",
                "INSPECTED",
                "Boundary zone inspection completed."
            )

        print("\nSurface and volume meshing not yet implemented.")
    
    except Exception as error:
        update_checkpoint(case_dir, "meshing", "FAILED", str(error))
        raise
    
    finally:
        if session is not None:
            session.exit()
            
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    
    import_geometry(args.case)