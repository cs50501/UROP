from pathlib import Path
import argparse
import math

from pipeline.config_loader import load_config
from pipeline.checkpoints import update_checkpoint


ROOT = Path(__file__).resolve().parents[1]


def inspect_zones(session):
    """List boundary and fluid zones in fluent"""
    
    print("\n" + "=" * 50)
    print("BOUNDARY ZONE INSPECTION")
    print("=" * 50)
    
    boundaries = (session.settings.setup.boundary_conditions)
    
    zone_types = [
        "velocity_inlet",
        "mass_flow_inlet",
        "pressure_inlet",
        "pressure_outlet",
        "outflow",
        "wall",
        "symmetry"
    ]
    
    detected = {}
    
    for zone_type in zone_types:
        zone_object = getattr(boundaries, zone_type, None)
        
        if zone_object is None:
            continue
        
        names = zone_object.get_object_names()
        
        if names:
            detected[zone_type] = names
            print(f"{zone_type}: {names}")
            
    print("\nFLUID REGIONS")
    
    fluid_zones = (session.settings.setup.cell_zone_conditions.fluid.get_object_names())
    
    print(f"Fluid Zones: {fluid_zones}")
    
    return detected, fluid_zones


def configure_physics(session, config, fluid_zones):
    """apply cfd physics settings from YAML"""
    
    print("\n" + "=" * 50)
    print("CONFIGURING SOLVER PHYSICS")
    print("=" * 50)

    setup = session.settings.setup
    
    # 1. General solver settings
    
    solver_config = config["solver"]
    
    if solver_config["type"].replace("_", "-") != "pressure-based":
        raise ValueError("Only pressure-based solver supported")
    
    if solver_config["time"] != "steady":
        raise ValueError("Only steady-state simulations supported")
    
    if solver_config["flow_model"] != "laminar":
        raise ValueError("Only laminar flow supported for now")
    
    setup.general.solver.type.set_state("pressure-based")
    setup.general.solver.time.set_state("steady")
    
    # 2. physical models
    setup.models.viscous.model.set_state("laminar")
    setup.models.energy.enabled.set_state(solver_config["energy"])
    
    print(f"Solver: {solver_config["type"]}")
    print(f"Time: {solver_config["time"]}")
    print(f"Viscous Model: {solver_config["flow_model"]}")
    
    # 3. Fluid properties
    
    fluid_config = config["fluid"]
    
    if fluid_config["viscosity_model"] != "newtonian":
        raise NotImplementedError("Non-Newtonian Models not implemented yet")
    
    name = fluid_config["name"]
    density = float(fluid_config["density_kg_m3"])
    viscosity = float(fluid_config["dynamic_viscosity_pa_s"])
    
    if density <= 0 or viscosity <= 0:
        raise ValueError("Density and viscosity must be positive")
    
    # 4. Create or retrieve material
    materials = setup.materials.fluid
    
    if name not in materials.get_object_names():
        materials.create(name)
        
    blood = materials[name]
    
    blood.density.option.set_state("constant")
    blood.density.value.set_state(density)
    
    blood.viscosity.option.set_state("constant")
    blood.viscosity.value.set_state(viscosity)
    
    print(f"\nMaterial: {name}")
    print(f"Density: {blood.density.value.get_state()} kg/m3")
    print("Dynamic viscosity:", blood.viscosity.value.get_state(), "Pa.s")
    
    # 5. assign material to fluid zones
    for zone_name in fluid_zones:
        zone = setup.cell_zone_conditions.fluid[zone_name]
        
        if "material" in zone.child_names:
            zone.material.set_state(name)
            assigned = zone.material.get_state()
            
        else:
            zone.general.material.set_state(name)
            assigned = zone.general.material.get_state()
            
        if assigned != name:
            raise RuntimeError(f"Material assignment failed: {zone_name}")
        
        print(f"Assigned {name} to {zone_name}")
        
    print("\nPhysics setup completed.")
    
    return True


def configure_boundaries(session, config, detected_zones):
    """apply and verify boundary conditions from YAML"""
    
    print("\n" + "=" * 50)
    print("CONFIGURING BOUNDARY CONDITIONS")
    print("=" * 50)
    
    bc = session.settings.setup.boundary_conditions
    settings = config["boundaries"]
    
    inlets = settings.get("inlets", [])
    outlets = settings.get("outlets", [])
    walls = settings.get("walls", [])
    
    # 1. convert previously detected zones into a lookup
    
    zone_lookup = {}
    
    for zone_type, names in detected_zones.items():
        for name in names:
            if name in zone_lookup:
                raise ValueError(f"Duplicate detected boundary: {name}")
            
            zone_lookup[name] = zone_type
            
    print("\nDetected boundaries:")
    for name, zone_type in zone_lookup.items():
        print(f"  {name}: {zone_type}")
    
    # 2.validate required zones before changing fluent
    required = ([item["name"] for item in inlets] + [item["name"] for item in outlets] + walls)
    
    if len(required) != len(set(required)):
        raise ValueError("Duplicate boundary names in YAML")
    
    missing = [name for name in required if name not in zone_lookup]
    
    if missing:
        raise ValueError(f"Missing fluent boundary zones: {missing}")
    
    # check for unspecified flow boundaries
    flow_types = {
        "velocity_inlet",
        "mass_flow_inlet",
        "pressure_inlet",
        "pressure_outlet",
        "mass_flow_outlet",
        "outflow"
    }
    
    extra_flow_zones = [name for name, zone_type in zone_lookup.items() if zone_type in flow_types and name not in required]
    
    if extra_flow_zones:
        raise ValueError("Unconfigured flow boundaries: " f"{extra_flow_zones}")
    
    # 3. validate existing boundary roles:
    
    for item in inlets:
        name = item["name"]
        
        if zone_lookup[name] not in {"velocity_inlet", "mass_flow_inlet", "pressure_inlet"}:
            raise ValueError(f"{name} is not currently an inlet-type zone")
        
    for item in outlets:
        name = item["name"]
        
        if zone_lookup[name] not in {"pressure_outlet", "mass_flow_outlet", "outflow"}:
            raise ValueError(f"{name} is not currently an outlet-type zone")
        
    for name in walls:
        if zone_lookup[name] != "wall":
            raise ValueError(f"{name} is not a wall boundary")
        
    # 4. configure inlet boundaries
    print("\n--- INLET CONDITIONS ---")
    
    for inlet in inlets:
        name = inlet["name"]
        
        if inlet["type"] != "mass-flow-inlet":
            raise ValueError(f"{name}: unsupported inlet type")
        
        rate = inlet.get("mass_flow_kg_s")
        
        if rate is None:
            raise ValueError(f"{name}: mass flow rate not specified")
        
        rate = float(rate)
        
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError(f"{name}: invalid mass flow rate")
        
        # Change boundary type if necessary.
        if zone_lookup[name] != "mass_flow_inlet":
            print(f"Changing {name}: " f"{zone_lookup[name]} -> mass_flow_inlet")
            
            bc.set_zone_type(zone_list=[name], new_type="mass-flow-inlet")
            
        # Verify the new boundary type.
        if name not in bc.mass_flow_inlet.get_object_names():
            raise RuntimeError(f"{name}: inlet type conversion failed")
        
        # Apply mass flow rate.
        inlet_bc = bc.mass_flow_inlet[name]
        
        inlet_bc.momentum.mass_flow_rate.value.set_state(rate)
        
        # Verify assigned value.
        actual = float(inlet_bc.momentum.mass_flow_rate.value.get_state())
        
        if not math.isclose(actual, rate, rel_tol=1e-6, abs_tol=1e-12):
            raise RuntimeError(f"{name}: mass flow verification failed")
        
        print(f"{name}: {actual} kg/s")
        
    # 5. Configure outlet boundaries.
    print("\n--- OUTLET CONDITIONS ---")
    
    for outlet in outlets:
        name = outlet["name"]
        
        if outlet["type"] != "pressure-outlet":
            raise ValueError(f"{name}: unsupported outlet type")
        
        pressure = outlet.get("gauge_pressure_pa")
        
        if pressure is None:
            raise ValueError(f"{name}: outlet pressure not specified")
        
        pressure = float(pressure)
        
        if not math.isfinite(pressure):
            raise ValueError(f"{name}: invalid outlet pressure")
        
        if zone_lookup[name] != "pressure_outlet":
            print(f"Changing {name}: " f"{zone_lookup[name]} -> pressure_outlet")
            
            bc.set_zone_type(zone_list=[name], new_type="pressure-outlet")
            
        if name not in bc.pressure_outlet.get_object_names():
            raise RuntimeError(f"{name}: outlet type conversion failed")
        
        outlet_bc = bc.pressure_outlet[name]
        outlet_bc.momentum.gauge_pressure.value.set_state(pressure)
        
        actual = float(outlet_bc.momentum.gauge_pressure.value.get_state())
        
        if not math.isclose(actual, pressure, rel_tol=1e-6, abs_tol=1e-9):
            raise RuntimeError(f"{name}: pressure verification failed")
        
        print(f"{name}: {actual} Pa")
        
    # 6. Configure wall boundaries.
    print("\n--- WALL CONDITIONS ---")
    
    for name in walls:
        wall = bc.wall[name]
        
        # Explicitly configure stationary, no-slip walls
        wall.momentum.motion_bc.set_state("Stationary Wall")
        wall.momentum.shear_bc.set_state("No Slip")
        
        # Verify the applied settings
        motion = wall.momentum.motion_bc.get_state()
        shear = wall.momentum.shear_bc.get_state()
        
        if motion != "Stationary Wall":
            raise RuntimeError(
                f"{name}: Wall motion verification failed"
            )
            
        if shear != "No Slip":
            raise RuntimeError(
                f"{name}: Wall shear verification failed"
            )
            
        print(f"{name}: {motion}, {shear}")
        
    print("\nBoundary conditions configured successfully!")
    
    return True


def configure_numerics(session, config):
    """configure and verify Fluent numerical methods"""
    
    print("\n" + "=" * 50)
    print("CONFIGURING NUMERICAL METHODS")
    print("=" * 50)
    
    cfg = config["numerics"]
    methods = session.settings.solution.methods
    
    # 1. pressure-velocity coupling
    coupling = methods.p_v_coupling.flow_scheme
    
    target_coupling = cfg["pressure_velocity_coupling"]
    
    coupling.set_state(target_coupling)
    
    actual_coupling = coupling.get_state()
    
    if actual_coupling != coupling.get_state():
        raise RuntimeError("pressure-velocity coupling verification failed")
    
    print(f"Pressure-velocity coupling: {actual_coupling}")
    
    # 2. Spatial discretization
    schemes = (methods.discretization_scheme)
    print("\nCurrent discretization schemes:")
    print(schemes.get_state())
    
    desired_schemes = {"pressure": cfg["pressure_discretization"], "mom": cfg["momentum_discretization"]}
    
    for equation, target in desired_schemes.items():
        setting = schemes[equation]
        
        # inspect accepted values
        try:
            allowed = setting.allowed_values()
            
        except (AttributeError, RuntimeError):
            allowed = None
            
        if allowed is not None and target not in allowed:
            raise ValueError(f"Invalid scheme for {equation}: {target}\n" f"Allowed values: {allowed}")
        
        setting.set_state(target)
        actual = setting.get_state()
        
        if actual != target:
            raise RuntimeError(f"{equation}: discretization verification failed")
        
        print(f"{equation}; {actual}")
        
    print("\nNumerical methods configured successfully!")
    
    return True


def validate_boundary_config(config):
    """validate boundary settings before launching fluent"""
    
    boundaries = config["boundaries"]
    
    inlets = boundaries.get("inlets", [])
    outlets = boundaries.get("outlets", [])
    walls = boundaries.get("walls", [])
    
    if not inlets or not outlets:
        raise ValueError("at least one inlet and outlet are required")
    
    names = []
    
    for inlet in inlets:
        name = inlet["name"]
        names.append(name)
        
        if inlet["type"] != "mass-flow-inlet":
            raise ValueError(f"{name}: unsupported inlet type")
        
        value = inlet.get("mass_flow_kg_s")
        
        if value is None or isinstance(value, bool):
            raise ValueError(f"{name}: mass_flow_kg_s must be specified")
        
        value = float(value)
        
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name}: mass flow must be positive and finite")
        
    for outlet in outlets:
        name = outlet["name"]
        names.append(name)
        
        if outlet["type"] != "pressure-outlet":
            raise ValueError(f"{name}: unsupported outlet type")
        
        value = outlet.get("gauge_pressure_pa")
        
        if value is None or isinstance(value, bool):
            raise ValueError(f"{name}: gauge_pressure_pa must be specified")
        
        value = float(value)
        
        if not math.isfinite(value):
            raise ValueError(f"{name}: gauge pressure flow must be finite")
        
    names.extend(walls)
    
    if len(names) != len(set(names)):
        raise ValueError("Duplicate boundary names in YAML configuration")
    
    print("Boundary configuration validated")


def save_configured_case(session, case_dir, mesh_preset):
    """Save fluent case after completing solver setup"""
    
    print("\n" + "=" * 50)
    print("SAVING CONFIGURED CASE")
    print("=" * 50)
    
    output_dir = case_dir / "solver" / mesh_preset
    output_dir.mkdir(parents=True, exist_ok=True)
    
    case_file = output_dir / "configured.cas.h5"
    
    session.settings.file.write_case(file_name=str(case_file.resolve()))
    
    if not case_file.is_file():
        raise FileNotFoundError(f"Fluent did not create: {case_file}")
    
    if case_file.stat().st_size == 0:
        raise RuntimeError("Configured Fluent case file is empty")
    
    print(f"Saved configured case: {case_file}")
    
    return case_file


def setup_solver(case_name):
    """Load mesh and inspect its fluent zones"""
    
    case_dir = ROOT / "cases" / case_name
    
    # 1. Load the configuration
    config = load_config(case_name)
    
    try:
        validate_boundary_config(config)
        
    except (ValueError, TypeError, KeyError) as error:
        update_checkpoint(case_dir, "setup", "BLOCKED", str(error))
        raise
    
    mesh_preset = config["mesh"]["selected"]
    
    mesh_file = (case_dir / "meshes" / f"{mesh_preset}.msh")
    
    print(f"\nCase: {case_name}")
    print(f"Mesh preset: {mesh_preset}")
    print(f"Mesh file: {mesh_file}")
    
    # 2. Check the mesh exists
    if not mesh_file.is_file():
        message = f"Mesh not found: {mesh_file}"
        
        update_checkpoint(case_dir, "setup", "BLOCKED", message)
        
        raise FileNotFoundError(message)
    
    # 3. launch fluent solver
    
    session = None
    
    try:
        import ansys.fluent.core as pyfluent
        
        if config["software"]["fluent_version"] != "24.1":
            raise ValueError("This module currently targets Fluent 24.1")
        
        update_checkpoint(case_dir, "setup", "RUNNING", "Launching Fluent Solver")
        
        run_dir = case_dir / "_solver_work"
        run_dir.mkdir(exist_ok=True)
        
        print("\nLaunching Fluent Solver...")
        
        session = pyfluent.launch_fluent(
            product_version=pyfluent.FluentVersion.v241,
            mode="solver",
            precision="double",
            processor_count=config["software"]["processor_count"],
            ui_mode="no_gui_or_graphics",
            cwd=str(run_dir.resolve())
        )
        
        print("Fluent version:", session.get_fluent_version())
        
        # 4. Read mesh
        print("\nReading mesh...")
        
        session.settings.file.read_mesh(file_name=str(mesh_file.resolve()))
        
        print("mesh imported successfully")
        
        # 5. inspect zones
        boundaries, fluids = inspect_zones(session)
        
        if not fluids:
            raise ValueError("No fluid cell zones detected")
        
        # 6. check against yaml configuration
        
        configured_inlets = {item["name"] for item in config["boundaries"]["inlets"]}
        configured_outlets = {item["name"] for item in config["boundaries"]["outlets"]}
        detected_names = {name for names in boundaries.values() for name in names}
        missing = (configured_inlets | configured_outlets) - detected_names
        
        if missing:
            message = ("YAML boundary names not found: " + ", ".join(sorted(missing)))
                
            print(f"\nWARNING: {message}")
                
            update_checkpoint(case_dir, "setup", "NEEDS_MANUAL_REVIEW", message)
            
            print(f"WARNING: {message}")
            return
            
        # Apply physics after successful zone validation
        configure_physics(session, config, fluids)
        update_checkpoint(case_dir, "setup", "PHYSICS_APPLIED", "solver physics and blood material configured")
        
        configure_boundaries(session, config, boundaries)
        update_checkpoint(case_dir, "setup", "BOUNDARIES_APPLIED", "Boundary conditions successfully applied")
        
        configure_numerics(session, config)
        update_checkpoint(case_dir, "setup", "NUMERICS_APPLIED", "Numerical methods configured")
        
        # Save fluent case
        case_file = save_configured_case(session, case_dir, mesh_preset)
        update_checkpoint(case_dir, "setup", "CONFIGURED_SAVED", f"Configured Fluent case saved: {case_file}")
        
        print("\nSolver setup completed successfully!!")
        
    except Exception as error:
        update_checkpoint(case_dir, "setup", "FAILED", str(error))
        raise
    
    finally:
        if session is not None:
            session.exit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    setup_solver(args.case)