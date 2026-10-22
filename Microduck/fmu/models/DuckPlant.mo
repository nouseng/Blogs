model DuckPlant "Microduck robot on the ground without the policy: joint targets in, IMU and joint states out"
  parameter Modelica.Units.SI.Voltage supply = 7.4 "Supply voltage of all servos";
  parameter Real friction(unit = "1") = 1 "Friction coefficient of the soles";
  parameter Modelica.Units.SI.Voltage kneeSupply = 7.4 "Supply voltage of the left knee servo";
  parameter Modelica.Units.SI.Angle kneeBacklash = 0.0349065850398866 "Gear play of the left knee servo";
  parameter Real kneeGain(unit = "1") = 200 "Position gain register of the left knee servo, 0 for unpowered";
  inner Modelica.Mechanics.MultiBody.World world(n = {0, 0, -1}, enableAnimation = false);
  // Cardan angles rather than quaternions: the quaternion start of an FMU can settle on the trunk turned over
  Modelica.Mechanics.MultiBody.Joints.FreeMotion trunkJoint(
    useQuaternions = false,
    r_rel_a(start = {0, 0, 0.12}, each fixed = true),
    v_rel_a(each fixed = true),
    angles_fixed = true,
    w_rel_a_fixed = true,
    animation = false);
  Duck.Components.Robot robot(animation = false, supplyVoltage = supply, mu = friction,
    leftKnee(supplyVoltage = kneeSupply, backlash = kneeBacklash, positionGain = kneeGain));
  Modelica.Mechanics.MultiBody.Sensors.AbsoluteAngularVelocity gyroSensor(resolveInFrame = Modelica.Mechanics.MultiBody.Types.ResolveInFrameA.frame_a);
  Modelica.Blocks.Interfaces.RealInput qRef[14](each unit = "rad") "Joint angle targets as they reach the servos";
  Modelica.Blocks.Interfaces.RealOutput gyro[3](each unit = "rad/s") "Angular velocity of the trunk in the IMU frame";
  Modelica.Blocks.Interfaces.RealOutput gravity[3](each unit = "1") = {-robot.frame_imu.R.T[1, 3], -robot.frame_imu.R.T[2, 3], -robot.frame_imu.R.T[3, 3]} "Gravity direction in the IMU frame";
  Modelica.Blocks.Interfaces.RealOutput q[14](each unit = "rad") = robot.q "Joint angles read by the encoders";
  Modelica.Blocks.Interfaces.RealOutput w[14](each unit = "rad/s") = robot.w "Joint speeds";
  Modelica.Blocks.Interfaces.RealOutput x(unit = "m") = robot.frame_a.r_0[1] "Forward position of the trunk";
  Modelica.Blocks.Interfaces.RealOutput z(unit = "m") = robot.frame_a.r_0[3] "Trunk height";
  Modelica.Blocks.Interfaces.RealOutput pitch(unit = "rad") = asin(-robot.frame_a.R.T[1, 3]) "Trunk pitch, nose down positive";
  Modelica.Blocks.Interfaces.RealOutput motorCurrent[14](each unit = "A") = {(robot.leftHipYaw.servo.voltage - robot.leftHipYaw.servo.torqueConstant * robot.leftHipYaw.servo.speedSensor.w_rel) / robot.leftHipYaw.servo.resistance,
    (robot.leftHipRoll.servo.voltage - robot.leftHipRoll.servo.torqueConstant * robot.leftHipRoll.servo.speedSensor.w_rel) / robot.leftHipRoll.servo.resistance,
    (robot.leftHipPitch.servo.voltage - robot.leftHipPitch.servo.torqueConstant * robot.leftHipPitch.servo.speedSensor.w_rel) / robot.leftHipPitch.servo.resistance,
    (robot.leftKnee.servo.voltage - robot.leftKnee.servo.torqueConstant * robot.leftKnee.servo.speedSensor.w_rel) / robot.leftKnee.servo.resistance,
    (robot.leftAnkle.servo.voltage - robot.leftAnkle.servo.torqueConstant * robot.leftAnkle.servo.speedSensor.w_rel) / robot.leftAnkle.servo.resistance,
    (robot.neckPitch.servo.voltage - robot.neckPitch.servo.torqueConstant * robot.neckPitch.servo.speedSensor.w_rel) / robot.neckPitch.servo.resistance,
    (robot.headPitch.servo.voltage - robot.headPitch.servo.torqueConstant * robot.headPitch.servo.speedSensor.w_rel) / robot.headPitch.servo.resistance,
    (robot.headYaw.servo.voltage - robot.headYaw.servo.torqueConstant * robot.headYaw.servo.speedSensor.w_rel) / robot.headYaw.servo.resistance,
    (robot.headRoll.servo.voltage - robot.headRoll.servo.torqueConstant * robot.headRoll.servo.speedSensor.w_rel) / robot.headRoll.servo.resistance,
    (robot.rightHipYaw.servo.voltage - robot.rightHipYaw.servo.torqueConstant * robot.rightHipYaw.servo.speedSensor.w_rel) / robot.rightHipYaw.servo.resistance,
    (robot.rightHipRoll.servo.voltage - robot.rightHipRoll.servo.torqueConstant * robot.rightHipRoll.servo.speedSensor.w_rel) / robot.rightHipRoll.servo.resistance,
    (robot.rightHipPitch.servo.voltage - robot.rightHipPitch.servo.torqueConstant * robot.rightHipPitch.servo.speedSensor.w_rel) / robot.rightHipPitch.servo.resistance,
    (robot.rightKnee.servo.voltage - robot.rightKnee.servo.torqueConstant * robot.rightKnee.servo.speedSensor.w_rel) / robot.rightKnee.servo.resistance,
    (robot.rightAnkle.servo.voltage - robot.rightAnkle.servo.torqueConstant * robot.rightAnkle.servo.speedSensor.w_rel) / robot.rightAnkle.servo.resistance} "Motor current of each servo";
  Modelica.Blocks.Interfaces.RealOutput batteryCurrent(unit = "A") = robot.leftHipYaw.servo.drive * motorCurrent[1] +
    robot.leftHipRoll.servo.drive * motorCurrent[2] +
    robot.leftHipPitch.servo.drive * motorCurrent[3] +
    robot.leftKnee.servo.drive * motorCurrent[4] +
    robot.leftAnkle.servo.drive * motorCurrent[5] +
    robot.neckPitch.servo.drive * motorCurrent[6] +
    robot.headPitch.servo.drive * motorCurrent[7] +
    robot.headYaw.servo.drive * motorCurrent[8] +
    robot.headRoll.servo.drive * motorCurrent[9] +
    robot.rightHipYaw.servo.drive * motorCurrent[10] +
    robot.rightHipRoll.servo.drive * motorCurrent[11] +
    robot.rightHipPitch.servo.drive * motorCurrent[12] +
    robot.rightKnee.servo.drive * motorCurrent[13] +
    robot.rightAnkle.servo.drive * motorCurrent[14] "Current drawn by all servos from an ideal supply";
  Modelica.Blocks.Interfaces.RealOutput servoTorque[14](each unit = "N.m") = {robot.leftHipYaw.servo.tau, robot.leftHipRoll.servo.tau, robot.leftHipPitch.servo.tau, robot.leftKnee.servo.tau, robot.leftAnkle.servo.tau, robot.neckPitch.servo.tau, robot.headPitch.servo.tau, robot.headYaw.servo.tau, robot.headRoll.servo.tau, robot.rightHipYaw.servo.tau, robot.rightHipRoll.servo.tau, robot.rightHipPitch.servo.tau, robot.rightKnee.servo.tau, robot.rightAnkle.servo.tau} "Servo torque on each joint";
equation
  connect(world.frame_b, trunkJoint.frame_a);
  connect(trunkJoint.frame_b, robot.frame_a);
  connect(robot.frame_imu, gyroSensor.frame_a);
  connect(gyroSensor.w, gyro);
  connect(qRef, robot.qRef);
  annotation(experiment(StartTime = 0, StopTime = 6, Tolerance = 1e-6, Interval = 0.001));
end DuckPlant;
