# Microduck

Code, models and data for the five-post Microduck series on
[nouseng.co](https://nouseng.co): the Pollen Robotics Microduck biped as a
Modelica plant model, checked against the MuJoCo model its walking policy was
trained on.

## Layout

- `post-1` … `post-5` — one folder per post: the post, a notebook, the
  figures, the data behind them and the wrapper models.
- `fmu/DuckPlant.fmu` — the robot without the policy, FMI 2.0 Model Exchange,
  Windows 64-bit. Input `qRef[14]` (joint targets as they reach the servos);
  outputs IMU (`gyro`, `gravity`), joint angles and speeds, trunk position and
  pitch, motor currents, supply current and servo torques. Parameters `supply`,
  `friction`, `kneeSupply`, `kneeBacklash`, `kneeGain`.
- `fmu/DuckStand.fmu` — the robot holding its home pose at servo gain `gain`.
- `fmu/models/` — Modelica sources of both FMUs and their export scripts.
- `mujoco/` — the MuJoCo training model, the ONNX policy and the MuJoCo
  notebooks, see [`mujoco/README.md`](mujoco/README.md).
- `common.py` — plot style and the helpers the notebooks use: `walk_fmu`,
  `stand_fmu`, `walk_mujoco`.

## How the walking notebooks work

The policy is not inside the FMU. `walk_fmu` runs `mujoco/velstand.onnx` in
Python at 50 Hz on the FMU's IMU and joint outputs, with the training
observation layout, action scale, target filters and the 22.5 ms command delay,
and integrates the FMU between control steps with fixed-step fourth-order
Runge-Kutta at 1 ms. A 6 s walk takes about 45 s.

The OpenModelica runs quoted in the posts applied the 22.5 ms delay at the next
1 ms step. `walk_fmu(command_delay=0.023)` reproduces them: at a 0.3 m/s
command it walks 0.133 m/s against 0.131 m/s, with joint angles within a few
milliradians. Walking is sensitive to such details at startup, so the speed
over the last 4 s moves by a few percent between equivalent runs.

## Run

```bash
pip install -r requirements.txt
cd post-1
jupyter notebook why-modelica.ipynb
```

The FMUs need Windows 64-bit. To rebuild them, copy `fmu/models/` into
`<Microduck repo>/build/<task>/` and run `omc export_plant.mos` and
`omc export_stand.mos` there.
