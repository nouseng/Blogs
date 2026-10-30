# MuJoCo Reference

The MuJoCo side of the Microduck series: the training model, the walking
policy and two notebooks.

- `walk.ipynb` — self-contained walk: loads the model, applies the BAM XL330
  servo model and the command delay, runs the policy at 50 Hz, renders a video
  and plots the trunk. Run it from this folder.
- `build_duck.ipynb` — the same robot assembled with `MjSpec` from the STL
  meshes, checked against the reference MJCF and a bit-identical walk.
- `model/scene_backlash.xml`, `model/robot_groundcontact_backlash.xml`,
  `model/assets/` — the robot with 2° of gear play per servo, as used to train
  the policy.
- `velstand.onnx` — the deployed walking policy.

```bash
pip install -r ../requirements.txt
jupyter notebook walk.ipynb
```

## Sources and licences

- Robot model and meshes: [pollen-robotics/microduck_rl](https://github.com/pollen-robotics/microduck_rl),
  `src/mjlab_microduck/robot/microduck/`, commit 273afe0b, Apache-2.0.
- Policy: [pollen-robotics/microduck-policies](https://huggingface.co/pollen-robotics/microduck-policies),
  `velstand.onnx`, Apache-2.0.
- Servo parameters: [Rhoban/bam](https://github.com/Rhoban/bam),
  `bam/params/xl330/m6.json`, Apache-2.0.

These files are redistributed under their Apache-2.0 licences.
