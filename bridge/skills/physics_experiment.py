from .models import SkillResult, SkillDef

METADATA = {
    "name": "physics_experiment",
    "version": "1.0.0",
    "category": "science",
    "description": "Simulate physics experiments (pendulum, projectile, spring, wave).",
}


def execute(experiment: str = "pendulum", params: dict = None, **kwargs) -> SkillResult:
    if params is None:
        params = {}

    valid_experiments = ("pendulum", "projectile", "spring", "wave")
    if experiment not in valid_experiments:
        return SkillResult.fail(f"Invalid experiment '{experiment}'. Must be one of: {valid_experiments}")

    try:
        import numpy as np
    except ImportError:
        return SkillResult.fail("numpy is not installed. Install with: pip install numpy")

    try:
        if experiment == "pendulum":
            result = _simulate_pendulum(params, np)
        elif experiment == "projectile":
            result = _simulate_projectile(params, np)
        elif experiment == "spring":
            result = _simulate_spring(params, np)
        elif experiment == "wave":
            result = _simulate_wave(params, np)
        else:
            return SkillResult.fail(f"Unknown experiment: {experiment}")

        return SkillResult.ok(output=result["summary"], data=result["data"])
    except Exception as e:
        return SkillResult.fail(f"Physics simulation error: {e}")


def _simulate_pendulum(params: dict, np) -> dict:
    g = float(params.get("gravity", 9.81))
    L = float(params.get("length", 1.0))
    theta0 = float(params.get("initial_angle", 30))
    t_max = float(params.get("duration", 10))

    theta0_rad = np.radians(theta0)
    t = np.linspace(0, t_max, 500)
    omega = np.sqrt(g / L)
    theta = theta0_rad * np.cos(omega * t)
    period = 2 * np.pi / omega

    summary = (
        f"Pendulum Simulation Results:\n"
        f"  Length: {L} m\n"
        f"  Gravity: {g} m/s^2\n"
        f"  Initial angle: {theta0} degrees\n"
        f"  Period: {period:.4f} s\n"
        f"  Angular frequency: {omega:.4f} rad/s\n"
        f"  Max velocity: {theta0_rad * omega * L:.4f} m/s\n"
        f"  Simulation duration: {t_max} s"
    )
    return {"summary": summary, "data": {"period": period, "omega": float(omega), "experiment": "pendulum"}}


def _simulate_projectile(params: dict, np) -> dict:
    g = float(params.get("gravity", 9.81))
    v0 = float(params.get("initial_velocity", 20.0))
    angle = float(params.get("launch_angle", 45.0))

    angle_rad = np.radians(angle)
    vx = v0 * np.cos(angle_rad)
    vy = v0 * np.sin(angle_rad)
    t_flight = 2 * vy / g
    max_height = vy ** 2 / (2 * g)
    range_val = vx * t_flight

    summary = (
        f"Projectile Motion Results:\n"
        f"  Initial velocity: {v0} m/s\n"
        f"  Launch angle: {angle} degrees\n"
        f"  Gravity: {g} m/s^2\n"
        f"  Time of flight: {t_flight:.4f} s\n"
        f"  Maximum height: {max_height:.4f} m\n"
        f"  Range: {range_val:.4f} m\n"
        f"  Horizontal velocity: {vx:.4f} m/s\n"
        f"  Initial vertical velocity: {vy:.4f} m/s"
    )
    return {"summary": summary, "data": {"t_flight": float(t_flight), "max_height": float(max_height), "range": float(range_val), "experiment": "projectile"}}


def _simulate_spring(params: dict, np) -> dict:
    k = float(params.get("spring_constant", 10.0))
    m = float(params.get("mass", 1.0))
    x0 = float(params.get("initial_displacement", 0.5))
    t_max = float(params.get("duration", 10))

    omega = np.sqrt(k / m)
    t = np.linspace(0, t_max, 500)
    x = x0 * np.cos(omega * t)
    v = -x0 * omega * np.sin(omega * t)
    period = 2 * np.pi / omega
    max_ke = 0.5 * m * (x0 * omega) ** 2
    max_pe = 0.5 * k * x0 ** 2

    summary = (
        f"Spring-Mass System Results:\n"
        f"  Spring constant: {k} N/m\n"
        f"  Mass: {m} kg\n"
        f"  Initial displacement: {x0} m\n"
        f"  Period: {period:.4f} s\n"
        f"  Angular frequency: {omega:.4f} rad/s\n"
        f"  Max kinetic energy: {max_ke:.4f} J\n"
        f"  Max potential energy: {max_pe:.4f} J\n"
        f"  Total energy: {max_ke:.4f} J"
    )
    return {"summary": summary, "data": {"period": float(period), "omega": float(omega), "total_energy": float(max_ke), "experiment": "spring"}}


def _simulate_wave(params: dict, np) -> dict:
    A = float(params.get("amplitude", 1.0))
    f = float(params.get("frequency", 1.0))
    wavelength = float(params.get("wavelength", 2.0))
    t_max = float(params.get("duration", 5))

    k = 2 * np.pi / wavelength
    omega = 2 * np.pi * f
    v = f * wavelength

    summary = (
        f"Wave Simulation Results:\n"
        f"  Amplitude: {A} m\n"
        f"  Frequency: {f} Hz\n"
        f"  Wavelength: {wavelength} m\n"
        f"  Wave speed: {v:.4f} m/s\n"
        f"  Wave number: {k:.4f} rad/m\n"
        f"  Angular frequency: {omega:.4f} rad/s\n"
        f"  Period: {1/f:.4f} s"
    )
    return {"summary": summary, "data": {"wave_speed": float(v), "wave_number": float(k), "angular_frequency": float(omega), "experiment": "wave"}}


def register(registry) -> None:
    registry.register(SkillDef(
        name="physics_experiment",
        description="Simulate physics experiments: pendulum, projectile, spring, or wave motion.",
        category="science",
        parameters={
            "type": "object",
            "properties": {
                "experiment": {
                    "type": "string",
                    "enum": ["pendulum", "projectile", "spring", "wave"],
                    "description": "Type of physics experiment to simulate",
                },
                "params": {
                    "type": "object",
                    "description": "Experiment parameters (e.g. gravity, length, mass, velocity, angle)",
                },
            },
            "required": [],
        },
        handler=execute,
        timeout=15,
    ))
