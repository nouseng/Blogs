# Why Rebuild a Walking Robot Duck in Modelica?

Vedat Senol and Ogulcan Isitman

A flock of 25 cm
[MicroDuck robots walked out on stage with Jensen Huang at NVIDIA GTC](https://www.youtube.com/watch?v=Nt6d62vN7CU).
Pollen Robotics and Hugging Face released the
[MuJoCo training environment](https://github.com/pollen-robotics/microduck_rl)
and [neural network weights](https://huggingface.co/pollen-robotics/microduck-policies)
under Apache-2.0, and the trained policy walks on real hardware. So why did we
rebuild the robot in Modelica?

Because "does it walk on stage?" is only the first question.

![The MicroDuck walking forward under its neural network policy in MuJoCo](images/walk.gif)

*Figure 1: The MicroDuck walking under its trained policy at a 0.3 m/s forward
command, rendered in MuJoCo.*

## Two Simulators, Two Jobs

The MicroDuck is a 25 cm biped with 14 Dynamixel XL330 servos and a modelled
mass of 0.737 kg. Its policy reads the IMU and joint states 50 times a second
and sends 14 joint targets back. MuJoCo is the right tool to train it. On a
desktop CPU it runs a 6 s walk in 0.55 s, and reinforcement learning needs
millions of those.

Speed comes at a price. MuJoCo has no electrical, thermal or 1D drivetrain
domain. In [`microduck_rl`](https://github.com/pollen-robotics/microduck_rl),
the built-in actuator is disabled and a Python callback runs before every
`mj_step` to compute motor torque from the
[BAM XL330 model](https://github.com/Rhoban/bam) at a fixed episode voltage.
Ground contact is C code inside the solver.

Rebuilding the robot as an equation-based plant in Modelica opens what a
rigid-body callback setup cannot reach:

- **Mechanics, electronics and heat in one solver.** Connect all 14 servos to
  one two-cell battery pack (`useBattery = true`) and pack voltage sags whenever
  the motors pull a current spike together, lowering torque at that same
  instant. Enable the servo thermal network (`useThermal = true`) and both
  winding copper loss ($R i^2$) and gearbox friction ($\tau_{\mathrm{f}}\omega$)
  heat the servo, raising copper resistance by 0.39% per kelvin. Modelica
  solves all three domains together at every step, without callback lag.
- **Gear play and drivetrains without extra 3D joints.** Every servo has 2° of
  gear play between motor and link, with the encoder on the link side. Because
  MuJoCo only has 3D joints, the training model had to insert 14 extra 3D hinge
  joints into the robot's body tree to mimic that play and add pairs of joint
  angles in Python to get the encoder reading. Modelica keeps the 14 physical
  3D joints and puts the motor, the 2° play and the encoder on each joint's 1D
  drive shaft.
- **Open, replaceable physics equations.** In MuJoCo, ground contact is
  compiled C code inside the solver: you can tune its parameters, whereas
  changing the law means editing the C engine. In Modelica, contact is a
  60-line equation block (`PointContact`), so you can swap a spring-damper sole
  for soft pyramidal contact without touching the rest of the robot.
- **Inverse dynamics and FMU export.** Because the plant is written as
  equations rather than a forward step function, the compiler can invert a
  joint from motion to required motor voltage and export the whole robot as a
  standalone FMU (`DuckPlant.fmu`) for Python, Simulink or hardware-in-the-loop
  tests.

![Diagram view of the WalkingTest model in OpenModelica](images/WalkingTest.svg)

*Figure 2: Diagram view of `WalkingTest` in OpenModelica, wiring the 3D
multibody `Robot` plant, IMU and joint sensors to the 50 Hz `WalkingPolicy`
block.*

## Verify Before Adding Anything

A second model is worthless if it disagrees with the first one for reasons
nobody understands. Before extending the plant, we matched the baseline
Modelica model against the MuJoCo model it was generated from.

At [Nous Engineering & Research](https://nouseng.co), we built the `MicroDuck`
library directly from the training MJCF file, so masses, inertias and joint
frames are identical by construction. Forward kinematics agree to
$4 \times 10^{-13}\ \mathrm{m}$. Each joint drives a 3D revolute joint through a
`PositionServo` with the identified XL330 parameters (torque constant
0.346 N·m/A, winding resistance 2.50 Ω, rotor inertia 0.00157 kg·m², Coulomb
and viscous friction) and 2° of gear play. Under each sole sit eight
`PointContact` elements implementing MuJoCo's soft pyramidal contact law. The
50 Hz `WalkingPolicy` block applies the mean training command delay of 22.5 ms.

Same policy, same 0.3 m/s command, two simulators. After 6 s the Modelica robot
has covered 0.797 m against 0.799 m in MuJoCo. Its 22 stance touchdowns land
25 ms from MuJoCo's on average, at a mean trunk height of 118 mm, and over the
last 4 s it walks at 0.137 m/s against 0.132 m/s.

![The MicroDuck walking forward under its neural network policy in OpenModelica](images/walk_modelica.gif)

*Figure 3: The Modelica MicroDuck walking under the same trained policy at a
0.3 m/s forward command, rendered in OpenModelica.*

![Forward position and trunk height over a 6 s walk, Modelica against MuJoCo](images/walking.png)

*Figure 4: Forward position (top) and trunk height (bottom) over a 6 s walk.
Solid: the Modelica MicroDuck library. Dashed: MuJoCo, same policy and command.*

## What the Plant Answers Next

In Modelica a 6 s walk takes about 6 s on a desktop CPU against 0.55 s in
MuJoCo. Nobody should train a policy this way. Once the policy is trained and
the plant is verified, the equation-based model answers hardware and control
questions across domains:

- **How the policy walks on servos too soft to stand on.** At a gain
  register of 800 (2.36 N·m/rad) the robot stands upright. At the walking gain
  of 200 (0.589 N·m/rad, four times softer), asked to stand still, it tips past
  30° in 0.74 s. During the walk the policy swings its angle targets 24° RMS
  ahead of the knees, using position error as a torque command while staying
  below 30% of the 1.01 N·m stall torque.
- **Battery discharge, current spikes and voltage sag.** With the 2S
  pack (`useBattery = true`) at `soc0` = 0.68 (7.40 V open-circuit), the 0.92 A
  touchdown spike across all 14 servos pulls terminal voltage down to 7.34 V (a
  64.5 mV sag), while the servos draw 2.26 W on average and drain 0.019% of the
  2.6 Ah pack every 6 s.
- **Policy sensitivity to the ground law.** Swapping MuJoCo's soft
  contact (where the stance foot slips 43 mm/s) for a firmer spring-damper
  floor (6.5 mm/s slip) makes the same policy walk nearly 50% faster, showing
  how strongly a learned gait depends on the contact compliance it was trained
  on.
- **Servo heating, torque fade and faults.** With the thermal network
  enabled (`useThermal = true`), the 14 servos dissipate 1.79 W in copper and
  0.37 W in gearbox friction (2.17 W total), warming the knee windings by 1.4 to
  1.7 K in 6 s. On a long walk, climbing from 20 °C to the XL330's 70 °C
  firmware limit raises copper resistance by 20% (softening the joint) and then
  trips `Torque Enable = 0`, which collapses the robot in 0.83 s. Even before a
  trip, a weakened left knee shifts 20% more copper heating (0.42 to 0.50 W)
  onto the opposite right knee.

MuJoCo and Modelica solve different halves of the problem. Train the policy in
the fast contact engine, then bring the weights into an equation-based plant
where the drivetrains, the battery, the thermal network and the contact law are
open equations you can inspect and extend. The
[`MicroDuck` library](https://github.com/nouseng/libraries/tree/main/RoboticsAtelier/MicroDuck)
is developed by [Nous Engineering & Research](https://nouseng.co) and runs in
OpenModelica with the Modelica Standard Library. If a training simulator and
your hardware disagree, that gap is where we work.

## References

- **MuJoCo robot model and meshes:**
  [`pollen-robotics/microduck_rl`](https://github.com/pollen-robotics/microduck_rl)
  (`src/mjlab_microduck/robot/microduck/`, Apache-2.0).
- **Trained neural network walking policy (`velstand.onnx`):**
  [`pollen-robotics/microduck-policies`](https://huggingface.co/pollen-robotics/microduck-policies)
  (Apache-2.0).
- **Identified Dynamixel XL330 actuator model:**
  [`Rhoban/bam`](https://github.com/Rhoban/bam)
  (`bam/params/xl330/m6.json`, Apache-2.0).
- **Modelica plant library (`MicroDuck` & `MicroDuckTest`):**
  [`nouseng/libraries/RoboticsAtelier/MicroDuck`](https://github.com/nouseng/libraries/tree/main/RoboticsAtelier/MicroDuck)
  (BSD 3-Clause).
- **Post 1 notebook, FMU and MuJoCo files:**
  [`nouseng/Blogs/Microduck/post-1`](https://github.com/nouseng/Blogs/tree/main/Microduck/post-1).
