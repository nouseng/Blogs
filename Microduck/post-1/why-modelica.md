# Why We Built a Walking Robot Duck Twice

Vedat Senol and Ogulcan Isitman

The Microduck already walks. Pollen Robotics trained its neural network policy
in MuJoCo, released the model and the weights under Apache-2.0, and the robot
walks on real hardware. So why did we spend weeks rebuilding it in Modelica?

Because "does it walk?" is only the first question.

![The Microduck walking forward under its neural network policy in MuJoCo](images/walk.gif)

*Figure 1: The Microduck walking under its trained policy at a 0.3 m/s forward
command, rendered in MuJoCo.*

## Two Simulators, Two Jobs

The Microduck is a 25 cm biped with 14 Dynamixel XL330 servos and a modelled
mass of 0.737 kg. Its policy reads the IMU and joint states 50 times a second
and sends 14 joint targets back. MuJoCo is the right tool to train it. It runs
a 6 s walk in 0.55 s, and reinforcement learning needs millions of those.

Speed comes at a price. In MuJoCo the servo is a parameter set tuned so the
training converges. Questions an engineer asks next sit outside that model.
What happens when the battery drains from 8.2 V to 6.5 V? How much heat does a
knee motor make on a long walk? If one joint goes limp, does the robot fall?

Answering those needs a plant model: equations for the motor, the gear, the
contact and the supply, written so that changing one physical value changes the
physics downstream. Modelica is built for that. MultiBody assembles the
equations of motion from the kinematic tree, and a single `connect` between a
motor and a joint gives the force balance without rewriting either side.

## Verify Before Adding Anything

A second model is worthless if it disagrees with the first one for reasons
nobody understands. So before adding a single new feature, we matched the
Modelica model against the MuJoCo model it was generated from.

The library is generated from the same MJCF file the policy was trained on,
so masses, inertias and joint frames are identical by construction. Forward
kinematics agree to 4e-13 m. The servo uses the identified XL330 motor model
from the [BAM project](https://github.com/Rhoban/bam): torque constant
0.346 N·m/A, resistance 2.50 Ω, 2° of gear play and a random command delay
averaging 22.5 ms, as in training.

Then the real test. Same policy, same command, two simulators. At a 0.3 m/s
command both step at 2.0 Hz and walk at 0.131 and 0.132 m/s, and after 6 s the
Modelica robot has covered 0.785 m against 0.799 m in MuJoCo.

![Forward position and trunk height over a 6 s walk, Modelica against MuJoCo](images/walking.png)

*Figure 2: Forward position (top) and trunk height (bottom) over a 6 s walk.
Solid: the Modelica Duck library. Dashed: MuJoCo, same policy and command.*

## The Match Was Not Free

The first walking run did not match at all. Modelica walked at 0.25 m/s,
MuJoCo at 0.17 m/s. Same robot, same network.

We first tried tuning the contact stiffness, and got walking right while a
drop test went badly wrong. Tuning hid the problem. The cause turned out to be
the ground. In MuJoCo the stance foot slips about 43 mm/s, whereas our
spring-damper soles slipped 6.5 mm/s. The policy had learned to walk on
MuJoCo's soft contact, slip included. A policy trained in one simulator has
learned that simulator's contact law, and a different law is a different robot.

The fix was to reimplement MuJoCo's soft contact formulation point by point,
eight points under each sole. After that, standing, dropping, sliding and
walking all matched at the nominal friction. Part 4 of this series tells that
story in detail.

It is not a perfect match everywhere. At a 0.4 m/s command Modelica walks
0.191 m/s against MuJoCo's 0.175 m/s, and that gap is still open. We prefer
stating it to hiding it.

## What It Costs, What It Buys

Modelica is the slow tool here. A 6 s walk takes about 15 s with fixed-step
Runge-Kutta against 0.55 s in MuJoCo. Nobody should train a policy this way.

What it buys is the plant. A first example: we swept the servo supply across the
range the policy was trained on, with everything else fixed.

| Supply | Walking speed | Mean servo power |
| :---: | :---: | :---: |
| 8.2 V | 0.137 m/s | 2.63 W |
| 7.4 V | 0.132 m/s | 2.35 W |
| 6.5 V | 0.128 m/s | 2.14 W |

A drained pack costs 7% of walking speed, and peak supply current rises from
0.90 A to 1.18 A. This is an ideal supply. Whether a real pack's sag
changes the picture is Part 3.

The split we recommend is the one this project followed. Train in the fast
contact engine, then verify and extend the plant in an equation-based model. We
use the same split for floating offshore wind turbines, where a fast load tool
runs thousands of cases and a detailed subsystem model checks the ones that
matter.

## The Series

1. Why build it twice (this post)
2. The servo is a motor, not a gain
3. What an empty battery does to the gait
4. Same policy, 50% faster: the contact law was the model
5. When a servo fails

The model runs in OpenModelica with the Modelica Standard Library. If a
training simulator and your hardware disagree, that gap is where we work.
